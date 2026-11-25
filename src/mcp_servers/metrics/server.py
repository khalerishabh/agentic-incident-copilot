from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from copilot.config import settings

from ..common.runtime import serve
from ..common.server import health_payload, tool_errors
from .prometheus import PrometheusClient
from .tools import MetricTools

cfg = settings.integrations.metrics
client = PrometheusClient(cfg.prometheus)
tools = MetricTools(client, cfg)
mcp = FastMCP("metrics")


@mcp.tool
@tool_errors
async def list_services() -> list[str]:
    """Services that currently report request metrics."""
    return await tools.list_services()


@mcp.tool
@tool_errors
async def compare_services(window: str = "5m") -> list[dict[str, Any]]:
    """Rate, error ratio and p95 latency for every service, worst first. Start here to see
    where errors originate rather than where they are merely observed."""
    return await tools.compare_services(window)


@mcp.tool
@tool_errors
async def service_red(service: str, window: str = "5m") -> dict[str, Any]:
    """Rate, error ratio and p50/p95/p99 latency for one service over a window like '5m'."""
    return await tools.service_red(service, window)


@mcp.tool
@tool_errors
async def red_timeline(service: str, minutes: int = 30, step: str = "1m") -> dict[str, Any]:
    """Rate, error ratio and p95 over time for one service, with hints for when error ratio
    and latency first rose. Use it to line a problem up with deploys and log events."""
    return await tools.red_timeline(service, minutes, step)


@mcp.tool
@tool_errors
async def resource_usage(service: str, window: str = "10m") -> dict[str, Any]:
    """Memory now, memory growth over the window, and CPU cores used by a service."""
    return await tools.resource_usage(service, window)


@mcp.tool
@tool_errors
async def upstream_errors(window: str = "5m") -> dict[str, Any]:
    """Failing service-to-service calls by caller and callee, worst first, plus the services
    where the failures most likely originate."""
    return await tools.upstream_errors(window)


@mcp.tool
@tool_errors
async def run_promql(query: str) -> dict[str, Any]:
    """Escape hatch: run an instant PromQL query. Prefer the specific tools; results are capped."""
    return await tools.run_promql(query)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/readyz", methods=["GET"])
async def readyz(_: Request) -> JSONResponse:
    try:
        await client.ping()
    except Exception as exc:
        return JSONResponse(health_payload("metrics", client.name, exc), status_code=503)
    return JSONResponse(health_payload("metrics", client.name, None))


if __name__ == "__main__":
    serve(mcp, 9102)
