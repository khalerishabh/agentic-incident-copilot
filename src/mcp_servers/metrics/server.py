import os

import httpx
from fastmcp import FastMCP

PROM = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
mcp = FastMCP("metrics")


def _query(promql: str) -> list[dict]:
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": promql}, timeout=10)
    r.raise_for_status()
    return [
        {"labels": s["metric"], "value": float(s["value"][1])}
        for s in r.json()["data"]["result"]
    ]


@mcp.tool
def service_red(service: str, window: str = "2m") -> dict:
    """Rate, errors and p95 duration for one service over a window like '2m'."""
    rate = _query(f'sum(rate(http_requests_total{{service="{service}"}}[{window}]))')
    errors = _query(
        f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[{window}]))'
    )
    p95 = _query(
        "histogram_quantile(0.95, sum by (le) "
        f'(rate(http_request_duration_seconds_bucket{{service="{service}"}}[{window}])))'
    )
    val = lambda res: res[0]["value"] if res else 0.0
    rps = val(rate)
    return {
        "service": service,
        "rps": round(rps, 3),
        "error_ratio": round(val(errors) / rps, 4) if rps else 0.0,
        "p95_seconds": round(val(p95), 3),
    }


@mcp.tool
def resource_usage(service: str) -> dict:
    """Memory (RSS) and CPU rate for a service's process."""
    rss = _query(f'process_resident_memory_bytes{{instance=~"{service}:.*"}}')
    cpu = _query(f'rate(process_cpu_seconds_total{{instance=~"{service}:.*"}}[1m])')
    return {
        "service": service,
        "rss_mb": round(rss[0]["value"] / 1e6, 1) if rss else None,
        "cpu_cores": round(cpu[0]["value"], 3) if cpu else None,
    }


@mcp.tool
def upstream_errors(window: str = "2m") -> list[dict]:
    """Which service-to-service calls are failing, by caller and callee."""
    return _query(f"sum by (service, upstream) (rate(upstream_errors_total[{window}])) > 0")


@mcp.tool
def run_promql(promql: str) -> list[dict]:
    """Escape hatch: run an instant PromQL query. Prefer the specific tools."""
    return _query(promql)[:50]


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "9102")))
