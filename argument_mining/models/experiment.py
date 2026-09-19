from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import ModuleSpec, StrictModel, utc_now
from .relation import PairGeneration


class StageSelection(StrictModel):
    module: str
    endpoint: str | None = None
    backend_type: Literal["ws", "repo"] | None = None
    backend_id: str | None = None
    route: str | None = None
    repository: str | None = None
    repository_commit: str | None = None
    version: str | None = None
    model: str | None = None
    model_revision: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class EndToEndConfig(StrictModel):
    experiment_id: str
    dataset_version: str = "unreported"
    gold_version: str | None = None
    random_seed: int = 42
    segmentation: StageSelection
    propositionalisation: StageSelection
    relation_identification: StageSelection
    pair_generation: PairGeneration = Field(default_factory=PairGeneration)


class FrozenOAMFConfiguration(StrictModel):
    schema_version: str = "1.0"
    status: Literal["not_frozen", "frozen"]
    selected_at: str | None = None
    selection_report: str | None = None
    dataset_used_for_selection: str
    application_data_used_for_tuning: bool = False
    random_seed: int = 42
    segmentation: StageSelection | None = None
    propositionalisation: StageSelection | None = None
    relation_identification: StageSelection | None = None
    freeze_requirements: list[str] = Field(default_factory=list)


class ExperimentManifest(StrictModel):
    schema_version: str = "1.0"
    experiment_id: str
    run_kind: Literal["segmentation", "propositionalisation", "relation_identification",
                      "xaif_export", "end_to_end"]
    dataset_version: str = "unreported"
    dataset_name: str | None = None
    dataset_split: str | None = None
    evaluation_reference: Literal["gold", "silver", "unannotated"] = "unannotated"
    gold_version: str | None = None
    random_seed: int = 42
    timestamp: str = Field(default_factory=utc_now)
    input_kind: dict[str, str] = Field(default_factory=dict)
    modules: dict[str, ModuleSpec | None] = Field(default_factory=dict)
    pair_generation: PairGeneration | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    status: Literal["running", "completed", "failed"] = "running"
    error: dict[str, Any] | None = None
    hardware: dict[str, Any] = Field(default_factory=dict)
    container: dict[str, Any] = Field(default_factory=dict)
    execution_seconds: float | None = None
