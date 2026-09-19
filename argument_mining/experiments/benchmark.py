from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from ..errors import ArgumentMiningError, SerializationError
from ..evaluation import evaluate_propositions, evaluate_relations, evaluate_segmentation
from ..models import ArgumentRelation, ArgumentSpan, Claim, PairGeneration
from ..models.common import StrictModel
from ..pipeline import ArgumentMiningPipeline, read_evidence, read_models, write_json
from ..registry import ModuleRegistry
from .config import load_mapping
from .descriptive import describe_run


BenchmarkStage = Literal["segmentation", "propositionalisation", "relation_identification"]


class SelectionRule(StrictModel):
    primary_metric: str
    tie_breakers: list[str] = Field(default_factory=list)
    higher_is_better: bool = True
    manual_review_required: bool = True


class StageBenchmark(StrictModel):
    candidates: list[str] = Field(min_length=1)
    input_path: Path | None = Field(default=None, alias="input")
    gold: Path
    pair_strategy: Literal["within_passage", "within_document", "all"] = "within_passage"
    selection: SelectionRule


class StagewiseBenchmarkConfig(StrictModel):
    benchmark_id: str
    dataset_version: str
    gold_version: str
    evidence: Path
    registry: Path
    stages: dict[BenchmarkStage, StageBenchmark]


def load_benchmark_config(path: Path) -> StagewiseBenchmarkConfig:
    try:
        return StagewiseBenchmarkConfig.model_validate(load_mapping(path))
    except ValidationError as exc:
        raise SerializationError(f"Configuración de benchmark inválida en {path}: {exc}") from exc


def inspect_benchmark(config: StagewiseBenchmarkConfig, registry: ModuleRegistry) -> dict:
    stages = {}
    for stage, stage_config in config.stages.items():
        candidates = []
        for module_id in stage_config.candidates:
            try:
                spec = registry.get(module_id, stage)
                candidates.append({
                    "module": module_id,
                    "registered": True,
                    "backend_type": spec.backend_type,
                    "backend_id": spec.backend_id,
                    "endpoint_status": spec.endpoint_status,
                    "runnable": spec.endpoint_status == "operational",
                    "reason": None if spec.endpoint_status == "operational"
                    else f"endpoint_status={spec.endpoint_status}",
                })
            except ValueError as exc:
                candidates.append({"module": module_id, "registered": False, "runnable": False,
                                   "reason": str(exc)})
        input_required = stage != "segmentation"
        input_exists = stage_config.input_path.exists() if stage_config.input_path else not input_required
        gold_exists = stage_config.gold.exists()
        stages[stage] = {
            "input": str(stage_config.input_path) if stage_config.input_path else None,
            "input_exists": input_exists,
            "gold": str(stage_config.gold),
            "gold_exists": gold_exists,
            "selection": stage_config.selection.model_dump(mode="json"),
            "candidates": candidates,
            "ready": config.evidence.exists() and input_exists and gold_exists
            and sum(item["runnable"] for item in candidates) >= 2,
        }
    return {
        "benchmark_id": config.benchmark_id,
        "protocol": "sequential_stagewise_selection",
        "cartesian_product": False,
        "evidence": str(config.evidence),
        "evidence_exists": config.evidence.exists(),
        "stages": stages,
    }


