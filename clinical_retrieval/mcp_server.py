"""Servidor MCP por stdio. stdout queda reservado al protocolo MCP."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .models import Passage
from .sources import SourceClient


def create_server(output: Path, timeout: int = 30, client: httpx.AsyncClient | None = None) -> FastMCP:
    source_client = SourceClient(output, timeout, client=client)
    documents: dict[str, Passage] = {}

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            await source_client.close()

    server = FastMCP("clinical-evidence", lifespan=lifespan)

    async def search(query, source, kind, limit):
        try:
            result = await source_client.search(query, source, kind, limit)
            for item in result["passages"]:
                passage = Passage.model_validate(item)
                documents[passage.document_id] = passage
            return result
        except (httpx.HTTPError, ValueError) as exc:
            return {"passages": [], "error": str(exc), "source": source, "query": query}

    @server.tool()
    async def search_guidelines(query: str, source: Literal["pubmed", "europe_pmc"] = "pubmed", limit: int = 5) -> dict:
        """Busca guías indexadas por tipo de publicación. Devuelve resúmenes originales, no recomendaciones generadas.

        Args:
            query: Consulta bibliográfica, preferiblemente en inglés. Sintaxis de la fuente elegida.
            source: pubmed o europe_pmc. No es acceso directo a NICE ni WHO.
            limit: Número máximo de documentos (1 a 10).
        """
        return await search(query, source, "guideline", limit)

    @server.tool()
    async def search_literature(query: str, source: Literal["pubmed", "europe_pmc"] = "europe_pmc", limit: int = 5) -> dict:
        """Busca artículos y recupera fragmentos de sus resúmenes.

        Args:
            query: Consulta bibliográfica, preferiblemente en inglés. Sintaxis de la fuente elegida.
            source: pubmed o europe_pmc.
            limit: Número máximo de documentos (1 a 10).
        """
        return await search(query, source, "literature", limit)

    @server.tool()
    async def fetch_full_text(document_id: str, query: str) -> dict:
        """Obtiene fragmentos del texto completo abierto en Europe PMC de un documento ya recuperado.

        Args:
            document_id: Identificador devuelto por una búsqueda de este agente, por ejemplo PMID:12345.
            query: Términos en inglés para priorizar párrafos por coincidencia léxica.
        """
        if document_id not in documents:
            return {"passages": [], "error": "Busca primero el documento con las herramientas de este agente"}
        if not query.strip() or len(query) > 1000:
            return {"passages": [], "error": "La consulta debe tener entre 1 y 1000 caracteres"}
        try:
            return await source_client.full_text(documents[document_id], query)
        except (httpx.HTTPError, ValueError) as exc:
            return {"passages": [], "error": str(exc), "document_id": document_id}

    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    create_server(args.output, args.timeout).run(transport="stdio")


if __name__ == "__main__":
    main()
