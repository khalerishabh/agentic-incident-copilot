from ..guardrails import check_fix
from ..state import IncidentState


async def executor(state: IncidentState) -> dict:
    """The only node allowed to change the system. Re-checks guardrails because state
    could have been edited between interrupt and resume.
    TODO week 4: implement restart/rollback against docker compose in a dry-run-first mode."""
    fix = state["proposed_fix"]
    if violations := check_fix(fix):
        return {"execution_result": f"refused: {violations}"}
    return {"execution_result": f"DRY RUN: would {fix.action} {fix.target} {fix.params}"}
