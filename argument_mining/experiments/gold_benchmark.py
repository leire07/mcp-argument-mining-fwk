from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from ..client import OAMFClient
from ..errors import SerializationError
from ..evaluation import evaluate_relations, evaluate_segmentation
from ..models import ArgumentRelation, ArgumentSpan, ArgumentUnit
from ..models.common import StrictModel, utc_now
from ..pipeline import read_evidence, read_models, write_json
from ..registry import ModuleRegistry
from ..segmentation import create_segmenter
from ..xaif import argument_units_xaif, parse_unit_relations
from .config import load_mapping


class DatasetReference(StrictModel):
    name: str
    version: str
    split: str
    evaluation_reference: Literal["gold"] = "gold"
    evidence: Path
    gold_spans: Path
    argument_units: Path
    gold_relations: Path
    unmapped_relations: Path | None = None


class RelationSemantics(StrictModel):
    xaif_to_benchmark: dict[Literal["RA", "CA"], Literal["support", "attack"]]
    justification: str = Field(min_length=1)


class GoldBenchmarkConfig(StrictModel):
    benchmark_id: str
    dataset: DatasetReference
    registry: Path
    random_seed: int = 42
    segmentation_candidates: list[str] = Field(min_length=1)
    relation_candidates: list[str] = Field(min_length=1)
    relation_semantics: dict[str, RelationSemantics]
    propositionalisation_candidates: list[str] = Field(default_factory=lambda: ["SPG", "CPJ"])


def load_gold_benchmark_config(path: Path) -> GoldBenchmarkConfig:
    try:
        return GoldBenchmarkConfig.model_validate(load_mapping(path))
    except ValidationError as exc:
        raise SerializationError(f"Configuración de benchmark gold inválida en {path}: {exc}") from exc


def hardware_snapshot() -> dict:
    return {
        "os": platform.platform(), "machine": platform.machine(),
        "processor": platform.processor() or None, "logical_cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "gpu": os.environ.get("CUDA_VISIBLE_DEVICES", "unreported"),
        "ram_bytes": None, "vram_bytes": None,
    }


def artifact_filename(evidence_id: str) -> str:
    # Keep scientific IDs untouched; filenames must also be valid on Windows.
    return hashlib.sha256(evidence_id.encode('utf-8')).hexdigest() + '.json'


def _duration(run) -> float:
    return (datetime.fromisoformat(run.completed_at) - datetime.fromisoformat(run.started_at)).total_seconds()


def _csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def inspect_gold_benchmark(config: GoldBenchmarkConfig, registry: ModuleRegistry) -> dict:
    files = {name: {"path": str(path), "exists": path.exists()} for name, path in {
        "evidence": config.dataset.evidence, "gold_spans": config.dataset.gold_spans,
        "argument_units": config.dataset.argument_units, "gold_relations": config.dataset.gold_relations,
    }.items()}
    candidates = []
    for stage, modules in (("segmentation", config.segmentation_candidates),
                           ("relation_identification", config.relation_candidates)):
        for module_id in modules:
            try:
                spec = registry.get(module_id, stage)
                semantics = config.relation_semantics.get(module_id) if stage == "relation_identification" else None
                candidates.append({
                    "stage": stage, "module": module_id, "registered": True,
                    "endpoint_status": spec.endpoint_status,
                    "semantics_declared": semantics is not None if stage == "relation_identification" else None,
                    "runnable": spec.endpoint_status == "operational" and
                    (stage != "relation_identification" or semantics is not None),
                })
            except ValueError as exc:
                candidates.append({"stage": stage, "module": module_id, "registered": False,
                                   "runnable": False, "reason": str(exc)})
    return {
        "benchmark_id": config.benchmark_id, "protocol": "independent_stagewise_gold_benchmark",
        "cartesian_product": False, "automatic_selection": False,
        "dataset": config.dataset.model_dump(mode="json"), "files": files,
        "candidates": candidates, "ready": all(item["exists"] for item in files.values()),
    }


