from ..state import Evidence, IncidentState


async def log_agent(state: IncidentState) -> dict:
    """TODO week 3: ReAct loop over logs MCP tools (error_summary -> search_logs -> trace_request)."""
    alert = state["alert"]
    return {"evidence": [Evidence(source="logs", summary=f"stub: logs not yet read for {alert.service}")]}


async def metrics_agent(state: IncidentState) -> dict:
    """TODO week 3: compare RED + resource metrics across services, find where the anomaly starts."""
    alert = state["alert"]
    return {"evidence": [Evidence(source="metrics", summary=f"stub: metrics not yet read for {alert.service}")]}


async def code_agent(state: IncidentState) -> dict:
    """TODO week 3: list commits since shortly before alert start, inspect suspicious diffs."""
    return {"evidence": [Evidence(source="code", summary="stub: no commits inspected")]}
