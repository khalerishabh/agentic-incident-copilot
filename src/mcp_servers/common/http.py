import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .errors import IntegrationError

RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 4.0
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, compare=False)

    def delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        backoff = self.base_delay * 2 ** (attempt - 1)
        return min(backoff, self.max_delay) * random.uniform(0.5, 1.0)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _short(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    integration: str,
    policy: RetryPolicy,
    accept_status: frozenset[int] = frozenset(),
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying timeouts, connection errors, 429 and 5xx gateway errors.
    Other 4xx responses are caller mistakes and fail immediately, unless listed in
    accept_status, in which case they are returned for the caller to interpret."""
    last_problem = "no attempt made"
    for attempt in range(1, policy.max_attempts + 1):
        retry_after = None
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            last_problem = "timed out"
        except httpx.TransportError as exc:
            last_problem = f"connection failed ({type(exc).__name__})"
        else:
            if resp.status_code < 400 or resp.status_code in accept_status:
                return resp
            if resp.status_code not in RETRYABLE_STATUS:
                raise IntegrationError(integration, f"HTTP {resp.status_code}: {_short(resp.text)}")
            last_problem = f"HTTP {resp.status_code}"
            retry_after = _retry_after(resp)
        if attempt < policy.max_attempts:
            await policy.sleep(policy.delay(attempt, retry_after))
    raise IntegrationError(
        integration,
        f"unavailable after {policy.max_attempts} attempts ({last_problem})",
        retryable=True,
    )
