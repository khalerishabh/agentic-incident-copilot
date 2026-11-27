"""End-to-end checks against the running Docker Compose stack.

    docker compose up -d --build --wait
    E2E=1 pytest tests/e2e

Each test talks to the MCP servers over HTTP exactly as the agents will, after injecting a
real fault into the demo services. Skipped unless E2E=1.
"""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastmcp import Client

pytestmark = pytest.mark.skipif(os.getenv("E2E") != "1", reason="set E2E=1 with the stack up")

HOST = os.getenv("E2E_HOST", "localhost")
MCP = {
    name: f"http://{HOST}:{port}/mcp"
    for name, port in [("logs", 9101), ("metrics", 9102), ("github", 9103), ("runbook", 9104)]
}
PAYMENTS = f"http://{HOST}:8002"
CHAOS = {"x-chaos-token": os.getenv("CHAOS_ADMIN_TOKEN", "change-me")}
SERVICES = {"gateway", "orders", "payments", "inventory"}


async def call(server: str, tool: str, **args: Any) -> Any:
    async with Client(MCP[server]) as client:
        result = await client.call_tool(tool, args, raise_on_error=False)
    assert not result.is_error, f"{server}.{tool} failed: {result.content[0].text}"
    data = result.structured_content
    return data.get("result", data) if isinstance(data, dict) else result.data


async def eventually(
    check: Callable[[], Awaitable[Any]], timeout: float, what: str, every: float = 5.0
) -> Any:
    """Poll until check() returns something truthy. Logs, scrapes and rate windows all lag."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = await check()
        if last:
            return last
        await asyncio.sleep(every)
    pytest.fail(f"timed out after {timeout}s waiting for {what}; last result: {last!r}")


@pytest.fixture
async def payments_failing():
    async with httpx.AsyncClient(base_url=PAYMENTS, headers=CHAOS, timeout=10) as http:
        resp = await http.post("/chaos/error_rate", json={"probability": 0.5})
        assert resp.status_code == 200, resp.text
        try:
            yield
        finally:
            await http.delete("/chaos/error_rate")


async def test_every_mcp_server_is_ready():
    async with httpx.AsyncClient(timeout=10) as http:
        for name, url in MCP.items():
            path = "/healthz" if name == "github" else "/readyz"
            resp = await http.get(url.removesuffix("/mcp") + path)
            assert resp.status_code == 200, f"{name}: {resp.text}"


async def test_metrics_see_all_demo_services():
    async def scraped():
        return SERVICES <= set(await call("metrics", "list_services"))

    await eventually(scraped, 90, "Prometheus to scrape all demo services")


async def test_code_server_maps_every_service_to_a_repo():
    repos = await call("github", "service_repos")
    assert {r["service"] for r in repos} == SERVICES
    assert all(r["repo"] for r in repos)


async def test_runbook_search_finds_the_error_rate_runbook():
    result = await call("runbook", "search_runbooks", query="high 5xx error rate", k=3)
    assert result["results"], result
    assert result["results"][0]["runbook"] == "high-error-rate"


async def test_injected_payments_fault_is_traced_to_payments(payments_failing):
    async def origin():
        out = await call("metrics", "upstream_errors", window="1m")
        return out if out["likely_origins"] == ["payments"] else None

    result = await eventually(origin, 180, "metrics to point at payments")
    callers = {(c["caller"], c["callee"]) for c in result["failing_calls"]}
    assert ("orders", "payments") in callers


async def test_injected_payments_fault_reaches_logs_through_loki(payments_failing):
    async def errors():
        out = await call("logs", "error_summary", service="payments", since_minutes=5)
        issues = [i["issue"] for i in out["top_issues"]]
        return out if any("internal processing error" in i for i in issues) else None

    result = await eventually(errors, 120, "payments errors to reach Loki")
    assert result["problem_lines"] > 0
