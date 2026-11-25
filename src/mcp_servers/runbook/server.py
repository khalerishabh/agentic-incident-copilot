import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from copilot.config import settings
from copilot.telemetry import setup_logging

from ..common.server import health_payload, tool_errors
from .factory import build_search
from .store import PgVectorSearch
from .tools import RunbookTools

cfg = settings.integrations.runbooks
search = build_search(settings)
tools = RunbookTools(search, cfg)


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    if isinstance(search, PgVectorSearch):
        await search.open()
    try:
        yield
    finally:
        await search.aclose()


mcp = FastMCP("runbook", lifespan=lifespan)


@mcp.tool
@tool_errors
async def search_runbooks(query: str, k: int = 3) -> dict[str, Any]:
    """Find runbook sections relevant to a symptom, error message or alert, best first.
    Matches both meaning and exact words, so paste error text as-is."""
    return await tools.search_runbooks(query, k)


@mcp.tool
@tool_errors
async def list_runbooks() -> list[dict[str, str]]:
    """Names and titles of all runbooks."""
    return await tools.list_runbooks()


@mcp.tool
@tool_errors
async def get_runbook(name: str) -> dict[str, Any]:
    """Full text of one runbook by name, as listed by list_runbooks."""
    return await tools.get_runbook(name)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/readyz", methods=["GET"])
async def readyz(_: Request) -> JSONResponse:
    try:
        stats = await search.stats()
        if not stats.get("chunks"):
            raise RuntimeError("runbook index is empty; run python -m mcp_servers.runbook.index")
    except Exception as exc:
        return JSONResponse(health_payload("runbook", search.name, exc), status_code=503)
    return JSONResponse({**health_payload("runbook", search.name, None), **stats})


if __name__ == "__main__":
    setup_logging()
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "9104")))
