"""Diagnóstico breve del endpoint existente: texto, JSON y tool calling."""
import json
import os
import re

from conn import crear_cliente
from .models import RetrievalPlan


def safe_message(exc: Exception) -> str:
    message = str(exc)
    for name in ("OPENAI_API_KEY", "GOOGLE_API_KEY"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", message)[:1500]


def main():
    client = crear_cliente().with_options(timeout=35, max_retries=0)
    model = os.getenv("LLM_MODEL", "gpt-oss-120b").removeprefix("openai/")
    probes = [
        ("text", {"messages": [{"role": "user", "content": "Reply with OK."}]}),
        ("structured_plan", {"messages": [{"role": "user", "content":
            "Return a retrieval plan JSON for a synthetic kidney disease question. Use guideline_agent and literature_agent tasks."}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "RetrievalPlan", "schema": RetrievalPlan.model_json_schema()}}}),
        ("tools", {"messages": [{"role": "user", "content": "Call the echo tool with text OK."}],
            "tools": [{"type": "function", "function": {"name": "echo", "description": "Echo input text",
                "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}]}),
    ]
    for name, kwargs in probes:
        try:
            result = client.chat.completions.create(model=model, **kwargs)
            message = result.choices[0].message
            print(json.dumps({"probe": name, "status": "ok", "text": message.content,
                              "tool_calls": [call.function.name for call in message.tool_calls or []]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({"probe": name, "status": "error", "type": type(exc).__name__,
                              "message": safe_message(exc)}, ensure_ascii=False), flush=True)
    client.close()


if __name__ == "__main__":
    main()
