"""Call one tool on a running MCP server, for manual testing.

python scripts/mcp_call.py logs list_services
python scripts/mcp_call.py logs error_summary service=payments since_minutes=30
"""

import asyncio
import json
import sys

from fastmcp import Client

from copilot.config import settings

SERVERS = {
    "logs": settings.mcp.logs_url,
    "metrics": settings.mcp.metrics_url,
    "github": settings.mcp.github_url,
    "runbook": settings.mcp.runbook_url,
}


def parse_args(pairs: list[str]) -> dict[str, object]:
    args: dict[str, object] = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        try:
            args[key] = json.loads(raw)
        except json.JSONDecodeError:
            args[key] = raw
    return args


async def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in SERVERS:
        print(__doc__)
        return 2
    server, tool = sys.argv[1], sys.argv[2]
    try:
        async with Client(SERVERS[server]) as client:
            result = await client.call_tool(tool, parse_args(sys.argv[3:]), raise_on_error=False)
    except RuntimeError as exc:
        if "failed to connect" not in str(exc).lower():
            raise
        print(f"Could not reach the {server} MCP server at {SERVERS[server]}.")
        print(f"Start it in another terminal: python -m mcp_servers.{server}.server")
        return 1
    if result.is_error:
        print("TOOL ERROR:", result.content[0].text)
        return 1
    print(json.dumps(result.structured_content or result.data, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
