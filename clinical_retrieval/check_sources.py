"""Prueba las fuentes reales a través de MCP, sin utilizar un LLM."""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ROOT, Settings
from .evidence import unpack_mcp_response


async def check(output: Path, query: str, timeout: int):
    output.mkdir(parents=True, exist_ok=False)
    results = []
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "clinical_retrieval.mcp_server", "--output", str(output), "--timeout", str(timeout)],
        cwd=str(ROOT), env={"PYTHONUTF8": "1"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_list = await session.list_tools()
            print("MCP tools: " + ", ".join(tool.name for tool in tool_list.tools), flush=True)
            for name, source in [("search_guidelines", "pubmed"), ("search_literature", "europe_pmc")]:
                result = await session.call_tool(name, {"query": query, "source": source, "limit": 3})
                payload = unpack_mcp_response(result)
                results.append({"tool": name, "source": source, "response": payload})
                print(f"{name}/{source}: {len(payload.get('passages', []))} fragmentos; error={payload.get('error')}", flush=True)
    (output / "source_check.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Comprobación de fuentes por MCP", "", f"Consulta: {query}", "",
             "Recuperación real sin LLM. Estos fragmentos todavía no tienen valoración de relevancia.", ""]
    for result in results:
        lines.extend([f"## {result['tool']} / {result['source']}", ""])
        if result["response"].get("error"):
            lines.extend([f"Error: {result['response']['error']}", ""])
        for item in result["response"].get("passages", []):
            lines.extend([f"### {item['title']}", "", f"[{item['document_id']}]({item['url']}) · {item['content_type']}",
                          "", "> " + item["passage_text"].replace("\n", "\n> "), ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Resultados: {output}")
    return all(not item["response"].get("error") and item["response"].get("passages") for item in results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="SGLT2 chronic kidney disease")
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    settings = Settings.from_env()
    name = "sources_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    ok = asyncio.run(check((args.output / name).resolve(), args.query, settings.http_timeout))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
