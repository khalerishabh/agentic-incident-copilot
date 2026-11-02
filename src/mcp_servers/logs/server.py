import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP

LOG_DIR = Path(os.getenv("LOG_DIR", "./data/logs"))
MAX_LINES_RETURNED = 50

mcp = FastMCP("logs")


def _read(service: str, since_minutes: int):
    path = LOG_DIR / f"{service}.log"
    if not path.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    with path.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if datetime.fromisoformat(rec["ts"]) >= cutoff:
                yield rec


@mcp.tool
def list_services() -> list[str]:
    """List services that have log files."""
    return sorted(p.stem for p in LOG_DIR.glob("*.log"))


@mcp.tool
def error_summary(service: str, since_minutes: int = 15) -> dict:
    """Group WARNING/ERROR log lines for a service by message and return counts.
    Use this first; it is far cheaper than reading raw lines."""
    counts: Counter = Counter()
    first_seen: dict[str, str] = {}
    total = 0
    for rec in _read(service, since_minutes):
        total += 1
        if rec["level"] in ("WARNING", "ERROR", "CRITICAL"):
            key = f'{rec["level"]}: {rec["msg"]}'
            counts[key] += 1
            first_seen.setdefault(key, rec["ts"])
    return {
        "service": service,
        "window_minutes": since_minutes,
        "total_lines": total,
        "top_issues": [
            {"issue": k, "count": c, "first_seen": first_seen[k]} for k, c in counts.most_common(10)
        ],
    }


@mcp.tool
def search_logs(service: str, contains: str = "", level: str = "", since_minutes: int = 15,
                limit: int = 20) -> list[dict]:
    """Return the most recent matching log lines for a service (capped)."""
    limit = min(limit, MAX_LINES_RETURNED)
    hits = [
        r for r in _read(service, since_minutes)
        if (not level or r["level"] == level.upper()) and contains.lower() in json.dumps(r).lower()
    ]
    return hits[-limit:]


@mcp.tool
def trace_request(request_id: str, since_minutes: int = 30) -> list[dict]:
    """Follow one request id across every service, ordered by time."""
    lines = []
    for service in list_services():
        lines += [r for r in _read(service, since_minutes) if r.get("request_id") == request_id]
    return sorted(lines, key=lambda r: r["ts"])[:MAX_LINES_RETURNED]


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "9101")))
