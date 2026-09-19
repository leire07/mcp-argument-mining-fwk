from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..errors import SerializationError
from ..models import EndToEndConfig, FrozenOAMFConfiguration


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        value = yaml.safe_load(text) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SerializationError(f"No se puede leer la configuración {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SerializationError(f"La configuración {path} debe ser un objeto")
    return value


def load_end_to_end_config(path: Path) -> EndToEndConfig:
    try:
        return EndToEndConfig.model_validate(load_mapping(path))
    except ValidationError as exc:
        raise SerializationError(f"Configuración experimental inválida en {path}: {exc}") from exc


def load_frozen_config(path: Path) -> FrozenOAMFConfiguration:
    try:
        config = FrozenOAMFConfiguration.model_validate(load_mapping(path))
    except ValidationError as exc:
        raise SerializationError(f"Configuración oAMF congelada inválida en {path}: {exc}") from exc
    if config.status != "frozen":
        raise SerializationError(f"La configuración {path} todavía tiene status={config.status}")
    if config.application_data_used_for_tuning:
        raise SerializationError("La configuración declara ajuste sobre datos de aplicación")
    if not all((config.segmentation, config.propositionalisation, config.relation_identification)):
        raise SerializationError("La configuración congelada debe fijar los tres módulos")
    return config
