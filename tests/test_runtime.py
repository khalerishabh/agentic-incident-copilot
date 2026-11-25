import asyncio

import mcp_servers.common.runtime as runtime


def test_windows_gets_a_selector_loop_for_psycopg(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    assert runtime.loop_factory() is asyncio.SelectorEventLoop


def test_other_platforms_keep_the_default_loop(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert runtime.loop_factory() is None


def test_run_returns_the_coroutine_result(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")

    async def answer() -> int:
        loop = asyncio.get_running_loop()
        return 42 if isinstance(loop, asyncio.SelectorEventLoop) else 0

    assert runtime.run(answer()) == 42
