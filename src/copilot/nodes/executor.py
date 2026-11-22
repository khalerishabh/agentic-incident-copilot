from ..config import settings
from ..guardrails import check_fix
from ..state import IncidentState


async def executor(state: IncidentState) -> dict:
    """The only node allowed to change the system. Re-checks guardrails because state
    could have been edited between interrupt and resume."""
    fix = state["proposed_fix"]
    if fix is None:
        return {"execution_result": "refused: no fix in state"}
    if violations := check_fix(fix):
        return {"execution_result": f"refused: {violations}"}
    if settings.guardrails.dry_run:
        return {"execution_result": f"DRY RUN: would {fix.action} {fix.target} {fix.params}"}
    return {"execution_result": "refused: real executors arrive in M4"}
