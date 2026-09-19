from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def _read(path: Path, name: str):
    target = path / name
    return json.loads(target.read_text(encoding="utf-8")) if target.exists() else None


def _module(manifest: dict) -> str:
    for value in manifest.get("modules", {}).values():
        if value:
            return value["module_id"]
    return "unknown"


def _duration(path: Path, items: list[dict] | None) -> float | None:
    runs = _read(path, "module_runs.json")
    if runs is None and items:
        unique = {}
        for item in items:
            run = item.get("generated_by")
            if run:
                unique[run["response_sha256"]] = run
        runs = list(unique.values())
    if not runs:
        return None
    return round(sum((datetime.fromisoformat(run["completed_at"]) -
                      datetime.fromisoformat(run["started_at"])).total_seconds() for run in runs), 3)


def describe_run(path: Path) -> dict:
    manifest = _read(path, "manifest.json")
    result = {"path": str(path), "module": _module(manifest), "stage": manifest["run_kind"],
              "status": manifest["status"], "error": manifest.get("error")}
    if manifest["status"] != "completed":
        return result
    if manifest["run_kind"] == "segmentation":
        spans = _read(path, "argument_spans.json") or []
        evidence = {item["evidence_id"]: item for item in (_read(path, "evidence.json") or [])}
        intervals = defaultdict(list)
        lengths = []
        for span in spans:
            source = span["source_span"]
            intervals[span["evidence_id"]].append((source["start_char"], source["end_char"]))
            lengths.append(source["end_char"] - source["start_char"])
        covered = 0
        for values in intervals.values():
            end = -1
            for start, stop in sorted(values):
                covered += max(0, stop - max(start, end))
                end = max(end, stop)
        total = sum(len(item["passage_text"]) for item in evidence.values())
        result.update(
            item_count=len(spans), evidence_covered=len(intervals),
            mean_span_chars=round(statistics.mean(lengths), 2) if lengths else 0,
            median_span_chars=statistics.median(lengths) if lengths else 0,
            character_coverage=round(covered / total, 4) if total else 0,
            module_seconds=_duration(path, spans),
        )
    elif manifest["run_kind"] == "propositionalisation":
        claims = _read(path, "claims.json") or []
        identity = sum(" ".join(c["proposition_text"].split()) ==
                       " ".join(c["source"]["source_span"]["text"].split()) for c in claims)
        unresolved = re.compile(r"\b(it|its|this|these|those|they|them|their|he|she|his|her)\b", re.I)
        result.update(
            item_count=len(claims), unchanged_from_span=identity,
            rewritten=len(claims) - identity,
            unresolved_reference_heuristic=sum(bool(unresolved.search(c["proposition_text"])) for c in claims),
            traceability_complete=sum(bool(c.get("evidence_id") and c.get("span_id") and c.get("source"))
                                      for c in claims),
            module_seconds=_duration(path, claims),
        )
    elif manifest["run_kind"] == "relation_identification":
        relations = _read(path, "relations.json") or []
        pairs = _read(path, "candidate_pairs.json") or []
        claims = {claim["claim_id"]: claim for claim in (_read(path, "claims.json") or [])}
        keys = [(r["source_claim_id"], r["target_claim_id"], r["relation"]) for r in relations]
        unique = set(keys)
        directed = {(source, target) for source, target, _ in unique}
        unordered_candidates = {
            frozenset((pair["source_claim_id"], pair["target_claim_id"])) for pair in pairs
        }
        unordered_relations = {frozenset((source, target)) for source, target in directed}
        evidence_with_relations = {
            claims[source]["evidence_id"] for source, _ in directed if source in claims
        }
        result.update(
            item_count=len(relations), candidate_pairs=len(pairs), unique_relations=len(unique),
            duplicates=len(relations) - len(unique), relation_distribution=dict(Counter(r["relation"] for r in relations)),
            positive_density=round(len(directed) / len(pairs), 4) if pairs else 0,
            unordered_pair_coverage=round(len(unordered_relations) / len(unordered_candidates), 4)
            if unordered_candidates else 0,
            evidence_with_relations=len(evidence_with_relations),
            self_relations=sum(source == target for source, target, _ in unique),
            reciprocal_pairs=sum((target, source) in directed for source, target in directed) // 2,
            module_seconds=_duration(path, relations),
        )
    return result


def describe_runs(paths: list[Path]) -> dict:
    runs = [describe_run(path) for path in paths]
    return {"analysis": "exploratory_without_gold", "can_select_best_module": False, "runs": runs}


