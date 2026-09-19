from typing import Any, Literal

from pydantic import Field, model_validator

from .common import ModuleRun, StrictModel


class ArgumentRelation(StrictModel):
    relation_id: str
    source_claim_id: str
    target_claim_id: str
    relation: Literal["support", "attack", "rephrase", "none"]
    xaif_relation_type: Literal["RA", "CA", "MA"] | None
    input_kind: Literal["gold", "silver", "predicted"] = "predicted"
    endpoint_kind: Literal["claim", "argument_unit"] = "claim"
    original_id: str | None = None
    original_label: str | None = None
    label_mapping: dict[str, Any] | None = None
    dataset_metadata: dict[str, Any] = Field(default_factory=dict)
    generated_by: ModuleRun | None = None
    confidence: float | None = None

    @model_validator(mode="after")
    def relation_matches_xaif(self):
        expected = {"support": "RA", "attack": "CA", "rephrase": "MA", "none": None}
        if self.xaif_relation_type != expected[self.relation]:
            raise ValueError(f"{self.relation} requiere xaif_relation_type={expected[self.relation]}")
        return self


class PairGeneration(StrictModel):
    strategy: Literal["within_passage", "within_document", "all"] = "within_passage"
    thresholds: dict[str, Any] = Field(default_factory=dict)
    version: str = "1"
