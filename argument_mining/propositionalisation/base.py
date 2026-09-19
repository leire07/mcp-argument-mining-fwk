from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import ArgumentSpan, Claim, EvidenceRecord, ModuleRun, ModuleSpec


@dataclass(frozen=True)
class PropositionalisationOutput:
    claims: list[Claim]
    xaif_input: dict
    xaif_response: dict
    module_run: ModuleRun


class PropositionalisationModule(ABC):
    """Contract: gold/predicted spans in, provenance-complete I-node claims out."""

    def __init__(self, spec: ModuleSpec, client):
        if spec.stage != "propositionalisation":
            raise ValueError(f"{spec.module_id} no es un proposicionador")
        self.spec = spec
        self.client = client

    @abstractmethod
    def run(self, evidence: EvidenceRecord, spans: list[ArgumentSpan], experiment_id: str,
            input_kind: str) -> PropositionalisationOutput:
        raise NotImplementedError