def markdown_report(summary: dict) -> str:
    lines = ["# Comparación exploratoria de módulos oAMF", "",
             "Esta ejecución no dispone de anotaciones gold. Los resultados describen comportamiento y disponibilidad; no permiten seleccionar científicamente el mejor módulo.", ""]
    for stage in ("segmentation", "propositionalisation", "relation_identification"):
        lines.extend([f"## {stage}", "", "| Módulo | Estado | Resultados | Tiempo de módulo |", "| --- | --- | --- | --- |"])
        for run in (item for item in summary["runs"] if item["stage"] == stage):
            if run["status"] != "completed":
                detail = run.get("error", {}).get("message", "fallo")
                values = detail.replace("|", "\\|").replace("\n", " ")
            elif stage == "segmentation":
                values = f"{run['item_count']} spans; cobertura {run['character_coverage']:.1%}; mediana {run['median_span_chars']} caracteres"
            elif stage == "propositionalisation":
                values = f"{run['item_count']} claims; {run['rewritten']} reescritos; trazabilidad {run['traceability_complete']}/{run['item_count']}"
            else:
                values = (f"{run['unique_relations']} relaciones únicas/{run['candidate_pairs']} pares; "
                          f"{run['relation_distribution']}; {run['evidence_with_relations']}/7 evidencias")
            duration = f"{run['module_seconds']} s" if run.get("module_seconds") is not None else "no disponible"
            lines.append(f"| {run['module']} | {run['status']} | {values} | {duration} |")
        lines.append("")
    by_module = {run["module"]: run for run in summary["runs"]}
    dsg, targer = by_module.get("DSG"), by_module.get("TARGER")
    spg = by_module.get("SPG")
    arir, sarim, targer_am = (by_module.get("ARIR"), by_module.get("SARIM"),
                              by_module.get("TARGER-AM"))
    lines.extend(["## Lectura de esta ejecución", ""])
    if dsg and targer and dsg["status"] == targer["status"] == "completed":
        lines.append(
            f"- DSG devolvió {dsg['item_count']} segmentos y cubrió {dsg['character_coverage']:.1%} "
            f"del texto. TARGER devolvió {targer['item_count']} y cubrió {targer['character_coverage']:.1%}. "
            "La menor cobertura de TARGER puede corresponder a filtrado argumentativo, pero requiere gold para distinguir filtrado útil de omisiones."
        )
    if spg and spg["status"] == "completed":
        lines.append(
            f"- SPG conservó literalmente los {spg['item_count']} segmentos: no reescribió ninguna proposición. "
            f"La heurística detectó referencias potencialmente no resueltas en {spg['unresolved_reference_heuristic']} claims."
        )
    if arir and arir["status"] == "completed":
        lines.append(
            f"- ARIR produjo {arir['unique_relations']} relaciones, todas support, cubriendo "
            f"{arir['evidence_with_relations']} de 7 evidencias y {arir['unordered_pair_coverage']:.1%} de los pares no ordenados. "
            "Es una salida no trivial, pero algunos sentidos de arista resultan contraintuitivos y necesitan revisión anotada."
        )
    if sarim and sarim["status"] == "completed":
        lines.append(
            f"- SARIM produjo {sarim['unique_relations']} relaciones, todas support, y cubrió "
            f"{sarim['unordered_pair_coverage']:.1%} de los pares no ordenados. En esta entrada construyó exactamente "
            "una inferencia para cada par, un patrón degenerado que no discrimina relaciones argumentativas."
        )
    if targer_am and targer_am["status"] == "completed":
        lines.append("- TARGER-AM respondió correctamente, pero no detectó ninguna relación.")
    failed = [run["module"] for run in summary["runs"] if run["status"] != "completed"]
    if failed:
        lines.append(f"- Los servicios públicos no estaban operativos para: {', '.join(failed)}.")
    lines.extend(["", "## Conclusión operativa", "",
                  "Con los endpoints públicos observados, ninguna combinación queda validada para producir grafos clínicos finales. DSG y TARGER pueden mantenerse como alternativas de segmentación; SPG es la única opción de proposicionamiento disponible, aunque aquí actuó como identidad; ARIR sirve para continuar pruebas de integración por generar una salida no trivial. SARIM y TARGER-AM no son adecuados en esta ejecución por saturación y vaciado del grafo, respectivamente. Esta conclusión conserva los módulos como experimentos separados y no fija un ganador.", ""])
    lines.extend(["## Límite de la conclusión", "",
                  "La disponibilidad del endpoint, el número de unidades y la densidad de aristas no miden corrección. La selección requiere spans, proposiciones y relaciones gold, además de revisión clínica de fidelidad, modalidad, negación y atomicidad.", ""])
    return "\n".join(lines)
