"""Servidor de pruebas: MCP real y HTTP simulado, sin red ni claves."""
import sys
from pathlib import Path

import httpx

from clinical_retrieval.mcp_server import create_server
from tests.fixtures import mock_response

if __name__ == "__main__":
    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_response))
    create_server(Path(sys.argv[1]), client=client).run(transport="stdio")
