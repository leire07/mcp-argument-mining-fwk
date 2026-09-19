from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .common import ModuleRun, StrictModel


class SourceSpan(StrictModel):
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_char <= self.start_char:
            raise ValueError("end_char debe ser mayor que start_char")
        return self


class ArgumentSpan(StrictModel):
    span_id: str
    evidence_id: str
    source_span: SourceSpan
    l_node_id: str
    input_kind: Literal["gold", "silver", "predicted"] = "predicted"
    generated_by: ModuleRun | None = None
    original_id: str | None = None
    component_type: Literal["premise", "claim", "major_claim"] | None = None
    dataset_metadata: dict[str, Any] = Field(default_factory=dict)


class ArgumentUnit(StrictModel):
    """Extractive benchmark component; it is deliberately not a normalised Claim."""

    unit_id: str
    original_id: str
    evidence_id: str
    span_id: str
    l_node_id: str
    i_node_id: str
    component_type: Literal["premise", "claim", "major_claim"]
    source_span: SourceSpan
    evaluation_reference: Literal["gold", "silver"]
    dataset_metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimSource(StrictModel):
    evidence_id: str
    passage_text: str
    source_span: SourceSpan
    document: dict[str, Any]
    retrieval_provenance: list[dict[str, Any]]
    upstream_assessments: list[dict[str, Any]]


class Claim(StrictModel):
    claim_id: str
    evidence_id: str
    span_id: str
    l_node_id: str
    i_node_id: str
    proposition_text: str = Field(min_length=1)
    source: ClaimSource
    input_kind: Literal["gold", "silver", "predicted"] = "predicted"
    generated_by: ModuleRun | None = None
    confidence: float | None = None
    quality_flags: list[str] = Field(default_factory=list)
