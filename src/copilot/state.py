import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

AgentName = Literal["log_agent", "metrics_agent", "code_agent"]
FaultCategory = Literal[
    "latency", "error_rate", "memory_leak", "cpu_saturation", "db_pool_exhaustion",
    "slow_query", "bad_config", "bad_deploy", "dependency_timeout", "unknown",
]


class Alert(BaseModel):
    name: str
    service: str
    severity: str = "page"
    summary: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    starts_at: str = ""


class Evidence(BaseModel):
    source: Literal["logs", "metrics", "code", "runbook"]
    summary: str
    details: dict = Field(default_factory=dict)
    tool_calls: int = 0
    tool_failures: int = 0


class RootCause(BaseModel):
    service: str
    category: FaultCategory
    culprit_commit: str | None = None
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)


class ProposedFix(BaseModel):
    action: Literal["rollback", "restart", "scale", "disable_flag", "none"]
    target: str
    params: dict = Field(default_factory=dict)
    rationale: str = ""


class IncidentState(TypedDict, total=False):
    incident_id: str
    alert: Alert
    plan: list[AgentName]
    evidence: Annotated[list[Evidence], operator.add]
    tokens_used: Annotated[int, operator.add]
    root_cause: RootCause | None
    proposed_fix: ProposedFix | None
    guardrail_violations: list[str]
    approval: Literal["pending", "approved", "rejected", "blocked"]
    reviewer_note: str
    execution_result: str
