import math
from datetime import datetime
from typing import Any

import httpx

from copilot.config import PrometheusConfig

from ..common.errors import IntegrationError
from ..common.http import RetryPolicy, request

INTEGRATION = "metrics/prometheus"


def to_float(raw: Any) -> float | None:
    """Prometheus encodes samples as strings and uses NaN/Inf, which JSON cannot carry."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class PrometheusClient:
    """Speaks the Prometheus HTTP API, so it also works with Mimir, Thanos and VictoriaMetrics."""

    name = "prometheus"

    def __init__(
        self,
        cfg: PrometheusConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.cfg = cfg
        self.policy = policy or RetryPolicy(max_attempts=cfg.max_attempts)
        headers = {}
        if cfg.bearer_token:
            headers["Authorization"] = f"Bearer {cfg.bearer_token.get_secret_value()}"
        auth = None
        if cfg.username and cfg.password:
            auth = httpx.BasicAuth(cfg.username, cfg.password.get_secret_value())
        self._client = httpx.AsyncClient(
            base_url=cfg.url.rstrip("/"),
            timeout=cfg.timeout_seconds,
            headers=headers,
            auth=auth,
            transport=transport,
        )

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        resp = await request(
            self._client,
            "GET",
            path,
            integration=INTEGRATION,
            policy=self.policy,
            accept_status=frozenset({400, 422}),
            params=params,
        )
        try:
            body = resp.json()
        except ValueError as exc:
            raise IntegrationError(INTEGRATION, "response was not JSON") from exc
        if body.get("status") != "success":
            raise IntegrationError(
                INTEGRATION, f"query rejected: {body.get('error', 'unknown error')}"
            )
        return body.get("data")

    async def instant(self, query: str) -> list[dict[str, Any]]:
        """Instant vector as [{labels, value}]. Scalars come back as one unlabelled sample."""
        data = await self._api("/api/v1/query", {"query": query, "timeout": self.cfg.query_timeout})
        if data.get("resultType") == "scalar":
            return [{"labels": {}, "value": to_float(data["result"][1])}]
        return [
            {"labels": s.get("metric", {}), "value": to_float(s["value"][1])}
            for s in data.get("result", [])
        ]

    async def scalar(self, query: str) -> float | None:
        result = await self.instant(query)
        return result[0]["value"] if result else None

    async def range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> list[dict[str, Any]]:
        data = await self._api(
            "/api/v1/query_range",
            {
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_seconds,
                "timeout": self.cfg.query_timeout,
            },
        )
        return [
            {
                "labels": s.get("metric", {}),
                "values": [(float(t), to_float(v)) for t, v in s.get("values", [])],
            }
            for s in data.get("result", [])
        ]

    async def label_values(self, label: str, match: str | None = None) -> list[str]:
        params = {"match[]": match} if match else {}
        result = await self._api(f"/api/v1/label/{label}/values", params)
        return sorted(result) if isinstance(result, list) else []

    async def ping(self) -> None:
        await request(self._client, "GET", "/-/ready", integration=INTEGRATION, policy=self.policy)

    async def aclose(self) -> None:
        await self._client.aclose()
