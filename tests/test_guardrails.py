from copilot.guardrails import check_fix
from copilot.state import ProposedFix


def test_restart_known_service_allowed():
    assert check_fix(ProposedFix(action="restart", target="orders")) == []


def test_unknown_target_blocked():
    assert check_fix(ProposedFix(action="restart", target="prod-db"))


def test_scale_bounds():
    assert check_fix(ProposedFix(action="scale", target="orders", params={"replicas": 50}))
    assert check_fix(ProposedFix(action="scale", target="orders", params={"replicas": 3})) == []


def test_rollback_needs_sha():
    assert check_fix(ProposedFix(action="rollback", target="orders"))
