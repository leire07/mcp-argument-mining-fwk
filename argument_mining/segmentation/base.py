from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import ArgumentSpan, EvidenceRecord, ModuleRun, ModuleSpec


@dataclass(frozen=True)
class SegmentationOutput:
    spans: list[ArgumentSpan]
    xaif_input: dict
    xaif_response: dict
    module_run: ModuleRun


class SegmentationModule(ABC):
    """Contract: one immutable evidence record in, traceable L-node spans out."""

    def __init__(self, spec: ModuleSpec, client):
        if spec.stage != "segmentation":
            raise ValueError(f"{spec.module_id} no es un segmentador")
        self.spec = spec
        self.client = client

    @abstractmethod
    def run(self, evidence: EvidenceRecord, experiment_id: str) -> SegmentationOutput:
        raise NotImplementedError
