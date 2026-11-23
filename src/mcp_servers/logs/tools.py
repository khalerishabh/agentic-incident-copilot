from collections import Counter
from typing import Any

from copilot.config import LogsIntegration

from ..common import limits
from ..common.errors import InvalidInput
from .backend import ERROR_LEVELS, LogBackend, LogQuery, normalize_level

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
TOP_ISSUES = 10


class LogTools:
    """The logic behind each logs MCP tool, independent of transport so it can be tested."""

    def __init__(self, backend: LogBackend, cfg: LogsIntegration) -> None:
        self.backend = backend
        self.cfg = cfg

    async def list_services(self) -> list[str]:
        return await self.backend.services()

    async def error_summary(self, service: str, since_minutes: int = 15) -> dict[str, Any]:
        service = limits.service_name(service)
        since = limits.window(since_minutes, self.cfg.max_window_minutes)
        records = await self.backend.fetch(
            LogQuery(
                since=since, service=service, levels=ERROR_LEVELS, limit=self.cfg.max_scan_lines
            )
        )
        total = await self.backend.count(service, since)
        counts: Counter[str] = Counter()
        first_seen: dict[str, str] = {}
        last_seen: dict[str, str] = {}
        for record in records:
            key = f"{record.level}: {record.message}"
            counts[key] += 1
            first_seen.setdefault(key, record.ts.isoformat())
            last_seen[key] = record.ts.isoformat()
        return {
            "service": service,
            "window_minutes": since_minutes,
            "total_lines": total,
            "problem_lines": len(records),
            "sampled": len(records) >= self.cfg.max_scan_lines,
            "top_issues": [
                {
                    "issue": key,
                    "count": count,
                    "first_seen": first_seen[key],
                    "last_seen": last_seen[key],
                }
                for key, count in counts.most_common(TOP_ISSUES)
            ],
        }

    async def search_logs(
        self,
        service: str,
        contains: str = "",
        level: str = "",
        since_minutes: int = 15,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        service = limits.service_name(service)
        since = limits.window(since_minutes, self.cfg.max_window_minutes)
        levels: tuple[str, ...] = ()
        if level:
            canonical = normalize_level(level)
            if canonical not in VALID_LEVELS:
                raise InvalidInput(f"level must be one of {sorted(VALID_LEVELS)}")
            levels = (canonical,)
        if len(contains) > 200:
            raise InvalidInput("contains must be at most 200 characters")
        records = await self.backend.fetch(
            LogQuery(
                since=since,
                service=service,
                levels=levels,
                contains=contains,
                limit=max(1, min(limit, self.cfg.max_lines)),
            )
        )
        return [r.to_dict() for r in records]

    async def trace_request(self, request_id: str, since_minutes: int = 30) -> list[dict[str, Any]]:
        request_id = limits.request_id(request_id)
        since = limits.window(since_minutes, self.cfg.max_window_minutes)
        records = await self.backend.fetch(
            LogQuery(since=since, request_id=request_id, limit=self.cfg.max_lines)
        )
        return [r.to_dict() for r in records]
