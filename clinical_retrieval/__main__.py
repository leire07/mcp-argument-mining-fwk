from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import time
from dataclasses import asdict
from pathlib import Path

from .config import Settings
from .evidence import EvidenceStore
from .models import ClinicalCase


def case_output_path(base: Path, case_id: str) -> Path:
    """Choose an unused case directory without interpreting the ID as a path."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", case_id).strip("_") or "case"
    if name.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"(?:COM|LPT)[1-9]", name, re.IGNORECASE
    ):
        name = "case_" + name
    base = base.resolve()
    output = base / name
    suffix = 2
    while output.exists() or output.is_symlink():
        output = base / f"{name}_{suffix}"
        suffix += 1
    return output


async def run_case(case: ClinicalCase, output: Path, settings: Settings) -> str:
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from .agents import build_workflow

    output.mkdir(parents=True, exist_ok=False)
    store = EvidenceStore(output)
    store.write_json("input.json", case.model_dump())
    store.write_json("config.json", asdict(settings))
    started = time.monotonic()
    toolsets = []
    status = "failed"
    try:
        workflow, toolsets = build_workflow(settings, store)
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="clinical_retrieval", user_id="local",
                                                state={"case_input": case.model_dump_json()})
        runner = Runner(agent=workflow, app_name="clinical_retrieval", session_service=sessions)
        message = types.Content(role="user", parts=[types.Part(text="Recupera evidencia para el caso de la sesión.")])
        async for event in runner.run_async(user_id="local", session_id=session.id,
                                            new_message=message,
                                            run_config=RunConfig(max_llm_calls=settings.max_llm_calls)):
            data = event.model_dump(mode="json", exclude_none=True)
            store.log("events.jsonl", data)
            if event.usage_metadata:
                for key, value in event.usage_metadata.model_dump(exclude_none=True).items():
                    if isinstance(value, int):
                        store.usage[key] = store.usage.get(key, 0) + value
            if event.error_code:
                store.error(event.author, f"Error del modelo: {event.error_code}")
            if event.is_final_response():
                print(f"[{event.author}] finalizado", flush=True)
        status = "partial" if store.errors else "completed"
    except Exception as exc:
        for name, agent_status in store.agent_status.items():
            if agent_status == "running":
                store.agent_status[name] = "failed"
        store.error("pipeline", f"{type(exc).__name__}: no se completó el flujo. Comprueba .env, red/VPN de UPV y soporte de tool calling/JSON del modelo.")
        status = "partial" if store.items else "failed"
    finally:
        for toolset in reversed(toolsets):
            try:
                await toolset.close()
            except Exception as exc:
                store.error("mcp_cleanup", type(exc).__name__)
                if status == "completed":
                    status = "partial"
        store.export(settings.top_k, dict(case_id=case.case_id, status=status,
                                         elapsed_seconds=round(time.monotonic() - started, 3)))
    print(f"Estado: {status}. Evidencia: {len(store.selected(settings.top_k))}. Archivos: {output}", flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description="Recuperación clínica con Google ADK + MCP")
    parser.add_argument("--case", type=Path, required=True, help="JSON con case_id, clinical_case, question y options")
    parser.add_argument("--output", type=Path, default=Path("outputs"), help="Directorio base de ejecuciones")
    args = parser.parse_args()
    os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    logging.basicConfig(level=logging.WARNING)
    try:
        settings = Settings.from_env()
        case = ClinicalCase.model_validate_json(args.case.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    output = case_output_path(args.output, case.case_id)
    status = asyncio.run(run_case(case, output, settings))
    raise SystemExit(0 if status == "completed" else 2)


if __name__ == "__main__":
    main()
