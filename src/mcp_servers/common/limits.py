import re
from datetime import timedelta

from .errors import InvalidInput

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


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


def window(minutes: int, max_minutes: int) -> timedelta:
    if not 1 <= minutes <= max_minutes:
        raise InvalidInput(f"since_minutes must be between 1 and {max_minutes}")
    return timedelta(minutes=minutes)
