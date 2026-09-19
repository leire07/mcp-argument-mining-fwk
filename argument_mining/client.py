from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from .errors import PropositionError, RelationError, SegmentationError, SerializationError
from .models import ModuleRun, ModuleSpec, utc_now


def canonical_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class OAMFClient:
    """Thin client for oAMF's multipart xAIF web-service contract."""

    def __init__(self, timeout: float = 120, max_attempts: int = 3):
        self.timeout = timeout
        self.max_attempts = max_attempts

    def invoke(self, spec: ModuleSpec, xaif: dict, experiment_id: str) -> tuple[dict, ModuleRun]:
        body = canonical_bytes(xaif)
        started = utc_now()
        error_class = {"segmentation": SegmentationError, "propositionalisation": PropositionError,
                       "relation_identification": RelationError}.get(spec.stage, SerializationError)
        attempts = 0
        for attempts in range(1, self.max_attempts + 1):
            try:
                response = httpx.post(
                    spec.endpoint,
                    files={"file": ("input.json", body, "application/json")},
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                response.raise_for_status()
                result = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                retryable = isinstance(exc, httpx.RequestError) or (
                    isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
                )
                if not retryable or attempts == self.max_attempts:
                    detail = str(exc)
                    if isinstance(exc, httpx.HTTPStatusError):
                        response_text = " ".join(exc.response.text.split())[:500]
                        if response_text:
                            detail = f"{detail}; respuesta del servicio: {response_text}"
                    raise error_class(
                        f"{spec.module_id} falló en {spec.endpoint} tras {attempts} intento(s): {detail}"
                    ) from exc
                time.sleep(attempts)
        completed = utc_now()
        run = ModuleRun(
            experiment_id=experiment_id,
            stage=spec.stage,
            module_id=spec.module_id,
            module_version=spec.version,
            model=spec.model,
            model_revision=spec.model_revision,
            endpoint=spec.endpoint,
            backend_type=spec.backend_type,
            backend_id=spec.backend_id,
            route=spec.route,
            repository=spec.repository,
            repository_commit=spec.repository_commit,
            config=spec.config,
            input_sha256=hashlib.sha256(body).hexdigest(),
            response_sha256=hashlib.sha256(canonical_bytes(result)).hexdigest(),
            started_at=started,
            completed_at=completed,
            attempts=attempts,
        )
        return result, run