def run_gold_benchmark(config: GoldBenchmarkConfig, stage: Literal["segmentation", "relations"],
                       output: Path, client: OAMFClient | None = None) -> dict:
    if output.exists():
        raise SerializationError(f"La salida ya existe: {output}")
    output.mkdir(parents=True)
    client = client or OAMFClient()
    registry = ModuleRegistry(config.registry)
    raw_evidence, evidence = read_evidence(config.dataset.evidence)
    evidence_by_id = {item.evidence_id: item for item in evidence}
    write_json(output / "benchmark_config.json", config)
    write_json(output / "evidence.json", raw_evidence)
    write_json(output / "artifact_index.json", {
        item.evidence_id: artifact_filename(item.evidence_id) for item in evidence
    })
    started = time.perf_counter()
    rows, all_errors = [], []
    if stage == "segmentation":
        gold = read_models(config.dataset.gold_spans, ArgumentSpan)
        write_json(output / "gold_spans.json", gold)
        module_ids = config.segmentation_candidates
        for module_id in module_ids:
            spec = registry.get(module_id, "segmentation")
            module_dir = output / "modules" / module_id.lower().replace("-", "_")
            module_dir.mkdir(parents=True)
            predictions, runs, errors = [], [], []
            module = create_segmenter(spec, client)
            wall_started = time.perf_counter()
            for item in evidence:
                filename = artifact_filename(item.evidence_id)
                try:
                    result = module.run(item, f"{config.benchmark_id}_segmentation_{module_id}")
                    write_json(module_dir / "inputs" / filename, result.xaif_input)
                    write_json(module_dir / "raw" / filename, result.xaif_response)
                    predictions.extend(result.spans)
                    runs.append(result.module_run)
                except Exception as exc:  # failure is an experimental outcome
                    error = {"module": module_id, "stage": stage, "evidence_id": item.evidence_id,
                             "error_class": type(exc).__name__, "message": str(exc)}
                    errors.append(error)
                    if hasattr(exc, "xaif_input"):
                        write_json(module_dir / "inputs" / filename, exc.xaif_input)
                    if hasattr(exc, "xaif_response"):
                        write_json(module_dir / "raw" / filename, exc.xaif_response)
                    if hasattr(exc, "module_run"):
                        runs.append(exc.module_run)
                write_json(module_dir / "errors.json", errors)
                print(f'{module_id}: {item.evidence_id}; failures={len(errors)}', flush=True)
            wall_seconds = time.perf_counter() - wall_started
            metrics = evaluate_segmentation(predictions, gold)
            metrics["execution"] = _execution(len(evidence), errors, runs, wall_seconds)
            write_json(module_dir / "argument_spans.json", predictions)
            write_json(module_dir / "l_nodes.json", [
                {"nodeID": span.l_node_id, "type": "L", "text": span.source_span.text,
                 "span_id": span.span_id, "evidence_id": span.evidence_id,
                 "source_span": span.source_span.model_dump(mode="json")}
                for span in predictions
            ])
            write_json(module_dir / "module_runs.json", runs)
            write_json(module_dir / "errors.json", errors)
            write_json(module_dir / "metrics.json", metrics)
            manifest = _module_manifest(config, spec, stage, module_dir, metrics, wall_seconds)
            write_json(module_dir / "manifest.json", manifest)
            all_errors.extend(errors)
            rows.append(_segmentation_row(module_id, spec, metrics, module_dir))
        _csv(output / "segmentation_benchmark.csv", rows, list(rows[0]) if rows else [])
    else:
        gold = read_models(config.dataset.gold_relations, ArgumentRelation)
        units = read_models(config.dataset.argument_units, ArgumentUnit)
        write_json(output / "argument_units.json", units)
        write_json(output / "i_nodes.json", [
            {"nodeID": unit.i_node_id, "type": "I", "text": unit.source_span.text,
             "argument_unit_id": unit.unit_id, "evidence_id": unit.evidence_id,
             "component_type": unit.component_type, "evaluation_reference": "gold"}
            for unit in units
        ])
        write_json(output / "gold_relations.json", gold)
        unmapped_path = config.dataset.unmapped_relations
        excluded_pairs = set()
        if unmapped_path:
            unmapped = json.loads(unmapped_path.read_text(encoding='utf-8-sig'))
            write_json(output / "unmapped_relations.json", unmapped)
            excluded_pairs = {
                (f"{r['evidence_id']}:{r['source_original_id']}",
                 f"{r['evidence_id']}:{r['target_original_id']}") for r in unmapped
            }
        write_json(output / "excluded_pairs.json", sorted(excluded_pairs))
        grouped: dict[str, list[ArgumentUnit]] = defaultdict(list)
        for unit in units:
            grouped[unit.evidence_id].append(unit)
        candidate_pairs = [
            {"evidence_id": evidence_id, "source_claim_id": source.unit_id,
             "target_claim_id": target.unit_id}
            for evidence_id, group in grouped.items()
            for source in group for target in group if source.unit_id != target.unit_id
            and (source.unit_id, target.unit_id) not in excluded_pairs
        ]
        write_json(output / "candidate_pairs.json", candidate_pairs)
        for module_id in config.relation_candidates:
            spec = registry.get(module_id, "relation_identification")
            semantics = config.relation_semantics.get(module_id)
            module_dir = output / "modules" / module_id.lower().replace("-", "_")
            module_dir.mkdir(parents=True)
            predictions, runs, errors = [], [], []
            wall_started = time.perf_counter()
            if semantics is None:
                errors.append({"module": module_id, "stage": stage, "evidence_id": None,
                               "error_class": "MissingSemanticMapping",
                               "message": "No declared Support/Attack semantic mapping; candidate not executed"})
            else:
                allowed = set(semantics.xaif_to_benchmark)
                for evidence_id, group in grouped.items():
                    if len(group) < 2:
                        continue
                    request = argument_units_xaif(group)
                    filename = artifact_filename(evidence_id)
                    write_json(module_dir / "inputs" / filename, request)
                    try:
                        response, run = client.invoke(spec, request,
                                                      f"{config.benchmark_id}_relations_{module_id}")
                        write_json(module_dir / "raw" / filename, response)
                        runs.append(run)
                        parsed = parse_unit_relations(response, group, run, "predicted", allowed)
                        # Parser semantics are xAIF defaults. Re-map only through the declared contract.
                        for relation in parsed:
                            module_xaif_type = relation.xaif_relation_type
                            mapped = semantics.xaif_to_benchmark[module_xaif_type]
                            relation.relation = mapped
                            relation.xaif_relation_type = "RA" if mapped == "support" else "CA"
                            relation.label_mapping = {
                                "module_xaif_type": module_xaif_type,
                                "benchmark_label": mapped,
                                "justification": semantics.justification,
                            }
                        predictions.extend(parsed)
                    except Exception as exc:
                        error = {"module": module_id, "stage": stage, "evidence_id": evidence_id,
                                 "error_class": type(exc).__name__, "message": str(exc)}
                        errors.append(error)
                        if hasattr(exc, "xaif_response"):
                            write_json(module_dir / "raw" / filename, exc.xaif_response)
                    write_json(module_dir / "errors.json", errors)
                    print(f'{module_id}: {evidence_id}; failures={len(errors)}', flush=True)
            wall_seconds = time.perf_counter() - wall_started
            scored = [r for r in predictions
                      if (r.source_claim_id, r.target_claim_id) not in excluded_pairs]
            metrics = evaluate_relations(scored, gold, candidate_pairs)
            metrics['macro_f1_all_present_classes'] = metrics['macro_f1']
            metrics['macro_f1'] = sum(metrics['per_class'][label]['f1']
                                      for label in ('support', 'attack')) / 2
            metrics['macro_f1_labels'] = ['support', 'attack']
            metrics['excluded_partial_attack_pairs'] = len(excluded_pairs)
            metrics["execution"] = _execution(len(grouped), errors, runs, wall_seconds)
            write_json(module_dir / "relations.json", predictions)
            write_json(module_dir / "module_runs.json", runs)
            write_json(module_dir / "errors.json", errors)
            write_json(module_dir / "metrics.json", metrics)
            manifest = _module_manifest(config, spec, stage, module_dir, metrics, wall_seconds)
            manifest["relation_semantics"] = semantics.model_dump(mode="json") if semantics else None
            manifest['excluded_pairs'] = '../../excluded_pairs.json'
            manifest['reference_endpoint_kind'] = 'gold_extractive_argument_units'
            write_json(module_dir / "manifest.json", manifest)
            all_errors.extend(errors)
            rows.append(_relation_row(module_id, spec, metrics, module_dir))
        _csv(output / "relation_benchmark.csv", rows, list(rows[0]) if rows else [])
    result = {
        "benchmark_id": config.benchmark_id, "stage": stage,
        "evaluation_reference": "gold", "cartesian_product": False,
        "automatic_selection": False, "selected_module": None,
        "rows": rows, "errors": all_errors,
        "execution_seconds": time.perf_counter() - started,
    }
    write_json(output / "results.json", result)
    write_json(output / "error_analysis.json", {
        "evaluation_reference": "gold", "failures": all_errors,
        "failure_count": len(all_errors), "silent_failures_excluded": False,
    })
    return result


