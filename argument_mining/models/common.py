from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


StageName = Literal["segmentation", "propositionalisation", "relation_identification", "xaif_export"]
BackendType = Literal["ws", "repo"]
EndpointStatus = Literal["operational", "unavailable", "not_deployed", "unknown"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModuleSpec(StrictModel):
    module_id: str
    stage: StageName
    endpoint: str
    backend_type: BackendType = "ws"
    backend_id: str = "public_ws"
    route: str | None = None
    endpoint_status: EndpointStatus = "unknown"
    endpoint_checked_at: str | None = None
    version: str = "public-service-unreported"
    model: str | None = None
    model_revision: str | None = None
    repository: str | None = None
    repository_commit: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ModuleRun(StrictModel):
    experiment_id: str
    stage: str
    module_id: str
    module_version: str
    model: str | None
    model_revision: str | None = None
    endpoint: str
    backend_type: BackendType = "ws"
    backend_id: str = "public_ws"
    route: str | None = None
    repository: str | None = None
    repository_commit: str | None = None
    config: dict[str, Any]
    input_sha256: str
    response_sha256: str
    started_at: str
    completed_at: str
    attempts: int = Field(default=1, ge=1)
