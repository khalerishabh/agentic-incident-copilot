import httpx
import pytest

from copilot.config import Settings
from mcp_servers.common.errors import IntegrationError, InvalidInput
from mcp_servers.common.http import RetryPolicy
from mcp_servers.github.client import GitHubClient
from mcp_servers.github.tools import CodeTools


async def _no_sleep(_: float) -> None:
    return None


def _settings(**github) -> Settings:
    return Settings.model_validate(
        {
            "services": [
                {
                    "name": "payments",
                    "repo": "acme/shop",
                    "branch": "main",
                    "paths": ["services/payments", "libs/common"],
                },
                {"name": "orders"},
            ],
            "integrations": {"code": {"github": github}},
        }
    )


def _commit(sha: str, date: str, msg: str = "change") -> dict:
    return {
        "sha": sha,
        "html_url": f"https://github.com/acme/shop/commit/{sha}",
        "commit": {"message": f"{msg}\n\nbody", "author": {"name": "dev", "date": date}},
    }


def _tools(handler, **github) -> CodeTools:
    settings = _settings(**github)
    client = GitHubClient(
        settings.integrations.code.github,
        transport=httpx.MockTransport(handler),
        policy=RetryPolicy(max_attempts=2, sleep=_no_sleep),
    )
    return CodeTools(client, settings)


async def test_recent_commits_queries_each_path_and_dedupes():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.params["path"] == "services/payments":
            return httpx.Response(200, json=[_commit("a" * 40, "2026-11-24T10:00:00Z", "fix")])
        return httpx.Response(
            200,
            json=[
                _commit("a" * 40, "2026-11-24T10:00:00Z", "fix"),
                _commit("b" * 40, "2026-11-24T12:00:00Z", "bump lib"),
            ],
        )

    out = await _tools(handler).recent_commits("payments", since_hours=6)
    assert [c["message"] for c in out["commits"]] == ["bump lib", "fix"]
    assert {r.url.params["sha"] for r in seen} == {"main"}
    assert all(r.url.path == "/repos/acme/shop/commits" for r in seen)


async def test_service_without_repo_explains_the_fix():
    tools = _tools(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(InvalidInput, match=r"set services\[\]\.repo"):
        await tools.recent_commits("orders")
    with pytest.raises(InvalidInput, match="unknown service"):
        await tools.recent_commits("billing")


async def test_commit_diff_puts_service_files_first_and_skips_lock_files():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "sha": "c" * 40,
                "commit": {"message": "add retry", "author": {"name": "dev", "date": "x"}},
                "stats": {"additions": 3, "deletions": 1},
                "files": [
                    {"filename": "README.md", "status": "modified", "patch": "+doc"},
                    {"filename": "poetry.lock", "status": "modified", "patch": "+x"},
                    {
                        "filename": "services/payments/charge.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 1,
                        "patch": "-old\n+new",
                    },
                    {"filename": "logo.png", "status": "added"},
                ],
            },
        )

    out = await _tools(handler).commit_diff("payments", "CCCCCCC")
    assert out["files"][0]["filename"] == "services/payments/charge.py"
    assert out["files"][0]["in_service_paths"] is True
    assert "poetry.lock" in out["files_not_shown"]
    assert "logo.png" in out["files_not_shown"]
    assert out["stats"]["files_changed"] == 4


async def test_patches_respect_per_file_and_total_budgets():
    big = "+" + "x" * 5000

    def handler(req: httpx.Request) -> httpx.Response:
        files = [{"filename": f"services/payments/f{i}.py", "patch": big} for i in range(5)]
        return httpx.Response(200, json={"sha": "d" * 40, "commit": {}, "files": files})

    tools = _tools(handler, max_patch_chars=1000, max_total_patch_chars=2500)
    out = await tools.commit_diff("payments", "d" * 12)
    sizes = [len(f["patch"]) for f in out["files"]]
    assert sizes == [1000, 1000, 500, 0, 0]
    assert all(f["patch_truncated"] for f in out["files"])


async def test_rate_limit_is_retryable_with_reset_time():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1795600000"}
        )

    with pytest.raises(IntegrationError, match="rate limited until 2026") as info:
        await _tools(handler).recent_commits("payments")
    assert info.value.retryable is True


async def test_missing_commit_says_not_found():
    tools = _tools(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(IntegrationError, match="not found"):
        await tools.commit_diff("payments", "abcdef1")


async def test_bad_sha_is_rejected_before_calling_github():
    calls: list[httpx.Request] = []
    tools = _tools(lambda r: calls.append(r) or httpx.Response(200, json={}))
    with pytest.raises(InvalidInput):
        await tools.commit_diff("payments", "../../etc")
    assert calls == []


def test_token_from_config_or_env_is_sent(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert GitHubClient(_settings().integrations.code.github).authenticated
    monkeypatch.delenv("GITHUB_TOKEN")
    assert not GitHubClient(_settings().integrations.code.github).authenticated
    assert GitHubClient(_settings(token="cfg").integrations.code.github).authenticated
