class IntegrationError(Exception):
    """A backend (Loki, Prometheus, GitHub, ...) failed in a way the agent should be told about."""

    def __init__(self, integration: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{integration}: {message}")
        self.integration = integration
        self.retryable = retryable


class InvalidInput(ValueError):
    """A tool argument was rejected before any backend was called."""
