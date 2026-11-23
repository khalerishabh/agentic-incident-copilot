import httpx
import pytest

from mcp_servers.common.errors import IntegrationError
from mcp_servers.common.http import RetryPolicy, request


def _policy(delays: list[float], attempts: int = 3) -> RetryPolicy:
    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    return RetryPolicy(max_attempts=attempts, sleep=fake_sleep)


def _client(responses: list) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x"), seen


async def test_retries_gateway_errors_then_succeeds():
    delays: list[float] = []
    client, seen = _client([httpx.Response(503), httpx.Response(502), httpx.Response(200)])
    resp = await request(client, "GET", "/q", integration="t", policy=_policy(delays))
    assert resp.status_code == 200
    assert len(seen) == 3
    assert len(delays) == 2


async def test_client_errors_fail_without_retry():
    client, seen = _client([httpx.Response(400, text="bad query")])
    with pytest.raises(IntegrationError, match="HTTP 400: bad query") as info:
        await request(client, "GET", "/q", integration="t", policy=_policy([]))
    assert len(seen) == 1
    assert info.value.retryable is False


async def test_timeouts_exhaust_attempts_and_are_retryable():
    timeout = httpx.ReadTimeout("slow")
    client, seen = _client([timeout, timeout, timeout])
    with pytest.raises(IntegrationError, match="after 3 attempts .timed out.") as info:
        await request(client, "GET", "/q", integration="t", policy=_policy([]))
    assert len(seen) == 3
    assert info.value.retryable is True


async def test_retry_after_header_is_honoured_but_capped():
    delays: list[float] = []
    client, _ = _client([httpx.Response(429, headers={"retry-after": "60"}), httpx.Response(200)])
    await request(client, "GET", "/q", integration="t", policy=_policy(delays))
    assert delays == [RetryPolicy().max_delay]
