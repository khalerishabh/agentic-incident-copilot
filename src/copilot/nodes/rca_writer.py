from ..state import IncidentState, ProposedFix, RootCause


async def rca_writer(state: IncidentState) -> dict:
    """TODO week 4: query runbook MCP, then LLM with structured output -> RootCause + ProposedFix."""
    alert = state["alert"]
    return {
        "root_cause": RootCause(
            service=alert.service,
            category="unknown",
            explanation="stub: " + " | ".join(e.summary for e in state.get("evidence", [])),
            confidence=0.0,
        ),
        "proposed_fix": ProposedFix(action="restart", target=alert.service, rationale="stub"),
    }
