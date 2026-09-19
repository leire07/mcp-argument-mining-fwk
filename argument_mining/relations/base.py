from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import ArgumentRelation, Claim, ModuleRun, ModuleSpec


@dataclass(frozen=True)
class RelationIdentificationOutput:
    relations: list[ArgumentRelation]
    xaif_input: dict
    xaif_response: dict
    module_run: ModuleRun


class RelationIdentificationModule(ABC):
    """Contract: one declared claim group in, directed RA/CA/MA relations out."""

    def __init__(self, spec: ModuleSpec, client):
        if spec.stage != "relation_identification":
            raise ValueError(f"{spec.module_id} no es un identificador de relaciones")
        self.spec = spec
        self.client = client

    @abstractmethod
    def run(self, claims: list[Claim], experiment_id: str,
            input_kind: str) -> RelationIdentificationOutput:
        raise NotImplementedError
