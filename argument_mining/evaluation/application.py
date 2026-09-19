from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from ..errors import SerializationError
from ..pipeline import write_json


def _read(path: Path, name: str, default):
    target = path / name
    return json.loads(target.read_text(encoding="utf-8-sig")) if target.exists() else default


def _csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def evaluate_application_run(run: Path, output: Path) -> dict:
    """Evaluate processing and traceability on UNANNOTATED application evidence."""
    if output.exists():
        raise SerializationError(f"La salida ya existe: {output}")
    output.mkdir(parents=True)
    evidence = _read(run, "evidence.json", [])
    spans = _read(run, "argument_spans.json", [])
    claims = _read(run, "claims.json", [])
    relations = _read(run, "relations.json", [])
    xaif = _read(run, "xaif.json", {})
    provenance = _read(run, "provenance_map.json", {})
    manifest = _read(run, "manifest.json", {})
    evidence_by_id = {item.get("evidence_id"): item for item in evidence}
    spans_by_evidence = Counter(item.get("evidence_id") for item in spans)
    claims_by_evidence = Counter(item.get("evidence_id") for item in claims)
    claim_ids = {item.get("claim_id") for item in claims}

    processing_rows = []
    for item in evidence:
        evidence_id = item["evidence_id"]
        local_claim_ids = {claim.get("claim_id") for claim in claims
                           if claim.get("evidence_id") == evidence_id}
        processing_rows.append({
            "evidence_id": evidence_id, "evaluation_reference": "unannotated",
            "input_characters": len(item.get("passage_text", "")),
            "span_count": spans_by_evidence[evidence_id], "claim_count": claims_by_evidence[evidence_id],
            "relation_count": sum(r.get("source_claim_id") in local_claim_ids for r in relations),
            "segmentation_processed": spans_by_evidence[evidence_id] > 0,
            "propositionalisation_processed": claims_by_evidence[evidence_id] > 0,
            "relation_stage_processed": bool(claims),
        })

    traceability_rows = []
    for claim in claims:
        source = claim.get("source", {})
        source_span = source.get("source_span", {})
        record = evidence_by_id.get(claim.get("evidence_id"))
        start, end = source_span.get("start_char"), source_span.get("end_char")
        exact = bool(record and isinstance(start, int) and isinstance(end, int) and
                     record.get("passage_text", "")[start:end] == source_span.get("text"))
        traceability_rows.append({
            "claim_id": claim.get("claim_id"), "evidence_id": claim.get("evidence_id"),
            "span_id": claim.get("span_id"), "evaluation_reference": "unannotated",
            "evidence_exists": record is not None, "source_span_exact": exact,
            "retrieval_provenance_preserved": source.get("retrieval_provenance") ==
            (record or {}).get("provenance", []),
            "document_metadata_present": bool(source.get("document")),
            "generated_by_present": bool(claim.get("generated_by")),
        })

    aif = xaif.get("AIF", xaif.get("aif", {})) if isinstance(xaif, dict) else {}
    nodes = aif.get("nodes", []) if isinstance(aif, dict) else []
    edges = aif.get("edges", []) if isinstance(aif, dict) else []
    node_ids = [str(node.get("nodeID")) for node in nodes]
    node_id_set = set(node_ids)
    node_by_id = {str(node.get("nodeID")): node for node in nodes}
    incoming = Counter(str(edge.get("toID")) for edge in edges)
    outgoing = Counter(str(edge.get("fromID")) for edge in edges)
    orphan_edges = sum(str(edge.get("fromID")) not in node_id_set or
                       str(edge.get("toID")) not in node_id_set for edge in edges)
    orphan_i_nodes = sum(node.get("type") == "I" and not
                         (incoming[str(node.get("nodeID"))] or outgoing[str(node.get("nodeID"))])
                         for node in nodes)
    invalid_relation_refs = sum(
        relation.get("source_claim_id") not in claim_ids or relation.get("target_claim_id") not in claim_ids
        for relation in relations
    )
    relation_counts = Counter(r.get("relation") for r in relations)
    possible_directed_relations = len(claims) * max(0, len(claims) - 1)
    graph_rows = [{
        "run": str(run), "evaluation_reference": "unannotated",
        "evidence_count": len(evidence), "span_count": len(spans), "claim_count": len(claims),
        "relation_count": len(relations), "node_count": len(nodes), "edge_count": len(edges),
        "l_nodes": sum(node.get("type") == "L" for node in nodes),
        "i_nodes": sum(node.get("type") == "I" for node in nodes),
        "ra_nodes": sum(node.get("type") == "RA" for node in nodes),
        "ca_nodes": sum(node.get("type") == "CA" for node in nodes),
        "duplicate_node_ids": len(node_ids) - len(node_id_set), "orphan_edges": orphan_edges,
        "orphan_i_nodes": orphan_i_nodes,
        "invalid_relation_references": invalid_relation_refs,
        "support_relations": relation_counts.get("support", 0),
        "attack_relations": relation_counts.get("attack", 0),
        "rephrase_relations": relation_counts.get("rephrase", 0),
        "relation_density": len(relations) / possible_directed_relations
        if possible_directed_relations else 0.0,
        "mean_claims_per_evidence": len(claims) / len(evidence) if evidence else 0.0,
        "claims_per_clinical_case": len(claims),
        "documents_represented": len({item.get("document_id") for item in evidence}),
        "evidence_sources_represented": len({item.get("source") for item in evidence}),
        "relation_distribution": json.dumps(dict(relation_counts), sort_keys=True),
    }]

    errors = []
    seen_error_paths = set()
    for candidate in [run / "errors.json", *run.glob("**/errors.json")]:
        resolved = candidate.resolve()
        if candidate.exists() and resolved not in seen_error_paths:
            seen_error_paths.add(resolved)
            value = json.loads(candidate.read_text(encoding="utf-8-sig"))
            errors.extend(value if isinstance(value, list) else [value])
    if manifest.get("error"):
        errors.append(manifest["error"])
    source_hash = _canonical_sha(evidence)
    stage_evidence_hashes = {}
    for candidate in run.glob("*/evidence.json"):
        stage_evidence_hashes[str(candidate.relative_to(run))] = _canonical_sha(
            json.loads(candidate.read_text(encoding="utf-8-sig"))
        )
    provenance_claim_ids = {item.get("claim_id") for item in provenance.get("claims", [])}
    provenance_evidence_ids = {item.get("evidence_id") for item in provenance.get("claims", [])}
    integrity = {
        "original_evidence_sha256": source_hash, "stage_evidence_sha256": stage_evidence_hashes,
        "evidence_immutable_across_stage_copies": all(value == source_hash for value in stage_evidence_hashes.values()),
        "provenance_map_present": bool(provenance),
        "provenance_claim_ids_resolve": provenance_claim_ids == claim_ids,
        "provenance_evidence_ids_resolve": provenance_evidence_ids <= set(evidence_by_id),
        "unique_evidence_ids": len(evidence_by_id) == len(evidence),
        "unique_span_ids": len({item.get('span_id') for item in spans}) == len(spans),
        "unique_claim_ids": len(claim_ids) == len(claims),
        "unique_relation_ids": len({item.get('relation_id') for item in relations}) == len(relations),
        "all_claims_traceable": all(row["evidence_exists"] and row["source_span_exact"] and
                                    row["retrieval_provenance_preserved"] for row in traceability_rows),
        "xaif_structurally_valid": not (graph_rows[0]["duplicate_node_ids"] or orphan_edges or
                                        orphan_i_nodes or invalid_relation_refs),
    }
    module_runs = []
    for candidate in run.glob("**/module_runs.json"):
        value = json.loads(candidate.read_text(encoding="utf-8-sig"))
        if isinstance(value, list):
            module_runs.extend(value)
    durations = []
    for module_run in module_runs:
        try:
            from datetime import datetime
            durations.append((datetime.fromisoformat(module_run["completed_at"]) -
                              datetime.fromisoformat(module_run["started_at"])).total_seconds())
        except (KeyError, TypeError, ValueError):
            continue
    efficiency = {
        "module_call_count": len(module_runs), "timed_module_call_count": len(durations),
        "module_seconds": sum(durations),
        "mean_module_latency_seconds": sum(durations) / len(durations) if durations else None,
        "peak_cpu_memory_bytes": None, "peak_gpu_memory_bytes": None,
        "cpu_utilisation": None, "gpu_utilisation": None,
        "hardware_telemetry_available": False,
        "note": "Resource values remain null unless an external telemetry collector is configured.",
    }
    error_analysis = {
        "evaluation_reference": "unannotated", "accuracy_metrics_permitted": False,
        "errors": errors, "error_count": len(errors),
        "errors_by_class": dict(Counter(error.get("error_class", error.get("class", "unknown"))
                                        for error in errors)),
        "timeouts": sum("timeout" in str(error).casefold() for error in errors),
        "invalid_outputs": sum("invalid" in str(error).casefold() for error in errors),
        "malformed_xaif": sum("xaif" in str(error).casefold() and
                              "invalid" in str(error).casefold() for error in errors),
        "empty_outputs": sum("empty" in str(error).casefold() or
                             "vacío" in str(error).casefold() for error in errors),
    }
    _csv(output / "application_processing_results.csv", processing_rows,
         list(processing_rows[0]) if processing_rows else ["evidence_id"])
    _csv(output / "traceability_results.csv", traceability_rows,
         list(traceability_rows[0]) if traceability_rows else ["claim_id"])
    _csv(output / "graph_statistics.csv", graph_rows, list(graph_rows[0]))
    write_json(output / "error_analysis.json", error_analysis)
    result = {
        "evaluation_reference": "unannotated", "accuracy_metrics_computed": False,
        "run": str(run), "manifest": manifest, "integrity": integrity,
        "efficiency": efficiency,
        "processing_summary": {
            "evidence_count": len(evidence),
            "fully_processed_count": sum(row["segmentation_processed"] and
                                         row["propositionalisation_processed"] for row in processing_rows),
            "fully_processed_percentage": sum(row["segmentation_processed"] and
                                              row["propositionalisation_processed"]
                                              for row in processing_rows) / len(processing_rows)
            if processing_rows else 1.0,
            "traceable_claim_count": sum(row["evidence_exists"] and row["source_span_exact"] and
                                         row["retrieval_provenance_preserved"]
                                         for row in traceability_rows),
            "claim_traceability_rate": sum(row["evidence_exists"] and row["source_span_exact"] and
                                           row["retrieval_provenance_preserved"] for row in traceability_rows)
            / len(traceability_rows) if traceability_rows else 1.0,
        },
        "outputs": {
            "application_processing_results": "application_processing_results.csv",
            "traceability_results": "traceability_results.csv",
            "graph_statistics": "graph_statistics.csv", "error_analysis": "error_analysis.json",
        },
    }
    write_json(output / "manifest.json", result)
    return result
