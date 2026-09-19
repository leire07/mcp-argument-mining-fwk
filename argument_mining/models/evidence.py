from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRecord(BaseModel):
    """Validated view that preserves every upstream field."""

    model_config = ConfigDict(extra="allow")
    evidence_id: str = Field(min_length=1)
    passage_text: str = Field(min_length=1)
    document_id: str = ""
    title: str = ""
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    assessments: list[dict[str, Any]] = Field(default_factory=list)
