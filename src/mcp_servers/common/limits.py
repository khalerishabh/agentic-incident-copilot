import re
from datetime import timedelta

from .errors import InvalidInput

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
DURATION = re.compile(r"^(\d{1,5})([smh])$")
SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def truncate(value: str, limit: int = 500) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def service_name(value: str) -> str:
    if not NAME.match(value):
        raise InvalidInput(f"invalid service name {value!r}")
    return value


def request_id(value: str) -> str:
    if not REQUEST_ID.match(value):
        raise InvalidInput(f"invalid request id {value!r}")
    return value


def commit_sha(value: str) -> str:
    if not SHA.match(value):
        raise InvalidInput(f"invalid commit sha {value!r}; expected 7-40 hex characters")
    return value.lower()


def window(minutes: int, max_minutes: int) -> timedelta:
    if not 1 <= minutes <= max_minutes:
        raise InvalidInput(f"since_minutes must be between 1 and {max_minutes}")
    return timedelta(minutes=minutes)


def duration(value: str, max_minutes: int, minimum_seconds: int = 1) -> int:
    """Parse a PromQL-style duration like '5m' into seconds, within bounds."""
    match = DURATION.match(value)
    if not match:
        raise InvalidInput(f"invalid duration {value!r}; use forms like 30s, 5m or 1h")
    seconds = int(match.group(1)) * UNIT_SECONDS[match.group(2)]
    if not minimum_seconds <= seconds <= max_minutes * 60:
        raise InvalidInput(
            f"duration {value!r} must be between {minimum_seconds}s and {max_minutes}m"
        )
    return seconds
