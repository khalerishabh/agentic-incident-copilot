from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from copilot.config import settings

from ..common.runtime import serve
from ..common.server import health_payload, tool_errors
from .factory import build_backend
from .tools import LogTools

cfg = settings.integrations.logs
backend = build_backend(cfg)
tools = LogTools(backend, cfg)
mcp = FastMCP("logs")


@mcp.tool
@tool_errors
async def list_services() -> list[str]:
    """List services that have logs in the last 24 hours."""
    return await tools.list_services()


@mcp.tool
@tool_errors
async def error_summary(service: str, since_minutes: int = 15) -> dict[str, Any]:
    """Group WARNING/ERROR/CRITICAL log lines for a service by message, with counts and
    first/last seen times. Use this first; it is far cheaper than reading raw lines."""
    return await tools.error_summary(service, since_minutes)


@mcp.tool
@tool_errors
async def search_logs(
    service: str, contains: str = "", level: str = "", since_minutes: int = 15, limit: int = 20
) -> list[dict[str, Any]]:
    """Most recent matching log lines for one service, oldest first. Results are capped."""
    return await tools.search_logs(service, contains, level, since_minutes, limit)


@mcp.tool
@tool_errors
async def trace_request(request_id: str, since_minutes: int = 30) -> list[dict[str, Any]]:
    """Follow one request id across every service, ordered by time."""
    return await tools.trace_request(request_id, since_minutes)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/readyz", methods=["GET"])
async def readyz(_: Request) -> JSONResponse:
    try:
        await backend.ping()
    except Exception as exc:
        return JSONResponse(health_payload("logs", backend.name, exc), status_code=503)
    return JSONResponse(health_payload("logs", backend.name, None))


if __name__ == "__main__":
    serve(mcp, 9101)