def build_propositionalisation_selection(config: GoldBenchmarkConfig, output: Path) -> dict:
    registry = ModuleRegistry(config.registry)
    candidates = []
    for module_id in config.propositionalisation_candidates:
        spec = registry.get(module_id, "propositionalisation")
        candidates.append({
            "module": module_id, "endpoint_status": spec.endpoint_status,
            "backend_type": spec.backend_type, "backend_id": spec.backend_id,
            "repository": spec.repository, "repository_commit": spec.repository_commit,
            "model": spec.model, "model_revision": spec.model_revision,
            "xAIF_compatible": True,
            "input_contract": "ArgumentSpan[] encoded as xAIF L nodes",
            "output_contract": "Claim[] / xAIF I nodes",
            "source_text_preservation_check": "required",
            "span_to_proposition_provenance": "supported by Claim.evidence_id + span_id + source_span",
            "empirically_ranked_on_normalised_gold_claims": False,
            "selection_factors": [
                "availability", "reproducibility", "xAIF compatibility",
                "source/provenance preservation", "compute requirements", "failure behaviour",
            ],
        })
    result = {
        "benchmark_id": config.benchmark_id, "evaluation_reference": "not_applicable",
        "reason": "No human-normalised gold propositions are available in AbstRCT",
        "automatic_selection": False, "empirical_best_module": None,
        "structural_baseline": "SPG", "baseline_is_claimed_best": False,
        "candidates": candidates,
    }
    write_json(output, result)
    return result


