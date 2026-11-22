import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram

incident_id_var: ContextVar[str | None] = ContextVar("incident_id", default=None)

INCIDENTS = Counter("copilot_incidents_total", "Incidents opened", ["alertname"])
INCIDENTS_ACTIVE = Gauge("copilot_incidents_active", "Incidents currently being investigated")
INCIDENT_ERRORS = Counter("copilot_incident_errors_total", "Incident runs that raised", ["stage"])
INVESTIGATION_SECONDS = Histogram(
    "copilot_investigation_seconds",
    "Alert received to fix proposed",
    buckets=(5, 15, 30, 60, 120, 300, 600),
)
APPROVALS = Counter("copilot_approvals_total", "Human decisions", ["outcome"])
TOOL_CALL_FAILURES = Counter(
    "copilot_tool_call_failures_total", "Failed MCP tool calls", ["server"]
)
TOKENS_USED = Counter("copilot_tokens_used_total", "LLM tokens consumed", ["agent"])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if incident_id := incident_id_var.get():
            payload["incident_id"] = incident_id
        for key, value in getattr(record, "fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True
