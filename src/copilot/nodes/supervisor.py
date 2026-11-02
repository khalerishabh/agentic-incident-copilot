from langgraph.types import Send

from ..state import IncidentState

DEFAULT_PLAN = ["log_agent", "metrics_agent", "code_agent"]


def supervisor(state: IncidentState) -> dict:
    """v0: investigate with every agent. Later: LLM picks agents from the alert, and can
    loop back for a second round when evidence is inconclusive."""
    return {"plan": DEFAULT_PLAN, "approval": "pending"}


def route_to_investigators(state: IncidentState) -> list[Send]:
    return [Send(agent, state) for agent in state["plan"]]
