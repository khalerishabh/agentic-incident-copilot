from langgraph.graph import END
from langgraph.types import interrupt

from ..guardrails import check_fix
from ..state import IncidentState


def approval_gate(state: IncidentState) -> dict:
    fix = state.get("proposed_fix")
    if fix is None or fix.action == "none":
        return {"approval": "rejected", "reviewer_note": "no actionable fix proposed"}

    violations = check_fix(fix)
    if violations:
        return {"approval": "blocked", "guardrail_violations": violations}

    root_cause = state.get("root_cause")
    decision = interrupt(
        {
            "incident_id": state["incident_id"],
            "root_cause": root_cause.model_dump() if root_cause else None,
            "proposed_fix": fix.model_dump(),
        }
    )
    approved = bool(decision.get("approved"))
    return {
        "approval": "approved" if approved else "rejected",
        "reviewer_note": decision.get("note", ""),
    }


def after_approval(state: IncidentState) -> str:
    return "executor" if state.get("approval") == "approved" else END
