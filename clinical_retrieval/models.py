from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClinicalCase(BaseModel):
    # Rechazar campos extra evita introducir respuestas/anotaciones gold por accidente.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: str = Field(min_length=1, max_length=100)
    clinical_case: str = Field(min_length=1, max_length=20000)
    question: str = Field(min_length=1, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=20)


class SearchTask(BaseModel):
    agent: Literal["guideline_agent", "literature_agent"]
    objective: str = Field(min_length=1)
    queries: list[str] = Field(min_length=1, max_length=4)


class RetrievalPlan(BaseModel):
    clinical_aspects: list[str] = Field(min_length=1)
    rationale: str
    tasks: list[SearchTask] = Field(min_length=1, max_length=2)


class Passage(BaseModel):
    evidence_id: str
    document_id: str
    title: str
    passage_text: str = Field(min_length=1)
    source: Literal["pubmed", "europe_pmc"]
    source_type: Literal["guideline", "literature"]
    url: str
    content_type: Literal["abstract", "full_text"]
    section: str
    publication_year: str = ""
    publication_types: list[str] = Field(default_factory=list)
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    retrieval_query: str
    retrieved_at: str
    source_rank: int
    raw_file: str


class Provenance(BaseModel):
    retrieved_by: str
    tool: str
    retrieval_query: str
    source: str
    url: str
    retrieved_at: str
    source_rank: int
    raw_file: str


class Assessment(BaseModel):
    agent: str
    relevance_score: int = Field(ge=0, le=3)
    reason: str


class EvidenceItem(Passage):
    provenance: list[Provenance] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)


def evidence_id(document_id: str, text: str) -> str:
    # Sólo normalizar espacios para identificar duplicados; conservar el texto original.
    canonical = re.sub(r"\s+", " ", text).strip()
    digest = hashlib.sha256(f"{document_id}\n{canonical}".encode()).hexdigest()[:24]
    return f"ev_{digest}"
