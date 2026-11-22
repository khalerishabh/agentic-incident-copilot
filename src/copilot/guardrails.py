from .config import Settings, settings
from .state import ProposedFix


def check_fix(fix: ProposedFix, cfg: Settings | None = None) -> list[str]:
    """Return a list of violations; empty means the fix may be shown to a human."""
    cfg = cfg or settings
    rules = cfg.guardrails
    violations = []
    if fix.action not in rules.allowed_actions:
        violations.append(f"action '{fix.action}' is not allow-listed")
    if fix.target not in cfg.service_names:
        violations.append(f"target '{fix.target}' is not a configured service")
    if fix.action == "scale":
        replicas = fix.params.get("replicas")
        if not isinstance(replicas, int) or not 1 <= replicas <= rules.max_replicas:
            violations.append(f"replicas must be an int in [1, {rules.max_replicas}]")
    if fix.action == "rollback" and not fix.params.get("to_sha"):
        violations.append("rollback requires params.to_sha")
    return violations
