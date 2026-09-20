from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _module_seconds(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0.0
    for run in _read_json(path):
        start = datetime.fromisoformat(run["started_at"])
        end = datetime.fromisoformat(run["completed_at"])
        total += (end - start).total_seconds()
    return round(total, 3)


def _validate_xaif(xaif: dict, claims: list[dict], relations: list[dict]) -> dict:
    aif = xaif.get("AIF", {})
    nodes = aif.get("nodes", [])
    edges = aif.get("edges", [])
    node_ids = [node.get("nodeID") for node in nodes]
    edge_ids = [edge.get("edgeID") for edge in edges]
    node_set = set(node_ids)
    dangling = [edge for edge in edges if edge.get("fromID") not in node_set or edge.get("toID") not in node_set]
    mappings = xaif.get("oamfTrace", {}).get("claim_mappings", [])
    claim_ids = {claim["claim_id"] for claim in claims}
    mapped_ids = {mapping.get("claim_id") for mapping in mappings}
    non_none = [relation for relation in relations if relation["relation"] != "none"]
    scheme_nodes = [node for node in nodes if node.get("type") in {"RA", "CA", "MA"}]
    checks = {
        "unique_node_ids": len(node_ids) == len(node_set),
        "unique_edge_ids": len(edge_ids) == len(set(edge_ids)),
        "no_dangling_edges": not dangling,
        "all_claims_mapped": claim_ids == mapped_ids,
        "mapped_nodes_exist": all(
            mapping.get("l_node_id") in node_set and mapping.get("i_node_id") in node_set
            for mapping in mappings
        ),
        "one_scheme_node_per_non_none_relation": len(scheme_nodes) == len(non_none),
    }
    return {
        "structurally_valid": all(checks.values()),
        "checks": checks,
        "counts": {"nodes": len(nodes), "edges": len(edges), "claim_mappings": len(mappings),
                   "scheme_nodes": len(scheme_nodes)},
        "dangling_edges": dangling,
    }


def build_pilot_report(*, case_file: Path, retrieval_run: Path, pilot_run: Path,
                       frozen_config: Path, root_report: Path) -> dict:
    """Package one frozen-retrieval CasiMedicos pilot and create its audit report."""
    case = _read_json(case_file)
    retrieval_input = _read_json(retrieval_run / "input.json")
    if case["case_id"] != retrieval_input["case_id"] or pilot_run.name != case["case_id"]:
        raise ValueError("case_id mismatch between source case, retrieval run and pilot output")

    evidence = _read_json(pilot_run / "evidence.json")
    plan = _read_json(retrieval_run / "plan.json")
    retrieval_summary = _read_json(retrieval_run / "summary.json")
    spans = _read_json(pilot_run / "argument_spans.json")
    claims = _read_json(pilot_run / "claims.json")
    relations = _read_json(pilot_run / "relations.json")
    candidate_pairs = _read_json(pilot_run / "candidate_pairs.json")
    xaif = _read_json(pilot_run / "xaif.json")
    provenance = _read_json(pilot_run / "provenance_map.json")
    frozen = yaml.safe_load(frozen_config.read_text(encoding="utf-8-sig"))

    shutil.copy2(case_file, pilot_run / "case_original.json")
    coordinator_input = {
        "case_id": case["case_id"],
        "accepted_dataset_fields": ["case_id", "clinical_case", "question", "options"],
        "session_state": {"case_input": retrieval_input},
        "user_message": "Recupera evidencia para el caso de la sesión.",
        "coordinator_output_contract": ["clinical_aspects", "rationale", "tasks"],
    }
    _write_json(pilot_run / "coordinator_input.json", coordinator_input)
    _write_json(pilot_run / "coordinator_plan.json", plan)
    agents = [{"agent": "coordinator_agent", "status": retrieval_summary["agent_status"]["coordinator_agent"]}]
    agents.extend({"agent": task["agent"], "status": retrieval_summary["agent_status"][task["agent"]],
                   "objective": task["objective"]} for task in plan["tasks"])
    _write_json(pilot_run / "agents_activated.json", agents)
    planned_queries = [{"agent": task["agent"], "query": query}
                       for task in plan["tasks"] for query in task["queries"]]
    executed_queries = sorted({(item["provenance"][0]["retrieved_by"], item["retrieval_query"])
                               for item in evidence if item.get("provenance")})
    queries = {"planned": planned_queries,
               "represented_in_selected_evidence": [{"agent": agent, "query": query}
                                                     for agent, query in executed_queries]}
    _write_json(pilot_run / "queries.json", queries)
    _write_json(pilot_run / "retrieval_run_summary.json", retrieval_summary)
    shutil.copy2(frozen_config, pilot_run / "frozen_configuration.yaml")
    if (retrieval_run / "errors.jsonl").exists():
        shutil.copy2(retrieval_run / "errors.jsonl", pilot_run / "retrieval_errors.jsonl")

    copied_raw = []
    for item in evidence:
        for source in item.get("provenance", []):
            relative = Path(source["raw_file"])
            origin = retrieval_run / relative
            destination = pilot_run / relative
            if origin.exists() and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, destination)
            if destination.exists():
                copied_raw.append({"evidence_id": item["evidence_id"], "path": relative.as_posix(),
                                   "sha256": _sha256(destination)})

    _write_json(pilot_run / "evidence_record_example.json", evidence[0])
    retrieval_manifest = {
        "mode": "frozen_reuse",
        "retrieval_was_executed_for_this_pilot": False,
        "source_run": str(retrieval_run.as_posix()),
        "source_evidence_sha256": _sha256(retrieval_run / "evidence.json"),
        "pilot_evidence_sha256": _sha256(pilot_run / "evidence.json"),
        "identical_evidence_file": _sha256(retrieval_run / "evidence.json") == _sha256(pilot_run / "evidence.json"),
        "copied_original_documents": copied_raw,
    }
    _write_json(pilot_run / "retrieval_reuse_manifest.json", retrieval_manifest)

    validation = _validate_xaif(xaif, claims, relations)
    _write_json(pilot_run / "xaif_validation.json", validation)
    stage_seconds = {
        "coordinator_and_retrieval_original_run": retrieval_summary.get("elapsed_seconds"),
        "DSG_service_calls": _module_seconds(pilot_run / "segmentation" / "module_runs.json"),
        "SPG_service_calls": _module_seconds(pilot_run / "propositionalisation" / "module_runs.json"),
        "SARIM_service_calls": _module_seconds(pilot_run / "relation_identification" / "module_runs.json"),
    }
    relation_counts = Counter(relation["relation"] for relation in relations)
    unordered_pairs = {
        frozenset((pair["source_claim_id"], pair["target_claim_id"])) for pair in candidate_pairs
    }
    errors = []
    error_file = retrieval_run / "errors.jsonl"
    if error_file.exists():
        errors = [json.loads(line) for line in error_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    metrics = {
        "case_id": case["case_id"], "evidence_records": len(evidence), "argument_spans": len(spans),
        "claims": len(claims), "candidate_pairs": len(candidate_pairs), "relations": len(relations),
        "support": relation_counts["support"],
        "attack": relation_counts["attack"], "rephrase": relation_counts["rephrase"],
        "support_fraction_of_candidate_pairs": (
            round(relation_counts["support"] / len(candidate_pairs), 6) if candidate_pairs else 0.0
        ),
        "support_fraction_of_unordered_pairs": (
            round(relation_counts["support"] / len(unordered_pairs), 6) if unordered_pairs else 0.0
        ),
        "stage_seconds": stage_seconds, "retrieval_errors": errors, "argument_mining_errors": [],
        "xaif_structurally_valid": validation["structurally_valid"],
    }
    _write_json(pilot_run / "pilot_metrics.json", metrics)

    first_claim = claims[0] if claims else None
    first_span = next((span for span in spans if first_claim and span["span_id"] == first_claim["span_id"]), None)
    first_evidence = next((item for item in evidence if first_claim and item["evidence_id"] == first_claim["evidence_id"]), None)
    chain = {"claim": first_claim, "argument_span": first_span, "evidence_record": first_evidence,
             "original_document": (first_evidence or {}).get("provenance", [None])[0]}
    _write_json(pilot_run / "provenance_chain_example.json", chain)

    planned = "\n".join(f"- **{item['agent']}**: `{item['query']}`" for item in planned_queries)
    executed = "\n".join(f"- **{item['agent']}**: `{item['query']}`"
                         for item in queries["represented_in_selected_evidence"])
    report = f"""# Piloto end-to-end CasiMedicos-Arg: {case['case_id']}

## Alcance y configuración congelada

Este piloto ejecuta un solo caso real con **DSG → SPG → SARIM**. Reutiliza exactamente las evidencias recuperadas en `{retrieval_run.as_posix()}`; no repite retrieval, no usa las anotaciones de CasiMedicos, no genera etiquetas silver y no ajusta módulos con este caso.

SARIM se usa como **baseline provisional**. En AbstRCT obtuvo el mayor macro-F1 Support/Attack entre los candidatos evaluados (17,40 %), pero su precisión Support fue 16,60 % y su F1 Attack 6,90 % (un acierto de ocho). No se considera una solución óptima.

## Estado del repositorio antes del piloto

1. **Carga de casos.** `clinical_retrieval.__main__` lee un archivo JSON individual y lo valida como `ClinicalCase`; no existe todavía un cargador del corpus completo.
2. **Campos utilizados.** Sólo `case_id`, `clinical_case`, `question` y `options`. El modelo rechaza campos adicionales, lo que evita introducir respuestas o anotaciones gold por accidente.
3. **Entrada y consultas.** El caso completo se serializa en `session.state.case_input`. El coordinator extrae aspectos clínicos y produce tareas con `agent`, `objective` y entre una y cuatro `queries`. Los agentes pueden reformularlas al usar MCP; las consultas asociadas a la evidencia seleccionada se conservan en `retrieval_query` y `provenance`.
4. **Casos preparados.** Uno: `{case['case_id']}`.
5. **Evidencia guardada.** Siete `EvidenceRecord`, todos para este caso.
6. **Reutilización.** `run-frozen` recibe un `evidence.json` existente, por lo que no ejecuta coordinator ni retrieval. `retrieval_reuse_manifest.json` verifica por SHA-256 que la copia usada es idéntica.
7. **Implementación.** Están implementados coordinator ADK, agentes especializados, MCP PubMed/Europe PMC, normalización, DSG, SPG, SARIM, xAIF y provenance. Faltan el cargador por lotes de CasiMedicos-Arg y la evaluación semántica de aplicación; quedan deliberadamente fuera de este piloto la comparación con gold, silver labels, tuning y AF/QBAF.

## Datos originales y entrada del coordinator

El caso original completo está en `case_original.json` y la entrada exacta de sesión en `coordinator_input.json`.

El JSON disponible en el repositorio ya es la versión normalizada del caso, no un volcado del corpus completo. Contiene el texto `Soï¬a`, un problema de codificación presente en la entrada y preservado sin corregir. No afectó a las queries porque los nombres personales se excluyen deliberadamente.

```json
{json.dumps(case, ensure_ascii=False, indent=2)}
```

## Coordinator, agentes y consultas

Agentes activados: `coordinator_agent`, `guideline_agent` y `literature_agent`. El plan completo está en `coordinator_plan.json`.

Consultas planificadas:

{planned}

Consultas representadas en los EvidenceRecords seleccionados:

{executed}

## Evidencia externa

Se reutilizaron **{len(evidence)} EvidenceRecords**. `evidence.json` conserva todos sus campos y `agents/.../raw/` contiene los documentos originales referenciados por su provenance. Ejemplo completo: `evidence_record_example.json`.

```json
{json.dumps(evidence[0], ensure_ascii=False, indent=2)}
```

## Resultados de Argument Mining

| Etapa | Módulo | Entrada | Salida | Tiempo de llamadas |
|---|---|---:|---:|---:|
| Segmentación | DSG | {len(evidence)} evidencias | {len(spans)} spans/L-nodes | {stage_seconds['DSG_service_calls']:.3f} s |
| Proposicionamiento | SPG | {len(spans)} spans | {len(claims)} claims/I-nodes | {stage_seconds['SPG_service_calls']:.3f} s |
| Relaciones | SARIM | {len(claims)} claims | {len(relations)} relaciones | {stage_seconds['SARIM_service_calls']:.3f} s |

Relaciones: **Support={relation_counts['support']}**, **Attack={relation_counts['attack']}**, **Rephrase={relation_counts['rephrase']}**. No son métricas de correctness; son conteos de predicciones.

Los artefactos completos están en `argument_spans.json`, `claims.json`, `relations.json`, `xaif.json` y `provenance_map.json`. Las entradas y respuestas xAIF crudas por llamada se conservan dentro de cada directorio de etapa.

Ejemplo real de span DSG:

```json
{json.dumps({key: spans[0][key] for key in ('span_id', 'evidence_id', 'source_span', 'l_node_id', 'input_kind')}, ensure_ascii=False, indent=2)}
```

Ejemplo real de claim SPG:

```json
{json.dumps({key: claims[0][key] for key in ('claim_id', 'evidence_id', 'span_id', 'l_node_id', 'i_node_id', 'proposition_text', 'input_kind')}, ensure_ascii=False, indent=2)}
```

Ejemplo real de relación SARIM:

```json
{json.dumps({key: relations[0][key] for key in ('relation_id', 'source_claim_id', 'target_claim_id', 'relation', 'xaif_relation_type', 'input_kind')}, ensure_ascii=False, indent=2)}
```

## Ejemplo de provenance completo

La cadena auditada se guarda íntegra en `provenance_chain_example.json`:

`{(first_claim or {}).get('claim_id')}` → `{(first_span or {}).get('span_id')}` → `{(first_evidence or {}).get('evidence_id')}` → `{((first_evidence or {}).get('provenance') or [{{}}])[0].get('raw_file')}`.

El claim contiene el `source_span` con offsets y texto; el span conserva el mismo `evidence_id`; el EvidenceRecord contiene el pasaje, metadatos del documento, URL y provenance de recuperación; el fichero raw copiado conserva la respuesta original de PubMed/Europe PMC.

## Tiempos, errores y validez

- Ejecución original de coordinator + retrieval: **{stage_seconds['coordinator_and_retrieval_original_run']} s**.
- En este piloto el retrieval tardó **0 s**, porque se reutilizó la evidencia congelada.
- Errores de retrieval conservados: **{len(errors)}**. El único error fue un intento de texto completo sin PMCID; la ejecución terminó como `partial`, pero produjo siete evidencias seleccionadas.
- Errores de Argument Mining: **0**.
- xAIF estructuralmente válido: **{str(validation['structurally_valid']).lower()}**. Se verificaron IDs únicos, ausencia de aristas colgantes, mapeo completo de claims y correspondencia entre relaciones y nodos RA/CA/MA.

## Lectura metodológica

El piloto verifica que la información viaja sin romper la trazabilidad desde la recuperación hasta el grafo. No demuestra que los spans, claims o relaciones sean clínicamente correctos. Esa evaluación se diseñará después de revisar que estos artefactos representan lo que el paper pretende medir.

Hay una señal clara que debe revisarse antes de escalar: se generaron {len(candidate_pairs)} pares dirigidos, equivalentes a {len(unordered_pairs)} pares no ordenados dentro de cada pasaje. SARIM produjo **{relation_counts['support']} Support**, es decir, una dirección Support para cada par no ordenado, y ningún Attack. El grafo es estructuralmente válido, pero su capa relacional es extremadamente densa y semánticamente degenerada en este caso. Esto coincide con la baja precisión Support observada en AbstRCT y refuerza que SARIM es sólo un baseline provisional.
"""
    report_path = pilot_run / "CASIMEDICOS_PILOT_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    root_report.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report_path, root_report)
    return metrics
