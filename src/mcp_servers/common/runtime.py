import asyncio
import os
import sys
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any, TypeVar

import anyio
from fastmcp import FastMCP

from copilot.telemetry import setup_logging

T = TypeVar("T")


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """Windows defaults to the Proactor event loop, which psycopg's async driver cannot use.
    Everywhere else the default loop is fine."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None


def run(main: Coroutine[Any, Any, T]) -> T:
    with asyncio.Runner(loop_factory=loop_factory()) as runner:
        return runner.run(main)


def serve(mcp: FastMCP, default_port: int) -> None:
    """Start an MCP server over streamable HTTP on an event loop that works on every OS."""
    setup_logging()
    factory = loop_factory()
    anyio.run(
        partial(
            mcp.run_async,
            transport="http",
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", str(default_port))),
            show_banner=False,
        ),
        backend_options={"loop_factory": factory} if factory else {},
    )
