from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from conn import cargar_env


ROOT = Path(__file__).resolve().parents[1]


def positive_env(name: str, default: int, ceiling: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= ceiling:
        raise ValueError(f"{name} debe estar entre 1 y {ceiling}")
    return value


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-oss-120b"
    llm_timeout: int = 120
    max_llm_calls: int = 24
    max_search_calls: int = 4
    max_fetch_calls: int = 2
    results_per_search: int = 5
    top_k: int = 10
    http_timeout: int = 30

    @classmethod
    def from_env(cls) -> Settings:
        if (ROOT / ".env").exists():
            cargar_env()
        return cls(
            model=os.getenv("LLM_MODEL", "gpt-oss-120b"),
            llm_timeout=positive_env("LLM_TIMEOUT", 120, 600),
            max_llm_calls=positive_env("MAX_LLM_CALLS", 24, 100),
            max_search_calls=positive_env("MAX_SEARCH_CALLS_PER_AGENT", 4, 10),
            max_fetch_calls=positive_env("MAX_FETCH_CALLS_PER_AGENT", 2, 10),
            results_per_search=positive_env("RESULTS_PER_SEARCH", 5, 10),
            top_k=positive_env("TOP_K", 10, 100),
            http_timeout=positive_env("HTTP_TIMEOUT", 30, 120),
        )