def _metric(metrics: dict, path: str) -> float:
    value = metrics
    try:
        for key in path.split("."):
            value = value[key]
        return float(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise SerializationError(f"Métrica no encontrada: {path}") from exc


def rank_stage_results(rows: list[dict], rule: SelectionRule) -> dict:
    metric_paths = [rule.primary_metric, *rule.tie_breakers]
    completed = [row for row in rows if row["status"] == "completed"]
    for row in completed:
        row["ranking_values"] = {path: _metric(row["metrics"], path) for path in metric_paths}
    completed.sort(
        key=lambda row: tuple(row["ranking_values"][path] for path in metric_paths),
        reverse=rule.higher_is_better,
    )
    unique_winner = len(completed) >= 2 and (
        len(completed) == 1 or
        tuple(completed[0]["ranking_values"].values()) != tuple(completed[1]["ranking_values"].values())
    )
    # Ranking values support a later multi-criteria decision. Experiments never
    # freeze a module automatically, even when one metric has a unique leader.
    can_select = False
    return {
        "primary_metric": rule.primary_metric,
        "tie_breakers": rule.tie_breakers,
        "higher_is_better": rule.higher_is_better,
        "manual_review_required": rule.manual_review_required,
        "can_select_best_module": can_select,
        "selected_module": None,
        "automatic_leader": completed[0]["module"] if completed else None,
        "rows": rows,
    }


def run_stage_benchmark(config: StagewiseBenchmarkConfig, stage: BenchmarkStage,
                        output: Path) -> dict:
    if stage not in config.stages:
        raise SerializationError(f"La etapa {stage} no está declarada en el benchmark")
    stage_config = config.stages[stage]
    registry = ModuleRegistry(config.registry)
    readiness = inspect_benchmark(config, registry)["stages"][stage]
    if not config.evidence.exists() or not readiness["input_exists"] or not readiness["gold_exists"]:
        raise SerializationError(
            f"Benchmark {stage} no preparado: evidence/input/gold deben existir; "
            "ejecuta benchmark-check para ver los bloqueos"
        )
    runnable = [item["module"] for item in readiness["candidates"] if item["runnable"]]
    if len(runnable) < 2:
        raise SerializationError(
            f"Benchmark {stage} necesita al menos dos candidatos operativos; disponibles: {runnable}"
        )
    raw_evidence, evidence = read_evidence(config.evidence)
    pipeline = ArgumentMiningPipeline()
    rows = []

    if stage == "segmentation":
        gold = read_models(stage_config.gold, ArgumentSpan)
        if not gold:
            raise SerializationError("El gold de segmentación está vacío")
    elif stage == "propositionalisation":
        input_items = read_models(stage_config.input_path, ArgumentSpan)
        gold = read_models(stage_config.gold, Claim)
        if not input_items or not gold:
            raise SerializationError("Los spans gold y claims gold no pueden estar vacíos")
    else:
        input_items = read_models(stage_config.input_path, Claim)
        gold = read_models(stage_config.gold, ArgumentRelation)
        if not input_items or not gold:
            raise SerializationError("Los claims gold y relaciones gold no pueden estar vacíos")

    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "benchmark_config.json", config.model_dump(mode="json", by_alias=True))

    for module_id in stage_config.candidates:
        candidate_info = next(item for item in readiness["candidates"] if item["module"] == module_id)
        if not candidate_info["runnable"]:
            rows.append({"module": module_id, "status": "skipped", "reason": candidate_info["reason"]})
            continue
        run_dir = output / module_id.lower().replace("-", "_")
        experiment_id = f"{config.benchmark_id}_{stage}_{module_id.lower()}"
        spec = registry.get(module_id, stage)
        try:
            if stage == "segmentation":
                predicted = pipeline.segment(raw_evidence, evidence, spec, run_dir, experiment_id,
                                             config.dataset_version)
                metrics = evaluate_segmentation(predicted, gold)
            elif stage == "propositionalisation":
                predicted = pipeline.propositionalise(
                    raw_evidence, evidence, input_items, spec, run_dir, experiment_id, "gold",
                    config.dataset_version, config.gold_version,
                )
                metrics = evaluate_propositions(predicted, gold)
            else:
                predicted = pipeline.identify_relations(
                    raw_evidence, evidence, input_items, spec,
                    PairGeneration(strategy=stage_config.pair_strategy), run_dir, experiment_id,
                    "gold", config.dataset_version, config.gold_version,
                )
                pairs = json.loads((run_dir / "candidate_pairs.json").read_text(encoding="utf-8"))
                metrics = evaluate_relations(predicted, gold, pairs)
            write_json(run_dir / "metrics.json", metrics)
            description = describe_run(run_dir)
            rows.append({"module": module_id, "status": "completed", "metrics": metrics,
                         "module_seconds": description.get("module_seconds"),
                         "run": str(run_dir)})
        except ArgumentMiningError as exc:
            rows.append({"module": module_id, "status": "failed", "reason": str(exc),
                         "error_type": exc.error_type, "run": str(run_dir)})

    result = {
        "benchmark_id": config.benchmark_id,
        "stage": stage,
        "protocol": "sequential_stagewise_selection",
        "cartesian_product": False,
        "dataset_version": config.dataset_version,
        "gold_version": config.gold_version,
        "ranking": rank_stage_results(rows, stage_config.selection),
    }
    write_json(output / "leaderboard.json", result)
    (output / "report.md").write_text(_report(result), encoding="utf-8")
    return result


def _report(result: dict) -> str:
    ranking = result["ranking"]
    lines = [f"# Benchmark {result['stage']}", "",
             "Comparación por etapa; no se generó ningún producto cartesiano de pipelines.", "",
             f"Métrica primaria: `{ranking['primary_metric']}`.", "",
             "| Módulo | Estado | Valor primario | Tiempo |", "| --- | --- | ---: | ---: |"]
    for row in ranking["rows"]:
        value = row.get("ranking_values", {}).get(ranking["primary_metric"], "-")
        seconds = row.get("module_seconds")
        lines.append(f"| {row['module']} | {row['status']} | {value} | "
                     f"{f'{seconds} s' if seconds is not None else '-'} |")
    lines.extend(["", f"Primero en el orden descriptivo: `{ranking['automatic_leader']}`.", ""])
    lines.append("Las métricas informan la revisión; la infraestructura no selecciona ni fija módulos automáticamente.")
    lines.append("")
    return "\n".join(lines)
