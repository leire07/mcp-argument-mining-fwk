from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from .evaluation import (evaluate_application_run, evaluate_end_to_end, evaluate_propositions,
                         evaluate_relations, evaluate_segmentation)
from .datasets import AbstRCTAdapter
from .experiments.config import load_end_to_end_config, load_frozen_config
from .experiments.benchmark import (StagewiseBenchmarkConfig, inspect_benchmark,
                                    load_benchmark_config, run_stage_benchmark)
from .experiments.descriptive import describe_runs, markdown_report
from .experiments.availability import export_module_availability
from .experiments.gold_benchmark import (GoldBenchmarkConfig, build_propositionalisation_selection,
                                          inspect_gold_benchmark, load_gold_benchmark_config,
                                          run_gold_benchmark)
from .experiments.selection_report import build_selection_report
from .errors import ArgumentMiningError
from .deployment import build_repo_plan
from .models import (ArgumentRelation, ArgumentSpan, ArgumentUnit, Claim, EndToEndConfig, EvidenceRecord,
                     PairGeneration)
from .pipeline import (ArgumentMiningPipeline, read_evidence, read_models, selected_spec,
                       write_json)
from .registry import ModuleRegistry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "configs" / "oamf_public_modules.yaml"
DEFAULT_LOCAL_REGISTRY = ROOT / "configs" / "oamf_local_repo_modules.yaml"


def add_common(parser: argparse.ArgumentParser, *, evidence: bool = True):
    if evidence:
        parser.add_argument("--evidence", type=Path, required=True, help="Array evidence.json producido por MCP/RAG")
    parser.add_argument("--output", type=Path, required=True, help="Nueva carpeta para este experimento")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--dataset-version", default="unreported")
    parser.add_argument("--gold-version")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)


def add_module(parser: argparse.ArgumentParser):
    parser.add_argument("--module", required=True)
    parser.add_argument("--endpoint", help="Sustituye el endpoint del registro, también permite un despliegue local")
    parser.add_argument("--backend-type", choices=("ws", "repo"))
    parser.add_argument("--backend-id")
    parser.add_argument("--route")
    parser.add_argument("--repository")
    parser.add_argument("--repository-commit")
    parser.add_argument("--module-version")
    parser.add_argument("--model")
    parser.add_argument("--model-revision")
    parser.add_argument("--module-config", default="{}", help="Objeto JSON enviado al manifiesto del módulo")


