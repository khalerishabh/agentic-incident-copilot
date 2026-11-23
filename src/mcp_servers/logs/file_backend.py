import asyncio
from collections import deque
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from copilot.config import LogFieldMap

from ..common.errors import IntegrationError
from .backend import LogQuery, LogRecord, level_variants, parse_line


class FileLogBackend:
    """Reads <directory>/<service>.log JSON-lines files. Meant for local development only:
    it scans whole files, which does not scale to production log volumes."""

    name = "file"

    def __init__(self, directory: Path, fields: LogFieldMap) -> None:
        self.directory = directory
        self.fields = fields

    def _records(self, service: str, since: timedelta) -> Iterator[LogRecord]:
        path = self.directory / f"{service}.log"
        if not path.exists():
            return
        cutoff = datetime.now(UTC) - since
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = parse_line(line, service, self.fields)
                if record.ts >= cutoff:
                    yield record

    def _matches(self, record: LogRecord, query: LogQuery, levels: set[str]) -> bool:
        if levels and record.level not in levels:
            return False
        if query.request_id and record.request_id != query.request_id:
            return False
        if query.contains:
            haystack = f"{record.message} {record.extra}".lower()
            if query.contains.lower() not in haystack:
                return False
        return True

    def _fetch_sync(self, query: LogQuery) -> list[LogRecord]:
        services = [query.service] if query.service else self._services_sync()
        levels = set(level_variants(query.levels)) if query.levels else set()
        newest: deque[LogRecord] = deque(maxlen=query.limit)
        merged = []
        for service in services:
            merged += [
                r for r in self._records(service, query.since) if self._matches(r, query, levels)
            ]
        merged.sort(key=lambda r: r.ts)
        newest.extend(merged)
        return list(newest)

    def _services_sync(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(p.stem for p in self.directory.glob("*.log"))

    async def services(self) -> list[str]:
        return await asyncio.to_thread(self._services_sync)

    async def fetch(self, query: LogQuery) -> list[LogRecord]:
        return await asyncio.to_thread(self._fetch_sync, query)

    async def count(self, service: str, since: timedelta) -> int | None:
        return await asyncio.to_thread(lambda: sum(1 for _ in self._records(service, since)))

    async def ping(self) -> None:
        if not self.directory.is_dir():
            raise IntegrationError("logs/file", f"directory {self.directory} does not exist")

    async def aclose(self) -> None:
        return None
