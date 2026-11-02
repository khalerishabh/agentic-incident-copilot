from .config import settings
from .state import ProposedFix

ALLOWED_ACTIONS = {"rollback", "restart", "scale", "disable_flag"}
MAX_REPLICAS = 5


def check_fix(fix: ProposedFix) -> list[str]:
    """Return a list of violations; empty means the fix may be shown to a human."""
    violations = []
    if fix.action not in ALLOWED_ACTIONS:
        violations.append(f"action '{fix.action}' is not allow-listed")
    if fix.target not in settings.known_services:
        violations.append(f"target '{fix.target}' is not a known service")
    if fix.action == "scale":
        replicas = fix.params.get("replicas")
        if not isinstance(replicas, int) or not 1 <= replicas <= MAX_REPLICAS:
            violations.append(f"replicas must be an int in [1, {MAX_REPLICAS}]")
    if fix.action == "rollback" and not fix.params.get("to_sha"):
        violations.append("rollback requires params.to_sha")
    return violations
