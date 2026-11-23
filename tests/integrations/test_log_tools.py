import json
from datetime import UTC, datetime, timedelta

import pytest

from copilot.config import LogFieldMap, LogsIntegration
from mcp_servers.common.errors import InvalidInput
from mcp_servers.logs.file_backend import FileLogBackend
from mcp_servers.logs.tools import LogTools


def _write(directory, service: str, lines: list[dict]) -> None:
    with (directory / f"{service}.log").open("w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _line(minutes_ago: float, level: str, msg: str, **extra) -> dict:
    ts = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {"ts": ts.isoformat(), "level": level, "msg": msg, **extra}


@pytest.fixture
def tools(tmp_path) -> LogTools:
    _write(
        tmp_path,
        "payments",
        [
            _line(30, "ERROR", "too old"),
            _line(4, "ERROR", "card declined", request_id="r1"),
            _line(3, "ERROR", "card declined", request_id="r2"),
            _line(2, "WARNING", "slow upstream"),
            _line(1, "INFO", "request handled", request_id="r1"),
        ],
    )
    _write(tmp_path, "orders", [_line(4, "INFO", "calling payments", request_id="r1")])
    cfg = LogsIntegration(backend="file", max_lines=3)
    return LogTools(FileLogBackend(tmp_path, LogFieldMap()), cfg)


async def test_error_summary_groups_and_ignores_old_lines(tools):
    out = await tools.error_summary("payments", since_minutes=15)
    assert out["total_lines"] == 4
    assert out["top_issues"][0]["issue"] == "ERROR: card declined"
    assert out["top_issues"][0]["count"] == 2
    assert {i["issue"] for i in out["top_issues"]} == {
        "ERROR: card declined",
        "WARNING: slow upstream",
    }
    assert out["sampled"] is False


async def test_search_respects_cap_and_level(tools):
    assert len(await tools.search_logs("payments", limit=100)) == 3
    warnings = await tools.search_logs("payments", level="warn")
    assert [r["msg"] for r in warnings] == ["slow upstream"]


async def test_trace_follows_request_across_services_in_time_order(tools):
    trace = await tools.trace_request("r1")
    assert [(r["service"], r["msg"]) for r in trace] == [
        ("payments", "card declined"),
        ("orders", "calling payments"),
        ("payments", "request handled"),
    ]


@pytest.mark.parametrize(
    "call",
    [
        lambda t: t.search_logs("../etc/passwd"),
        lambda t: t.search_logs("payments", level="LOUD"),
        lambda t: t.error_summary("payments", since_minutes=0),
        lambda t: t.trace_request("r1; drop"),
    ],
)
async def test_bad_input_is_rejected_before_the_backend(tools, call):
    with pytest.raises(InvalidInput):
        await call(tools)
