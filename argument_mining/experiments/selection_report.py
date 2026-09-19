from __future__ import annotations

import csv
import json
from pathlib import Path

from ..pipeline import write_json


def _json(path: Path | None) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path and path.exists() else None


def _csv(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_selection_report(output: Path, availability: Path,
                           segmentation_results: Path | None = None,
                           relation_results: Path | None = None,
                           propositionalisation: Path | None = None) -> dict:
    """Aggregate decision evidence while deliberately leaving selection manual."""
    availability_rows = _csv(availability)
    segmentation = _json(segmentation_results)
    relations = _json(relation_results)
    propositions = _json(propositionalisation)
    report = {
        "report_kind": "multi_criteria_module_selection_evidence",
        "automatic_selection": False, "selected_configuration": None,
        "selection_must_be_frozen_manually": True,
        "criteria": [
            "gold benchmark performance where semantically valid",
            "endpoint and repository availability", "reproducibility and version pinning",
            "xAIF compatibility", "source/provenance preservation",
            "compute requirements", "failure rate and failure modes",
        ],
        "segmentation": segmentation,
        "propositionalisation": propositions,
        "relation_identification": relations,
        "module_availability": availability_rows,
        "decision_constraints": {
            "no_cartesian_grid": True, "no_application_data_tuning": True,
            "no_normalised_gold_claims_fabricated": True,
            "failed_items_remain_in_denominator": True,
        },
        "next_step": "Review this evidence and edit configs/selected_oamf_configuration.yaml manually.",
    }
    write_json(output, report)
    return report
