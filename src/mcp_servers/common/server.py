import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from fastmcp.exceptions import ToolError

from .errors import IntegrationError, InvalidInput

P = ParamSpec("P")
R = TypeVar("R")
log = logging.getLogger("mcp")


def tool_errors(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Turn backend and input failures into MCP tool errors the agent can read and act on,
    instead of crashing the tool call with a stack trace."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except InvalidInput as exc:
            raise ToolError(f"invalid input: {exc}") from exc
        except IntegrationError as exc:
            log.warning("integration failure", extra={"fields": {"error": str(exc)}})
            hint = " (temporary, retry later)" if exc.retryable else ""
            raise ToolError(f"{exc}{hint}") from exc

    return wrapper


def health_payload(name: str, backend: str, error: Exception | None) -> dict[str, Any]:
    if error is None:
        return {"status": "ready", "server": name, "backend": backend}
    return {"status": "unavailable", "server": name, "backend": backend, "error": str(error)}
