import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from copilot.config import LogFieldMap

from ..common.limits import truncate

ERROR_LEVELS = ("WARNING", "ERROR", "CRITICAL")
LEVEL_ALIASES = {
    "WARN": "WARNING",
    "ERR": "ERROR",
    "FATAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "PANIC": "CRITICAL",
}
MAX_EXTRA_FIELDS = 10


def normalize_level(value: Any) -> str:
    level = str(value or "INFO").upper()
    return LEVEL_ALIASES.get(level, level)


def level_variants(levels: tuple[str, ...]) -> list[str]:
    """All spellings that map to the requested levels, so filters work across log styles."""
    wanted = {normalize_level(level) for level in levels}
    variants = set(wanted)
    variants |= {alias for alias, canonical in LEVEL_ALIASES.items() if canonical in wanted}
    return sorted(variants)


@dataclass(frozen=True)
class LogQuery:
    since: timedelta
    service: str | None = None
    levels: tuple[str, ...] = ()
    contains: str = ""
    request_id: str | None = None
    limit: int = 50


@dataclass
class LogRecord:
    ts: datetime
    service: str
    level: str
    message: str
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ts": self.ts.isoformat(),
            "service": self.service,
            "level": self.level,
            "msg": self.message,
        }
        if self.request_id:
            out["request_id"] = self.request_id
        out.update(self.extra)
        return out


def parse_line(
    line: str, service: str, fields: LogFieldMap, fallback_ts: datetime | None = None
) -> LogRecord:
    """Turn one raw log line into a LogRecord. Non-JSON lines are kept as plain messages."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        return LogRecord(
            ts=fallback_ts or datetime.now(UTC),
            service=service,
            level="INFO",
            message=truncate(line.strip()),
        )

    ts = fallback_ts
    raw_ts = data.get(fields.timestamp)
    if isinstance(raw_ts, str):
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    if ts is None:
        ts = datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    known = {fields.timestamp, fields.level, fields.message, fields.request_id, "service"}
    extra: dict[str, Any] = {}
    for key, value in data.items():
        if key in known or len(extra) >= MAX_EXTRA_FIELDS:
            continue
        extra[key] = truncate(value, 200) if isinstance(value, str) else value
    rid = data.get(fields.request_id)
    return LogRecord(
        ts=ts,
        service=str(data.get("service") or service),
        level=normalize_level(data.get(fields.level)),
        message=truncate(str(data.get(fields.message, ""))),
        request_id=str(rid) if rid else None,
        extra=extra,
    )


class LogBackend(Protocol):
    name: str

    async def services(self) -> list[str]: ...

    async def fetch(self, query: LogQuery) -> list[LogRecord]:
        """The most recent `query.limit` matching records, oldest first."""
        ...

    async def count(self, service: str, since: timedelta) -> int | None:
        """Total lines for a service in the window, or None if the backend cannot tell."""
        ...

    async def ping(self) -> None: ...

    async def aclose(self) -> None: ...
