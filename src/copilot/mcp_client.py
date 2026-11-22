from functools import lru_cache

from langchain_mcp_adapters.client import MultiServerMCPClient

from .config import settings


@lru_cache
def _client() -> MultiServerMCPClient:
    servers = {
        "logs": settings.mcp.logs_url,
        "metrics": settings.mcp.metrics_url,
        "github": settings.mcp.github_url,
        "runbook": settings.mcp.runbook_url,
    }
    return MultiServerMCPClient(
        {name: {"url": url, "transport": "streamable_http"} for name, url in servers.items()}  # type: ignore[misc]
    )


async def tools_for(server: str):
    """Tools from a single MCP server, so each agent only sees its own toolset."""
    return await _client().get_tools(server_name=server)
