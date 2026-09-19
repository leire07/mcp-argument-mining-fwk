from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..errors import SerializationError
from ..models import ArgumentRelation, ArgumentSpan, ArgumentUnit, EvidenceRecord, SourceSpan
from ..pipeline import write_json


ABSTRCT_REPOSITORY = "https://gitlab.com/tomaye/abstrct"
ABSTRCT_COMMIT = "f856f1ca7514caa4094194b5623e84c159d9bf1d"
ABSTRCT_LICENSE = "CC BY-NC-SA 4.0"


@dataclass(frozen=True)
class AbstRCTAdaptation:
    evidence: list[EvidenceRecord]
    spans: list[ArgumentSpan]
    units: list[ArgumentUnit]
    relations: list[ArgumentRelation]
    unmapped_relations: list[dict]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(prefix: str, *parts: str) -> str:
    value = "\n".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(value).hexdigest()[:24]}"


def _component_type(label: str) -> str:
    mapping = {"Premise": "premise", "Claim": "claim", "MajorClaim": "major_claim"}
    try:
        return mapping[label]
    except KeyError as exc:
        raise SerializationError(f"Tipo de componente AbstRCT no soportado: {label}") from exc


class AbstRCTAdapter:
    """Lossless BRAT-to-contract adapter for the official AbstRCT corpus."""

    def __init__(self, corpus_root: Path, version: str = ABSTRCT_COMMIT):
        self.corpus_root = corpus_root
        self.version = version

    def adapt(self, split: str, subset: str | None = None,
              max_documents: int | None = None) -> AbstRCTAdaptation:
        split_root = self.corpus_root / split
        if not split_root.is_dir():
            raise SerializationError(f"Split AbstRCT inexistente: {split_root}")
        roots = [split_root / subset] if subset else sorted(p for p in split_root.iterdir() if p.is_dir())
        missing = [str(path) for path in roots if not path.is_dir()]
        if missing:
            raise SerializationError(f"Subset AbstRCT inexistente: {', '.join(missing)}")
        text_paths = sorted(path for root in roots for path in root.glob("*.txt"))
        if max_documents is not None:
            text_paths = text_paths[:max_documents]
        if not text_paths:
            raise SerializationError("No se encontraron documentos .txt de AbstRCT")

        evidence, spans, units, relations, unmapped = [], [], [], [], []
        for text_path in text_paths:
            ann_path = text_path.with_suffix(".ann")
            if not ann_path.exists():
                raise SerializationError(f"Falta la anotación BRAT: {ann_path}")
            subset_name = text_path.parent.name
            document_id = text_path.stem
            evidence_id = f"abstrct:{split}:{subset_name}:{document_id}"
            passage = text_path.read_text(encoding="utf-8")
            metadata = {
                "dataset_name": "AbstRCT", "dataset_version": self.version,
                "dataset_split": split, "dataset_subset": subset_name,
                "original_document_id": document_id,
            }
            record = EvidenceRecord(
                evidence_id=evidence_id, passage_text=passage,
                document_id=f"PMID:{document_id}", title="", source="abstrct",
                source_type="benchmark", pmid=document_id, evaluation_reference="gold",
                **metadata,
                provenance=[{
                    "adapter": "argument_mining.datasets.abstrct.AbstRCTAdapter",
                    "repository": ABSTRCT_REPOSITORY, "repository_commit": self.version,
                    "license": ABSTRCT_LICENSE, "text_file": str(text_path),
                    "annotation_file": str(ann_path), "text_sha256": _sha256(text_path),
                    "annotation_sha256": _sha256(ann_path),
                }],
            )
            evidence.append(record)
            component_by_original: dict[str, ArgumentUnit] = {}
            relation_rows = []
            for line_number, raw_line in enumerate(ann_path.read_text(encoding="utf-8").splitlines(), 1):
                line = raw_line.rstrip("\r")
                if not line:
                    continue
                fields = line.split("\t")
                if line.startswith("T"):
                    if len(fields) < 3:
                        raise SerializationError(f"Anotación BRAT inválida en {ann_path}:{line_number}")
                    original_id, definition, annotated_text = fields[0], fields[1], fields[2]
                    definition_parts = definition.split()
                    if len(definition_parts) != 3 or ";" in definition:
                        raise SerializationError(
                            f"Span BRAT discontinuo o inválido no soportado en {ann_path}:{line_number}"
                        )
                    label, start_text, end_text = definition_parts
                    start, end = int(start_text), int(end_text)
                    exact = passage[start:end]
                    if exact != annotated_text:
                        raise SerializationError(
                            f"Offsets BRAT no coinciden en {ann_path}:{line_number}: {original_id}"
                        )
                    span_id = f"{evidence_id}:{original_id}"
                    component = _component_type(label)
                    source_span = SourceSpan(start_char=start, end_char=end, text=exact)
                    span = ArgumentSpan(
                        span_id=span_id, evidence_id=evidence_id, source_span=source_span,
                        l_node_id=original_id, input_kind="gold", original_id=original_id,
                        component_type=component, dataset_metadata=metadata,
                    )
                    unit = ArgumentUnit(
                        unit_id=span_id, original_id=original_id, evidence_id=evidence_id,
                        span_id=span_id, l_node_id=original_id, i_node_id=original_id,
                        component_type=component, source_span=source_span,
                        evaluation_reference="gold", dataset_metadata=metadata,
                    )
                    spans.append(span)
                    units.append(unit)
                    component_by_original[original_id] = unit
                elif line.startswith("R"):
                    relation_rows.append((line_number, fields))

            for line_number, fields in relation_rows:
                if len(fields) < 2:
                    raise SerializationError(f"Relación BRAT inválida en {ann_path}:{line_number}")
                original_id, definition = fields[0], fields[1].split()
                if len(definition) != 3:
                    raise SerializationError(f"Relación BRAT inválida en {ann_path}:{line_number}")
                original_label, arg1, arg2 = definition
                source_original, target_original = arg1.removeprefix("Arg1:"), arg2.removeprefix("Arg2:")
                if source_original not in component_by_original or target_original not in component_by_original:
                    raise SerializationError(f"Extremo BRAT inexistente en {ann_path}:{line_number}")
                base = {
                    "original_id": original_id, "original_label": original_label,
                    "source_original_id": source_original, "target_original_id": target_original,
                    "evidence_id": evidence_id, **metadata,
                }
                if original_label not in {"Support", "Attack"}:
                    unmapped.append({**base, "reason": "label_not_in_binary_support_attack_task"})
                    continue
                relation = original_label.lower()
                xaif_type = "RA" if relation == "support" else "CA"
                relations.append(ArgumentRelation(
                    relation_id=f"{evidence_id}:{original_id}",
                    source_claim_id=component_by_original[source_original].unit_id,
                    target_claim_id=component_by_original[target_original].unit_id,
                    relation=relation, xaif_relation_type=xaif_type, input_kind="gold",
                    endpoint_kind="argument_unit", original_id=original_id,
                    original_label=original_label,
                    label_mapping={original_label: relation, "justification": "AbstRCT label semantics"},
                    dataset_metadata=metadata,
                ))
        return AbstRCTAdaptation(evidence, spans, units, relations, unmapped)

    def export(self, output: Path, split: str, subset: str | None = None,
               max_documents: int | None = None, copy_raw: bool = True) -> dict:
        if output.exists():
            raise SerializationError(f"La salida ya existe: {output}")
        result = self.adapt(split, subset, max_documents)
        output.mkdir(parents=True)
        write_json(output / "evidence.json", result.evidence)
        write_json(output / "gold_spans.json", result.spans)
        write_json(output / "argument_units.json", result.units)
        write_json(output / "gold_relations.json", result.relations)
        write_json(output / "unmapped_relations.json", result.unmapped_relations)
        source_files = []
        for evidence in result.evidence:
            provenance = evidence.provenance[0]
            for kind, key in (("text", "text_file"), ("annotation", "annotation_file")):
                source = Path(provenance[key])
                destination = None
                if copy_raw:
                    destination = output / "raw" / evidence.dataset_split / evidence.dataset_subset / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                source_files.append({
                    "kind": kind, "source": str(source),
                    "copied_to": str(destination.relative_to(output)) if destination else None,
                    "sha256": _sha256(source),
                })
        mapping = {
            "dataset": "AbstRCT", "repository": ABSTRCT_REPOSITORY,
            "repository_commit": self.version, "license": ABSTRCT_LICENSE,
            "component_mapping": {
                "Premise": "argument_unit.component_type=premise",
                "Claim": "argument_unit.component_type=claim",
                "MajorClaim": "argument_unit.component_type=major_claim",
            },
            "relation_mapping": {"Support": "support/RA", "Attack": "attack/CA"},
            "unmapped_labels": {"Partial-Attack": "excluded_from_binary_support_attack_task"},
            "normalised_gold_claims_created": False,
            "note": "argument_units are extractive benchmark endpoints, not gold normalised propositions",
        }
        write_json(output / "mapping.json", mapping)
        write_json(output / "raw_input_manifest.json", source_files)
        manifest = {
            "experiment_id": f"abstrct_adapter_{split}_{subset or 'all'}",
            "run_kind": "dataset_adapter", "evaluation_reference": "gold",
            "dataset_name": "AbstRCT", "dataset_version": self.version,
            "dataset_split": split, "dataset_subset": subset,
            "repository": ABSTRCT_REPOSITORY, "repository_commit": self.version,
            "copy_raw": copy_raw, "max_documents": max_documents,
            "counts": {
                "evidence": len(result.evidence), "spans": len(result.spans),
                "argument_units": len(result.units), "relations": len(result.relations),
                "unmapped_relations": len(result.unmapped_relations),
                "components_by_type": dict(Counter(item.component_type for item in result.units)),
                "relations_by_label": dict(Counter(item.relation for item in result.relations)),
            },
            "outputs": {
                "evidence": "evidence.json", "gold_spans": "gold_spans.json",
                "argument_units": "argument_units.json", "gold_relations": "gold_relations.json",
                "unmapped_relations": "unmapped_relations.json", "mapping": "mapping.json",
                "raw_input_manifest": "raw_input_manifest.json", "raw": "raw/" if copy_raw else None,
            },
        }
        write_json(output / "manifest.json", manifest)
        return manifest
