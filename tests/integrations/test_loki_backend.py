import json
import re
from datetime import timedelta

import httpx
import pytest

from copilot.config import LogFieldMap, LokiConfig
from mcp_servers.common.errors import IntegrationError
from mcp_servers.common.http import RetryPolicy
from mcp_servers.logs.backend import LogQuery
from mcp_servers.logs.loki_backend import LokiLogBackend, quote, regex_literal


async def _no_sleep(_: float) -> None:
    return None


def _backend(handler, **cfg) -> LokiLogBackend:
    return LokiLogBackend(
        LokiConfig(url="http://loki:3100", **cfg),
        "service",
        LogFieldMap(),
        transport=httpx.MockTransport(handler),
        policy=RetryPolicy(max_attempts=2, sleep=_no_sleep),
    )


def _streams(*lines: tuple[str, int, dict]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {"stream": {"service": svc}, "values": [[str(ts), json.dumps(body)]]}
                for svc, ts, body in lines
            ],
        },
    }


def test_quote_escapes_quotes_and_backslashes():
    assert quote('a"b\\c') == '"a\\"b\\\\c"'


def test_regex_literal_keeps_spaces_unescaped():
    assert regex_literal("pool timeout (5s)") == "pool timeout \\(5s\\)"


def test_query_for_errors_in_one_service():
    b = _backend(lambda r: httpx.Response(200))
    q = b.build_query(LogQuery(since=timedelta(minutes=5), service="payments", levels=("ERROR",)))
    assert q == '{service="payments"} | json | level=~"(?i)^(ERR|ERROR)$"'


def test_query_for_request_trace_spans_all_services():
    b = _backend(lambda r: httpx.Response(200))
    q = b.build_query(LogQuery(since=timedelta(minutes=5), request_id="abc123"))
    assert q == '{service=~".+"} |= "abc123" | json | request_id="abc123"'


def _line_filter_regex(query: str) -> re.Pattern[str]:
    """Decode the |~ "..." literal from a LogQL query back into the regex Loki will run."""
    literal = query.split("|~ ", 1)[1].split(" | ", 1)[0]
    return re.compile(json.loads(literal))


def test_injection_attempt_in_contains_stays_inside_the_literal():
    b = _backend(lambda r: httpx.Response(200))
    attack = 'x"} or {job=~".+'
    q = b.build_query(LogQuery(since=timedelta(minutes=5), service="orders", contains=attack))
    assert q.startswith('{service="orders"} |~ ')
    assert q.count("{service=") == 1
    pattern = _line_filter_regex(q)
    assert pattern.search(json.dumps({"msg": attack}))
    assert not pattern.search(json.dumps({"msg": "x"}))


def test_contains_matches_json_escaped_quotes_in_raw_lines():
    b = _backend(lambda r: httpx.Response(200))
    q = b.build_query(
        LogQuery(since=timedelta(minutes=5), service="orders", contains='"Quoted" (x)')
    )
    raw_line = json.dumps({"msg": 'a "quoted" (x) value'})
    assert _line_filter_regex(q).search(raw_line)


async def test_fetch_parses_streams_oldest_first_and_caps():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/loki/api/v1/query_range"
        assert req.url.params["direction"] == "backward"
        return httpx.Response(
            200,
            json=_streams(
                (
                    "payments",
                    3_000_000_000,
                    {
                        "ts": "2026-11-23T10:00:03+00:00",
                        "level": "error",
                        "msg": "boom",
                        "request_id": "r1",
                        "route": "/charge",
                    },
                ),
                (
                    "payments",
                    1_000_000_000,
                    {"ts": "2026-11-23T10:00:01+00:00", "level": "WARN", "msg": "slow"},
                ),
            ),
        )

    records = await _backend(handler).fetch(
        LogQuery(since=timedelta(minutes=5), service="payments", limit=10)
    )
    assert [r.message for r in records] == ["slow", "boom"]
    assert records[0].level == "WARNING"
    assert records[1].level == "ERROR"
    assert records[1].to_dict()["route"] == "/charge"


async def test_count_reads_instant_vector():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "count_over_time" in req.url.params["query"]
        assert "[15m]" in req.url.params["query"]
        return httpx.Response(
            200, json={"status": "success", "data": {"result": [{"value": [0, "42"]}]}}
        )

    assert await _backend(handler).count("orders", timedelta(minutes=15)) == 42


async def test_tenant_header_and_basic_auth_are_sent():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"status": "success", "data": ["orders"]})

    b = _backend(handler, tenant_id="team-a", username="u", password="p")
    assert await b.services() == ["orders"]
    assert seen[0].headers["X-Scope-OrgID"] == "team-a"
    assert seen[0].headers["Authorization"].startswith("Basic ")


async def test_loki_down_becomes_retryable_integration_error():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(IntegrationError) as info:
        await _backend(handler).ping()
    assert info.value.retryable is True
    assert "logs/loki" in str(info.value)
