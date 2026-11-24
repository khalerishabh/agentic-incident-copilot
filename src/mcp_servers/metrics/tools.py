import statistics
from datetime import UTC, datetime
from typing import Any

from copilot.config import MetricsIntegration

from ..common import limits
from ..common.errors import InvalidInput
from .prometheus import PrometheusClient

QUANTILES = (0.5, 0.95, 0.99)
MAX_PROMQL_CHARS = 1000


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _ratio(part: float | None, whole: float | None) -> float | None:
    """Error ratio; None when there was no traffic, since 0/0 is not 'no errors'."""
    if not whole:
        return None
    return (part or 0.0) / whole


def _first_sustained_rise(
    points: list[tuple[float, float | None]], floor: float, factor: float
) -> str | None:
    """First time a series rises above max(floor, factor * early baseline) and stays there
    for two consecutive points. A hint for when a problem started, not a verdict."""
    values = [v for _, v in points if v is not None]
    if len(values) < 4:
        return None
    baseline = statistics.median(values[: max(2, len(values) // 4)])
    threshold = max(floor, factor * baseline)
    for (t, v), (_, nxt) in zip(points, points[1:], strict=False):
        if v is not None and nxt is not None and v > threshold and nxt > threshold:
            return datetime.fromtimestamp(t, tz=UTC).isoformat()
    return None


class MetricTools:
    def __init__(self, client: PrometheusClient, cfg: MetricsIntegration) -> None:
        self.client = client
        self.cfg = cfg
        self.names = cfg.names

    def _sel(self, service: str, extra: str = "", label: str | None = None) -> str:
        matcher = f'{label or self.cfg.service_label}="{service}"'
        return "{" + matcher + (f",{extra}" if extra else "") + "}"

    def _errors_matcher(self) -> str:
        return f'{self.names.status_label}=~"{self.names.error_status_regex}"'

    def _window(self, window: str) -> str:
        limits.duration(window, self.cfg.max_window_minutes, minimum_seconds=30)
        return window

    async def list_services(self) -> list[str]:
        return await self.client.label_values(
            self.cfg.service_label, match=self.names.requests_total
        )

    async def service_red(self, service: str, window: str = "5m") -> dict[str, Any]:
        service = limits.service_name(service)
        w = self._window(window)
        req, bucket = self.names.requests_total, self.names.duration_bucket
        rps = await self.client.scalar(f"sum(rate({req}{self._sel(service)}[{w}]))")
        errors = await self.client.scalar(
            f"sum(rate({req}{self._sel(service, self._errors_matcher())}[{w}]))"
        )
        out: dict[str, Any] = {
            "service": service,
            "window": w,
            "rps": _round(rps, 3),
            "error_ratio": _round(_ratio(errors, rps)),
        }
        for q in QUANTILES:
            value = await self.client.scalar(
                f"histogram_quantile({q}, sum by (le) (rate({bucket}{self._sel(service)}[{w}])))"
            )
            out[f"p{int(q * 100)}_seconds"] = _round(value, 3)
        if rps is None:
            out["note"] = "no request metrics found for this service in the window"
        return out

    async def compare_services(self, window: str = "5m") -> list[dict[str, Any]]:
        w = self._window(window)
        label, req = self.cfg.service_label, self.names.requests_total
        rps = await self.client.instant(f"sum by ({label}) (rate({req}[{w}]))")
        errors = await self.client.instant(
            f"sum by ({label}) (rate({req}{{{self._errors_matcher()}}}[{w}]))"
        )
        p95 = await self.client.instant(
            f"histogram_quantile(0.95, sum by ({label}, le) "
            f"(rate({self.names.duration_bucket}[{w}])))"
        )
        err_by = {s["labels"].get(label): s["value"] for s in errors}
        p95_by = {s["labels"].get(label): s["value"] for s in p95}
        rows = []
        for sample in rps:
            name = sample["labels"].get(label)
            if not name:
                continue
            rows.append(
                {
                    "service": name,
                    "rps": _round(sample["value"], 3),
                    "error_ratio": _round(_ratio(err_by.get(name, 0.0), sample["value"])),
                    "p95_seconds": _round(p95_by.get(name), 3),
                }
            )
        rows.sort(key=lambda r: (-(r["error_ratio"] or 0), -(r["p95_seconds"] or 0)))
        return rows[: self.cfg.max_series]

    async def red_timeline(
        self, service: str, minutes: int = 30, step: str = "1m"
    ) -> dict[str, Any]:
        service = limits.service_name(service)
        since = limits.window(minutes, self.cfg.max_window_minutes)
        step_s = limits.duration(step, self.cfg.max_window_minutes, minimum_seconds=15)
        if since.total_seconds() / step_s > self.cfg.max_points:
            raise InvalidInput(f"too many points; use a larger step (max {self.cfg.max_points})")
        rate_w = f"{max(60, 2 * step_s)}s"
        req, bucket = self.names.requests_total, self.names.duration_bucket
        sel, err_sel = self._sel(service), self._sel(service, self._errors_matcher())
        end = datetime.now(UTC)
        start = end - since
        queries = {
            "rps": f"sum(rate({req}{sel}[{rate_w}]))",
            "error_ratio": f"(sum(rate({req}{err_sel}[{rate_w}])) or vector(0)) "
            f"/ sum(rate({req}{sel}[{rate_w}]))",
            "p95_seconds": f"histogram_quantile(0.95, sum by (le) (rate({bucket}{sel}[{rate_w}])))",
        }
        series: dict[str, dict[float, float | None]] = {}
        for key, query in queries.items():
            result = await self.client.range(query, start, end, step_s)
            series[key] = dict(result[0]["values"]) if result else {}
        times = sorted(set().union(*(s.keys() for s in series.values())))
        points = [
            {
                "t": datetime.fromtimestamp(t, tz=UTC).isoformat(),
                **{k: _round(series[k].get(t), 4) for k in queries},
            }
            for t in times
        ]
        return {
            "service": service,
            "step": step,
            "points": points,
            "hints": {
                "error_ratio_rose_at": _first_sustained_rise(
                    [(t, series["error_ratio"].get(t)) for t in times], floor=0.05, factor=3
                ),
                "p95_rose_at": _first_sustained_rise(
                    [(t, series["p95_seconds"].get(t)) for t in times], floor=0.25, factor=2
                ),
            },
        }

    async def resource_usage(self, service: str, window: str = "10m") -> dict[str, Any]:
        service = limits.service_name(service)
        w = self._window(window)
        label = self.cfg.resource_service_label or self.cfg.service_label
        sel = self._sel(service, label=label)
        mem, cpu = self.names.memory_bytes, self.names.cpu_seconds_total
        now = await self.client.scalar(f"sum({mem}{sel})")
        before = await self.client.scalar(f"sum({mem}{sel} offset {w})")
        cores = await self.client.scalar(f"sum(rate({cpu}{sel}[{w}]))")
        growth = None if now is None or before is None else round((now - before) / 1e6, 1)
        return {
            "service": service,
            "window": w,
            "memory_mb": None if now is None else round(now / 1e6, 1),
            "memory_growth_mb": growth,
            "cpu_cores": _round(cores, 3),
        }

    async def upstream_errors(self, window: str = "5m") -> dict[str, Any]:
        metric = self.names.upstream_errors_total
        if not metric:
            raise InvalidInput("upstream error metric is not configured")
        w = self._window(window)
        label, up = self.cfg.service_label, self.names.upstream_label
        result = await self.client.instant(f"sum by ({label}, {up}) (rate({metric}[{w}])) > 0")
        rows = [
            {
                "caller": s["labels"].get(label),
                "callee": s["labels"].get(up),
                "errors_per_second": _round(s["value"], 3),
            }
            for s in result
        ]
        rows.sort(key=lambda r: -(r["errors_per_second"] or 0))
        callers = {r["caller"] for r in rows}
        origins = sorted({r["callee"] for r in rows if r["callee"] not in callers})
        return {
            "failing_calls": rows[: self.cfg.max_series],
            "likely_origins": origins,
            "note": "likely_origins are failing callees whose own downstream calls are healthy; "
            "a hint for where errors start, to confirm with logs",
        }

    async def run_promql(self, query: str) -> dict[str, Any]:
        if not self.cfg.allow_raw_promql:
            raise InvalidInput("raw PromQL is disabled (integrations.metrics.allow_raw_promql)")
        if not query.strip() or len(query) > MAX_PROMQL_CHARS:
            raise InvalidInput(f"query must be 1-{MAX_PROMQL_CHARS} characters")
        result = await self.client.instant(query)
        return {
            "series": result[: self.cfg.max_series],
            "truncated": len(result) > self.cfg.max_series,
        }
