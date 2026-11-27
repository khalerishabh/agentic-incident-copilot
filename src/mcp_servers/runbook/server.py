import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from copilot.config import settings

from ..common.errors import IntegrationError
from ..common.runtime import serve
from ..common.server import health_payload, tool_errors
from .factory import build_search
from .store import PgVectorSearch
from .tools import RunbookTools

log = logging.getLogger("mcp.runbooks")
cfg = settings.integrations.runbooks
search = build_search(settings)
tools = RunbookTools(search, cfg)


async def _index_once() -> None:
    """Index at startup when configured. A failure (say, the embedding model is not pulled
    yet) is logged rather than fatal: search still works on text, and /readyz reports it."""
    assert isinstance(search, PgVectorSearch)
    try:
        result = await search.sync()
        log.info("runbooks indexed", extra={"fields": result})
    except IntegrationError as exc:
        log.warning("runbook indexing failed", extra={"fields": {"error": str(exc)}})


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    if isinstance(search, PgVectorSearch):
        await search.open()
        if cfg.index_on_start:
            await _index_once()
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
    serve(mcp, 9104)
