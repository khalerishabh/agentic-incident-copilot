from .config import settings


class BudgetExceeded(Exception):
    pass


def remaining(state: dict) -> int:
    return settings.token_budget_per_incident - state.get("tokens_used", 0)


def ensure_budget(state: dict, needed: int = 2_000) -> None:
    if remaining(state) < needed:
        raise BudgetExceeded(f"token budget exhausted ({state.get('tokens_used', 0)} used)")


def tokens_from_response(message) -> int:
    usage = getattr(message, "usage_metadata", None) or {}
    return int(usage.get("total_tokens", 0))