def _execution(total: int, errors: list[dict], runs: list, wall_seconds: float) -> dict:
    failures = len({error.get("evidence_id") for error in errors if error.get("evidence_id")})
    return {
        "total_items": total, "successful_items": max(0, total - failures),
        "failed_items": failures, "failure_rate": failures / total if total else 0.0,
        "wall_seconds": wall_seconds, "module_seconds": sum(_duration(run) for run in runs),
        "mean_latency_seconds": sum(_duration(run) for run in runs) / len(runs) if runs else None,
    }


def _module_manifest(config, spec, stage, module_dir, metrics, wall_seconds):
    return {
        "experiment_id": f"{config.benchmark_id}_{stage}_{spec.module_id}",
        "timestamp": utc_now(), "run_kind": f"gold_{stage}_benchmark",
        "evaluation_reference": "gold", "dataset_name": config.dataset.name,
        "dataset_version": config.dataset.version, "dataset_split": config.dataset.split,
        "random_seed": config.random_seed,
        "module": spec.model_dump(mode="json"), "hardware": hardware_snapshot(),
        "hardware_scope": "client only; remote inference hardware unreported",
        "remote_deployed_commit_verified": False if spec.backend_type == 'ws' else None,
        "container": spec.config.get("container", {}), "execution_seconds": wall_seconds,
        "outputs": {"directory": str(module_dir), "metrics": "metrics.json",
                    "module_runs": "module_runs.json", "errors": "errors.json"},
        "failure_policy": "failures remain in denominator and are recorded",
        "automatic_selection": False,
    }


def _segmentation_row(module_id, spec, metrics, module_dir):
    execution = metrics["execution"]
    return {
        "module": module_id, "backend": spec.backend_type, "endpoint": spec.endpoint,
        "exact_precision": metrics["exact_span"]["precision"],
        "exact_recall": metrics["exact_span"]["recall"], "exact_f1": metrics["exact_span"]["f1"],
        "overlap_precision": metrics["overlap_span"]["precision"],
        "overlap_recall": metrics["overlap_span"]["recall"],
        "overlap_f1": metrics["overlap_span"]["f1"],
        "over_segmentation": metrics["over_segmentation"]["count"],
        "under_segmentation": metrics["under_segmentation"]["count"],
        "failures": execution["failed_items"], "failure_rate": execution["failure_rate"],
        "wall_seconds": execution["wall_seconds"], "mean_latency_seconds": execution["mean_latency_seconds"],
        "run": str(module_dir),
    }


def _relation_row(module_id, spec, metrics, module_dir):
    execution = metrics["execution"]
    return {
        "module": module_id, "backend": spec.backend_type, "endpoint": spec.endpoint,
        "support_precision": metrics["per_class"]["support"]["precision"],
        "support_recall": metrics["per_class"]["support"]["recall"],
        "support_f1": metrics["per_class"]["support"]["f1"],
        "attack_precision": metrics["per_class"]["attack"]["precision"],
        "attack_recall": metrics["per_class"]["attack"]["recall"],
        "attack_f1": metrics["per_class"]["attack"]["f1"],
        "macro_f1": metrics["macro_f1"], "directed_edge_accuracy": metrics["directed_edge_accuracy"],
        "failures": execution["failed_items"], "failure_rate": execution["failure_rate"],
        "wall_seconds": execution["wall_seconds"], "mean_latency_seconds": execution["mean_latency_seconds"],
        "run": str(module_dir),
    }
