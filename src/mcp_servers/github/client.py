import os
from datetime import UTC, datetime
from typing import Any

import httpx

from copilot.config import GitHubConfig

from ..common.errors import IntegrationError
from ..common.http import RetryPolicy, request

INTEGRATION = "code/github"
HANDLED_STATUS = frozenset({401, 403, 404, 409, 422})


def _reset_time(resp: httpx.Response) -> str:
    reset = resp.headers.get("x-ratelimit-reset")
    if not reset or not reset.isdigit():
        return "later"
    return datetime.fromtimestamp(int(reset), tz=UTC).isoformat()


class GitHubClient:
    """REST v3 client. api_url can point at GitHub Enterprise Server (https://host/api/v3)."""

    name = "github"

    def __init__(
        self,
        cfg: GitHubConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.cfg = cfg
        self.policy = policy or RetryPolicy(max_attempts=cfg.max_attempts)
        token = cfg.token.get_secret_value() if cfg.token else os.getenv("GITHUB_TOKEN")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "incident-copilot",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.authenticated = bool(token)
        self._client = httpx.AsyncClient(
            base_url=cfg.api_url.rstrip("/"),
            timeout=cfg.timeout_seconds,
            headers=headers,
            transport=transport,
        )

    def _raise_for(self, resp: httpx.Response, what: str) -> None:
        status = resp.status_code
        if status == 401:
            raise IntegrationError(INTEGRATION, "authentication failed; check the GitHub token")
        if status == 403:
            if resp.headers.get("x-ratelimit-remaining") == "0":
                hint = "" if self.authenticated else " (unauthenticated: set a GitHub token)"
                raise IntegrationError(
                    INTEGRATION,
                    f"rate limited until {_reset_time(resp)}{hint}",
                    retryable=True,
                )
            raise IntegrationError(INTEGRATION, f"access denied to {what}; check token scopes")
        if status == 404:
            raise IntegrationError(
                INTEGRATION, f"{what} not found (or the token cannot see a private repo)"
            )
        if status == 409:
            raise IntegrationError(INTEGRATION, f"{what} is empty")
        if status == 422:
            message = resp.json().get("message", "unprocessable") if resp.content else ""
            raise IntegrationError(INTEGRATION, f"{what}: {message}")

    async def get(self, path: str, what: str, params: dict[str, Any] | None = None) -> Any:
        resp = await request(
            self._client,
            "GET",
            path,
            integration=INTEGRATION,
            policy=self.policy,
            accept_status=HANDLED_STATUS,
            params=params or {},
        )
        self._raise_for(resp, what)
        return resp.json()

    async def ping(self) -> dict[str, Any]:
        """Uses /rate_limit, which does not count against the rate limit."""
        body = await self.get("/rate_limit", "rate limit endpoint")
        core = body.get("resources", {}).get("core", {})
        return {"authenticated": self.authenticated, "remaining": core.get("remaining")}

    async def aclose(self) -> None:
        await self._client.aclose()
