import time
from typing import Any

import httpx
import pytest

from copilot.config import MetricsIntegration, PrometheusConfig
from mcp_servers.common.errors import IntegrationError, InvalidInput
from mcp_servers.common.http import RetryPolicy
from mcp_servers.metrics.prometheus import PrometheusClient
from mcp_servers.metrics.tools import MetricTools


async def _no_sleep(_: float) -> None:
    return None


def _vector(*samples: tuple[dict[str, str], str]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": m, "value": [time.time(), v]} for m, v in samples],
        },
    }


def _tools(answer, **cfg) -> tuple[MetricTools, list[str]]:
    """answer(query) returns the JSON body Prometheus would send for that query."""
    queries: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        query = req.url.params.get("query", "")
        queries.append(query)
        body = answer(query, req)
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    config = MetricsIntegration(prometheus=PrometheusConfig(url="http://prom:9090"), **cfg)
    client = PrometheusClient(
        config.prometheus,
        transport=httpx.MockTransport(handler),
        policy=RetryPolicy(max_attempts=2, sleep=_no_sleep),
    )
    return MetricTools(client, config), queries


async def test_service_red_turns_nan_quantiles_into_none():
    def answer(q, _):
        if q.startswith("histogram_quantile(0.99"):
            return _vector(({}, "NaN"))
        if "status=~" in q:
            return _vector(({}, "1"))
        if q.startswith("histogram_quantile"):
            return _vector(({}, "0.2"))
        return _vector(({}, "4"))

    tools, queries = _tools(answer)
    out = await tools.service_red("payments", "5m")
    assert out["rps"] == 4
    assert out["error_ratio"] == 0.25
    assert out["p95_seconds"] == 0.2
    assert out["p99_seconds"] is None
    assert all('service="payments"' in q for q in queries)


async def test_service_red_with_no_traffic_reports_none_not_zero_errors():
    tools, _ = _tools(lambda q, _: _vector())
    out = await tools.service_red("payments", "5m")
    assert out["error_ratio"] is None
    assert "note" in out


async def test_compare_services_ranks_worst_first():
    def answer(q, _):
        if q.startswith("histogram_quantile"):
            return _vector(({"service": "a"}, "0.1"), ({"service": "b"}, "0.9"))
        if "status=~" in q:
            return _vector(({"service": "b"}, "5"))
        return _vector(({"service": "a"}, "10"), ({"service": "b"}, "10"))

    tools, _ = _tools(answer)
    rows = await tools.compare_services("5m")
    assert [r["service"] for r in rows] == ["b", "a"]
    assert rows[0]["error_ratio"] == 0.5
    assert rows[1]["error_ratio"] == 0.0


async def test_upstream_errors_points_at_deepest_failing_callee():
    def answer(q, _):
        return _vector(
            ({"service": "gateway", "upstream": "orders"}, "4"),
            ({"service": "orders", "upstream": "payments"}, "4.5"),
        )

    tools, _ = _tools(answer)
    out = await tools.upstream_errors("5m")
    assert out["likely_origins"] == ["payments"]
    assert out["failing_calls"][0]["callee"] == "payments"


async def test_custom_metric_names_and_labels_are_used():
    tools, queries = _tools(
        lambda q, _: _vector(({}, "1")),
        service_label="app",
        names={"requests_total": "http_server_requests_seconds_count", "status_label": "code"},
    )
    await tools.service_red("payments", "5m")
    assert 'http_server_requests_seconds_count{app="payments",code=~"5.."}' in " ".join(queries)


async def test_prometheus_parse_error_reaches_the_agent_verbatim():
    def answer(q, _):
        return httpx.Response(
            400,
            json={"status": "error", "errorType": "bad_data", "error": "parse error: unclosed"},
        )

    tools, _ = _tools(answer)
    with pytest.raises(IntegrationError, match="query rejected: parse error: unclosed"):
        await tools.run_promql("sum(rate(x[1m]")


async def test_raw_promql_can_be_disabled():
    tools, queries = _tools(lambda q, _: _vector(), allow_raw_promql=False)
    with pytest.raises(InvalidInput, match="disabled"):
        await tools.run_promql("up")
    assert queries == []


async def test_raw_promql_results_are_capped():
    many = [({"instance": str(i)}, "1") for i in range(80)]
    tools, _ = _tools(lambda q, _: _vector(*many), max_series=10)
    out = await tools.run_promql("up")
    assert len(out["series"]) == 10
    assert out["truncated"] is True


@pytest.mark.parametrize("window", ["5 minutes", "0s", "99h", "5d", "5m]) or vector(1"])
async def test_bad_windows_are_rejected(window):
    tools, queries = _tools(lambda q, _: _vector())
    with pytest.raises(InvalidInput):
        await tools.service_red("payments", window)
    assert queries == []


async def test_timeline_hint_finds_when_errors_started():
    now = time.time()
    ratios = [0.0] * 8 + [0.4] * 4

    def answer(q, req):
        values = [[now - 60 * (len(ratios) - i), str(v)] for i, v in enumerate(ratios)]
        if not q.startswith("(sum"):
            values = [[t, "1"] for t, _ in values]
        return {
            "status": "success",
            "data": {"resultType": "matrix", "result": [{"metric": {}, "values": values}]},
        }

    tools, _ = _tools(answer)
    out = await tools.red_timeline("payments", minutes=15, step="1m")
    assert len(out["points"]) == len(ratios)
    rose = out["hints"]["error_ratio_rose_at"]
    assert rose == out["points"][8]["t"]
    assert out["hints"]["p95_rose_at"] is None


async def test_timeline_refuses_too_many_points():
    tools, _ = _tools(lambda q, _: _vector())
    with pytest.raises(InvalidInput, match="too many points"):
        await tools.red_timeline("payments", minutes=600, step="15s")