def module_spec(registry: ModuleRegistry, args, stage: str):
    return selected_spec(registry.get(args.module, stage), args.endpoint, args.module_version,
                         args.model, json.loads(args.module_config), args.backend_type,
                         args.backend_id, args.route, args.repository, args.repository_commit,
                         args.model_revision)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Minería modular y trazable de argumentos con oAMF")
    commands = root.add_subparsers(dest="command", required=True)

    segment = commands.add_parser("segment", help="Evidencia cruda -> spans/L-nodes")
    add_common(segment)
    add_module(segment)

    propositions = commands.add_parser("propositions", help="Spans gold o predichos -> claims/I-nodes")
    add_common(propositions)
    add_module(propositions)
    propositions.add_argument("--spans", type=Path, required=True)
    propositions.add_argument("--input-kind", choices=("gold", "predicted"), required=True)

    relations = commands.add_parser("relations", help="Claims gold o predichos -> relaciones/xAIF")
    add_common(relations)
    add_module(relations)
    relations.add_argument("--claims", type=Path, required=True)
    relations.add_argument("--input-kind", choices=("gold", "predicted"), required=True)
    relations.add_argument("--pair-strategy", choices=("within_passage", "within_document", "all"),
                           default="within_passage")

    run = commands.add_parser("run", help="Ejecución completa con una configuración declarada")
    run.add_argument("--evidence", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True, help="Configuración experimental YAML o JSON")
    run.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    run.add_argument("--output", type=Path, required=True)
    frozen_run = commands.add_parser(
        "run-frozen", help="Aplica una configuración manualmente congelada a evidencia UNANNOTATED"
    )
    frozen_run.add_argument("--evidence", type=Path, required=True)
    frozen_run.add_argument("--config", type=Path, required=True)
    frozen_run.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    frozen_run.add_argument("--experiment-id", required=True)
    frozen_run.add_argument("--dataset-version", default="unreported")
    frozen_run.add_argument("--output", type=Path, required=True)

    export = commands.add_parser("export", help="Claims + relaciones -> xAIF trazable, sin inferencia")
    add_common(export)
    export.add_argument("--claims", type=Path, required=True)
    export.add_argument("--relations", type=Path, required=True)

    evaluate = commands.add_parser("evaluate", help="Evaluación separada, sin ejecutar inferencia")
    evaluate.add_argument("--stage", choices=("segmentation", "propositionalisation", "relations", "end_to_end"), required=True)
    evaluate.add_argument("--predicted", type=Path, required=True)
    evaluate.add_argument("--gold", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--candidate-pairs", type=Path,
                          help="candidate_pairs.json para derivar la clase none en relaciones")

    list_modules = commands.add_parser("list-modules")
    list_modules.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    schemas = commands.add_parser("schemas", help="Exportar contratos JSON Schema")
    schemas.add_argument("--output", type=Path, required=True)
    describe = commands.add_parser("describe", help="Comparación descriptiva de ejecuciones, sin gold")
    describe.add_argument("--runs", type=Path, nargs="+", required=True)
    describe.add_argument("--output", type=Path, required=True)
    repo_plan = commands.add_parser("repo-plan", help="Genera el plan repo fijado; no clona ni despliega")
    repo_plan.add_argument("--registry", type=Path, default=DEFAULT_LOCAL_REGISTRY)
    repo_plan.add_argument("--modules", nargs="*")
    repo_plan.add_argument("--output", type=Path, required=True)
    benchmark_check = commands.add_parser(
        "benchmark-check", help="Comprueba gold, inputs y candidatos sin ejecutar inferencia"
    )
    benchmark_check.add_argument("--config", type=Path, required=True)
    benchmark_check.add_argument("--output", type=Path, required=True)
    benchmark = commands.add_parser(
        "benchmark", help="Compara candidatos de una sola etapa sobre la misma entrada gold"
    )
    benchmark.add_argument("--config", type=Path, required=True)
    benchmark.add_argument("--stage", choices=("segmentation", "propositionalisation",
                                                "relation_identification"), required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    adapt = commands.add_parser("adapt-abstrct", help="Adapta el BRAT oficial de AbstRCT sin fabricar gold claims")
    adapt.add_argument("--source", type=Path, required=True, help="Directorio AbstRCT_corpus/data")
    adapt.add_argument("--split", choices=("train", "dev", "test"), required=True)
    adapt.add_argument("--subset")
    adapt.add_argument("--max-documents", type=int)
    adapt.add_argument("--output", type=Path, required=True)
    gold_check = commands.add_parser("gold-benchmark-check", help="Valida entradas del benchmark AbstRCT")
    gold_check.add_argument("--config", type=Path, required=True)
    gold_check.add_argument("--output", type=Path, required=True)
    gold_run = commands.add_parser("gold-benchmark", help="Evalúa una etapa sobre GOLD sin seleccionar ganador")
    gold_run.add_argument("--config", type=Path, required=True)
    gold_run.add_argument("--stage", choices=("segmentation", "relations"), required=True)
    gold_run.add_argument("--output", type=Path, required=True)
    prop_selection = commands.add_parser(
        "proposition-selection", help="Genera el informe estructural, sin afirmar un mejor módulo empírico"
    )
    prop_selection.add_argument("--config", type=Path, required=True)
    prop_selection.add_argument("--output", type=Path, required=True)
    audit = commands.add_parser("audit-modules", help="Exporta disponibilidad y recursos de candidatos")
    audit.add_argument("--public-registry", type=Path, default=DEFAULT_REGISTRY)
    audit.add_argument("--repo-registry", type=Path, default=DEFAULT_LOCAL_REGISTRY)
    audit.add_argument("--resources", type=Path, default=ROOT / "configs" / "oamf_module_resources.yaml")
    audit.add_argument("--output", type=Path, required=True)
    app_eval = commands.add_parser(
        "evaluate-application", help="Evalúa proceso, trazabilidad y grafo sobre evidencia UNANNOTATED"
    )
    app_eval.add_argument("--run", type=Path, required=True)
    app_eval.add_argument("--output", type=Path, required=True)
    selection = commands.add_parser(
        "selection-report", help="Integra evidencia multi-criterio sin seleccionar automáticamente"
    )
    selection.add_argument("--availability", type=Path, required=True)
    selection.add_argument("--segmentation-results", type=Path)
    selection.add_argument("--relation-results", type=Path)
    selection.add_argument("--propositionalisation", type=Path)
    selection.add_argument("--output", type=Path, required=True)
    return root


def main():
    args = parser().parse_args()
    if args.command == "list-modules":
        registry = ModuleRegistry(args.registry)
        for stage in ("segmentation", "propositionalisation", "relation_identification"):
            print(f"{stage}:")
            for spec in registry.specs(stage):
                print(f"  {spec.module_id}: {spec.backend_type}/{spec.backend_id}; "
                      f"{spec.endpoint_status}; {spec.endpoint}")
        return
    if args.command == "adapt-abstrct":
        manifest = AbstRCTAdapter(args.source).export(
            args.output, args.split, args.subset, args.max_documents
        )
        print(f"AbstRCT adaptado: {manifest['counts']['evidence']} documentos. Salida: {args.output.resolve()}")
        return
    if args.command == "gold-benchmark-check":
        config = load_gold_benchmark_config(args.config)
        write_json(args.output, inspect_gold_benchmark(config, ModuleRegistry(config.registry)))
        print(f"Preparación del benchmark GOLD: {args.output.resolve()}")
        return
    if args.command == "gold-benchmark":
        config = load_gold_benchmark_config(args.config)
        result = run_gold_benchmark(config, args.stage, args.output)
        print(f"Benchmark GOLD {args.stage}: {len(result['rows'])} candidatos; sin selección automática")
        return
    if args.command == "proposition-selection":
        config = load_gold_benchmark_config(args.config)
        build_propositionalisation_selection(config, args.output)
        print(f"Informe de proposicionamiento: {args.output.resolve()}")
        return
    if args.command == "audit-modules":
        rows = export_module_availability(args.public_registry, args.repo_registry, args.resources, args.output)
        print(f"Auditoría: {len(rows)} módulos. Salida: {args.output.resolve()}")
        return
    if args.command == "evaluate-application":
        evaluate_application_run(args.run, args.output)
        print(f"Evaluación UNANNOTATED: {args.output.resolve()}")
        return
    if args.command == "selection-report":
        build_selection_report(args.output, args.availability, args.segmentation_results,
                               args.relation_results, args.propositionalisation)
        print(f"Informe multi-criterio (sin selección automática): {args.output.resolve()}")
        return
    if args.command == "schemas":
        contracts = {
            "evidence.schema.json": TypeAdapter(list[EvidenceRecord]).json_schema(),
            "argument_spans.schema.json": TypeAdapter(list[ArgumentSpan]).json_schema(),
            "argument_units.schema.json": TypeAdapter(list[ArgumentUnit]).json_schema(),
            "claims.schema.json": TypeAdapter(list[Claim]).json_schema(),
            "relations.schema.json": TypeAdapter(list[ArgumentRelation]).json_schema(),
            "experiment.schema.json": EndToEndConfig.model_json_schema(),
            "benchmark.schema.json": StagewiseBenchmarkConfig.model_json_schema(),
            "gold_benchmark.schema.json": GoldBenchmarkConfig.model_json_schema(),
        }
        for filename, schema in contracts.items():
            write_json(args.output / filename, schema)
        print(f"Esquemas: {args.output.resolve()}")
        return
    if args.command == "repo-plan":
        plan = build_repo_plan(ModuleRegistry(args.registry), args.modules)
        write_json(args.output, plan)
        print(f"Plan repo fijado (sin despliegue): {args.output.resolve()}")
        return
    if args.command == "benchmark-check":
        config = load_benchmark_config(args.config)
        readiness = inspect_benchmark(config, ModuleRegistry(config.registry))
        write_json(args.output, readiness)
        print(f"Preparación del benchmark: {args.output.resolve()}")
        return
    if args.command == "benchmark":
        config = load_benchmark_config(args.config)
        result = run_stage_benchmark(config, args.stage, args.output)
        leader = result["ranking"]["automatic_leader"]
        print(f"Benchmark {args.stage}: orden descriptivo={leader}; sin selección automática. "
              f"Salida: {args.output.resolve()}")
        return
    if args.command == "describe":
        summary = describe_runs(args.runs)
        write_json(args.output / "summary.json", summary)
        (args.output / "report.md").write_text(markdown_report(summary), encoding="utf-8")
        print(f"Comparación descriptiva: {args.output.resolve()}")
        return
    if args.command == "evaluate":
        if args.stage == "segmentation":
            result = evaluate_segmentation(read_models(args.predicted, ArgumentSpan),
                                           read_models(args.gold, ArgumentSpan))
        elif args.stage == "propositionalisation":
            result = evaluate_propositions(read_models(args.predicted, Claim), read_models(args.gold, Claim))
        elif args.stage == "relations":
            pairs = json.loads(args.candidate_pairs.read_text(encoding="utf-8-sig")) if args.candidate_pairs else None
            result = evaluate_relations(read_models(args.predicted, ArgumentRelation),
                                        read_models(args.gold, ArgumentRelation), pairs)
        else:
            pairs_path = args.predicted / "candidate_pairs.json"
            pairs = json.loads(pairs_path.read_text(encoding="utf-8-sig")) if pairs_path.exists() else None
            result = evaluate_end_to_end(
                read_models(args.predicted / "argument_spans.json", ArgumentSpan),
                read_models(args.gold / "argument_spans.json", ArgumentSpan),
                read_models(args.predicted / "claims.json", Claim),
                read_models(args.gold / "claims.json", Claim),
                read_models(args.predicted / "relations.json", ArgumentRelation),
                read_models(args.gold / "relations.json", ArgumentRelation), pairs,
            )
        write_json(args.output, result)
        print(f"Métricas: {args.output.resolve()}")
        return
    if args.command == "run-frozen":
        frozen = load_frozen_config(args.config)
        raw, evidence = read_evidence(args.evidence)
        registry = ModuleRegistry(args.registry)
        selections = {
            "segmentation": frozen.segmentation,
            "propositionalisation": frozen.propositionalisation,
            "relation_identification": frozen.relation_identification,
        }
        specs = {}
        for stage, selection in selections.items():
            base = registry.get(selection.module, stage)
            specs[stage] = selected_spec(base, selection.endpoint, selection.version,
                                         selection.model, selection.config, selection.backend_type,
                                         selection.backend_id, selection.route, selection.repository,
                                         selection.repository_commit, selection.model_revision)
        config = EndToEndConfig(
            experiment_id=args.experiment_id, dataset_version=args.dataset_version,
            random_seed=frozen.random_seed, segmentation=frozen.segmentation,
            propositionalisation=frozen.propositionalisation,
            relation_identification=frozen.relation_identification,
        )
        spans, claims, relations = ArgumentMiningPipeline().end_to_end(
            raw, evidence, config, specs, args.output
        )
        print(f"Configuración congelada aplicada: {len(spans)} spans, {len(claims)} claims, "
              f"{len(relations)} relaciones. Salida: {args.output.resolve()}")
        return

    raw, evidence = read_evidence(args.evidence)
    registry = ModuleRegistry(args.registry)
    pipeline = ArgumentMiningPipeline()
    if args.command == "segment":
        spec = module_spec(registry, args, "segmentation")
        spans = pipeline.segment(raw, evidence, spec, args.output, args.experiment_id, args.dataset_version)
        print(f"Segmentos: {len(spans)}. Salida: {args.output.resolve()}")
    elif args.command == "propositions":
        spec = module_spec(registry, args, "propositionalisation")
        spans = read_models(args.spans, ArgumentSpan)
        claims = pipeline.propositionalise(raw, evidence, spans, spec, args.output, args.experiment_id,
                                           args.input_kind, args.dataset_version, args.gold_version)
        print(f"Proposiciones: {len(claims)}. Salida: {args.output.resolve()}")
    elif args.command == "relations":
        spec = module_spec(registry, args, "relation_identification")
        claims = read_models(args.claims, Claim)
        relations = pipeline.identify_relations(raw, evidence, claims, spec,
                                                PairGeneration(strategy=args.pair_strategy), args.output,
                                                args.experiment_id, args.input_kind,
                                                args.dataset_version, args.gold_version)
        print(f"Relaciones: {len(relations)}. Salida: {args.output.resolve()}")
    elif args.command == "export":
        claims = read_models(args.claims, Claim)
        relations = read_models(args.relations, ArgumentRelation)
        pipeline.export_xaif(raw, evidence, claims, relations, args.output, args.experiment_id,
                             args.dataset_version)
        print(f"xAIF: {(args.output / 'xaif.json').resolve()}")
    else:
        config = load_end_to_end_config(args.config)
        selections = {
            "segmentation": config.segmentation,
            "propositionalisation": config.propositionalisation,
            "relation_identification": config.relation_identification,
        }
        specs = {}
        for stage, selection in selections.items():
            base = registry.get(selection.module, stage)
            specs[stage] = selected_spec(base, selection.endpoint, selection.version,
                                         selection.model, selection.config, selection.backend_type,
                                         selection.backend_id, selection.route, selection.repository,
                                         selection.repository_commit, selection.model_revision)
        spans, claims, relations = pipeline.end_to_end(raw, evidence, config, specs, args.output)
        print(f"Spans: {len(spans)}; claims: {len(claims)}; relaciones: {len(relations)}. "
              f"Salida: {args.output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except ArgumentMiningError as exc:
        print(f"[{exc.error_type}] {exc}", file=sys.stderr)
        raise SystemExit(2)
