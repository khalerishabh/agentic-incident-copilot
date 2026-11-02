from langchain_mcp_adapters.client import MultiServerMCPClient

from .config import settings

READ_ONLY_SERVERS = {
    "logs": settings.mcp_logs_url,
    "metrics": settings.mcp_metrics_url,
    "github": settings.mcp_github_url,
    "runbook": settings.mcp_runbook_url,
}

_client = MultiServerMCPClient(
    {name: {"url": url, "transport": "streamable_http"} for name, url in READ_ONLY_SERVERS.items()}
)


async def tools_for(server: str):
    """Tools from a single MCP server, so each agent only sees its own toolset."""
    return await _client.get_tools(server_name=server)
