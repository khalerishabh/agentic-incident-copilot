import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from copilot.config import LogFieldMap, LokiConfig

from ..common.errors import IntegrationError
from ..common.http import RetryPolicy, request
from .backend import LogQuery, LogRecord, level_variants, parse_line

INTEGRATION = "logs/loki"


def quote(value: str) -> str:
    """A LogQL double-quoted string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


RE2_SPECIAL = set("\\.+*?()|[]{}^$")


def regex_literal(value: str) -> str:
    """Escape a literal for RE2. Python's re.escape also escapes spaces, which RE2 rejects."""
    return "".join("\\" + ch if ch in RE2_SPECIAL else ch for ch in value)


def _ns(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1_000_000_000))


class LokiLogBackend:
    name = "loki"

    def __init__(
        self,
        cfg: LokiConfig,
        service_label: str,
        fields: LogFieldMap,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.cfg = cfg
        self.service_label = service_label
        self.fields = fields
        self.policy = policy or RetryPolicy(max_attempts=cfg.max_attempts)
        headers = {"X-Scope-OrgID": cfg.tenant_id} if cfg.tenant_id else {}
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

    def selector(self, service: str | None) -> str:
        if service:
            return "{" + f"{self.service_label}={quote(service)}" + "}"
        return "{" + f'{self.service_label}=~".+"' + "}"

    def build_query(self, query: LogQuery) -> str:
        parts = [self.selector(query.service)]
        if query.contains:
            needle = query.contains
            if self.cfg.line_format == "json":
                # Line filters see the raw line, where quotes and backslashes are JSON-escaped.
                needle = json.dumps(needle)[1:-1]
            parts.append(f"|~ {quote('(?i)' + regex_literal(needle))}")
        if query.request_id:
            parts.append(f"|= {quote(query.request_id)}")
        if query.levels or query.request_id:
            parts.append(f"| {self.cfg.line_format}")
        if query.levels:
            pattern = "(?i)^(" + "|".join(level_variants(query.levels)) + ")$"
            parts.append(f"| {self.fields.level}=~{quote(pattern)}")
        if query.request_id:
            parts.append(f"| {self.fields.request_id}={quote(query.request_id)}")
        return " ".join(parts)

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = await request(
            self._client, "GET", path, integration=INTEGRATION, policy=self.policy, params=params
        )
        try:
            body = resp.json()
        except ValueError as exc:
            raise IntegrationError(INTEGRATION, "response was not JSON") from exc
        if body.get("status") not in (None, "success"):
            raise IntegrationError(INTEGRATION, f"query failed: {body.get('error', body)}")
        return body

    async def services(self) -> list[str]:
        now = datetime.now(UTC)
        body = await self._get(
            f"/loki/api/v1/label/{self.service_label}/values",
            {"start": _ns(now - timedelta(hours=24)), "end": _ns(now)},
        )
        return sorted(body.get("data") or [])

    async def fetch(self, query: LogQuery) -> list[LogRecord]:
        now = datetime.now(UTC)
        body = await self._get(
            "/loki/api/v1/query_range",
            {
                "query": self.build_query(query),
                "start": _ns(now - query.since),
                "end": _ns(now),
                "limit": query.limit,
                "direction": "backward",
            },
        )
        records = []
        for stream in body.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            service = labels.get(self.service_label, query.service or "unknown")
            for ts_ns, line in stream.get("values", []):
                fallback = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=UTC)
                records.append(parse_line(line, service, self.fields, fallback))
        records.sort(key=lambda r: r.ts)
        return records[-query.limit :]

    async def count(self, service: str, since: timedelta) -> int | None:
        minutes = max(1, int(since.total_seconds() // 60))
        body = await self._get(
            "/loki/api/v1/query",
            {"query": f"sum(count_over_time({self.selector(service)}[{minutes}m]))"},
        )
        result = body.get("data", {}).get("result", [])
        if not result:
            return 0
        return int(float(result[0]["value"][1]))

    async def ping(self) -> None:
        await request(self._client, "GET", "/ready", integration=INTEGRATION, policy=self.policy)

    async def aclose(self) -> None:
        await self._client.aclose()
