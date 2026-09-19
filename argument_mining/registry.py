from __future__ import annotations

from pathlib import Path

from .errors import SerializationError
from .experiments.config import load_mapping
from .models import ModuleSpec


class ModuleRegistry:
    def __init__(self, path: Path):
        data = load_mapping(path)
        try:
            specs = [ModuleSpec.model_validate(item) for item in data["modules"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SerializationError(f"Registro de módulos inválido en {path}: {exc}") from exc
        self.modules = {item.module_id.upper(): item for item in specs}

    def get(self, module_id: str, stage: str) -> ModuleSpec:
        try:
            spec = self.modules[module_id.upper()]
        except KeyError as exc:
            raise ValueError(f"Módulo no registrado: {module_id}") from exc
        if spec.stage != stage:
            raise ValueError(f"{module_id} pertenece a {spec.stage}, no a {stage}")
        return spec.model_copy(deep=True)

    def choices(self, stage: str) -> list[str]:
        return sorted(spec.module_id for spec in self.modules.values() if spec.stage == stage)

    def specs(self, stage: str) -> list[ModuleSpec]:
        return sorted(
            (spec.model_copy(deep=True) for spec in self.modules.values() if spec.stage == stage),
            key=lambda spec: spec.module_id,
        )

    def all_specs(self) -> list[ModuleSpec]:
        return [spec.model_copy(deep=True) for spec in self.modules.values()]
