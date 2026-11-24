import os
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from copilot.config import settings
from copilot.telemetry import setup_logging

from ..common.server import health_payload, tool_errors
from .client import GitHubClient
from .tools import CodeTools

client = GitHubClient(settings.integrations.code.github)
tools = CodeTools(client, settings)
mcp = FastMCP("github")


@mcp.tool
@tool_errors
async def service_repos() -> list[dict[str, Any]]:
    """Which repository, branch and paths hold each service's code."""
    return await tools.service_repos()


@mcp.tool
@tool_errors
async def recent_commits(service: str, since_hours: int = 24) -> dict[str, Any]:
    """Commits in the last N hours that touched a service's code, newest first."""
    return await tools.recent_commits(service, since_hours)


@mcp.tool
@tool_errors
async def commit_diff(service: str, sha: str) -> dict[str, Any]:
    """Files changed by one commit with truncated patches; files under the service's paths
    come first. Lock files and binaries are listed but not shown."""
    return await tools.commit_diff(service, sha)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/readyz", methods=["GET"])
async def readyz(_: Request) -> JSONResponse:
    try:
        info = await client.ping()
    except Exception as exc:
        return JSONResponse(health_payload("github", client.name, exc), status_code=503)
    return JSONResponse({**health_payload("github", client.name, None), **info})


if __name__ == "__main__":
    setup_logging()
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "9103")))
