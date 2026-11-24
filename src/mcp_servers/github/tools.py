import fnmatch
from datetime import UTC, datetime, timedelta
from typing import Any

from copilot.config import GitHubConfig, ServiceConfig, Settings

from ..common import limits
from ..common.errors import InvalidInput
from .client import GitHubClient

SKIP_PATTERNS = (
    "*.lock",
    "*-lock.json",
    "*.lock.json",
    "*.min.js",
    "*.min.css",
    "*.svg",
    "*.png",
    "*.jpg",
    "*.ico",
    "*.pdf",
    "vendor/*",
    "node_modules/*",
)
MAX_SINCE_HOURS = 24 * 30


def _skipped(filename: str) -> bool:
    name = filename.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(filename, p) for p in SKIP_PATTERNS)


def _touches(filename: str, paths: list[str]) -> bool:
    return any(filename == p or filename.startswith(p.rstrip("/") + "/") for p in paths)


class CodeTools:
    def __init__(self, client: GitHubClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.cfg: GitHubConfig = settings.integrations.code.github

    def _service(self, name: str) -> tuple[ServiceConfig, str]:
        name = limits.service_name(name)
        svc = self.settings.service(name)
        if svc is None:
            raise InvalidInput(
                f"unknown service {name!r}; configured: {sorted(self.settings.service_names)}"
            )
        if not svc.repo:
            raise InvalidInput(f"no repository configured for {name!r}; set services[].repo")
        return svc, svc.repo

    async def service_repos(self) -> list[dict[str, Any]]:
        return [
            {"service": s.name, "repo": s.repo, "branch": s.branch, "paths": s.paths}
            for s in self.settings.services
        ]

    async def recent_commits(self, service: str, since_hours: int = 24) -> dict[str, Any]:
        svc, repo = self._service(service)
        if not 1 <= since_hours <= MAX_SINCE_HOURS:
            raise InvalidInput(f"since_hours must be between 1 and {MAX_SINCE_HOURS}")
        since = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
        commits: dict[str, dict[str, Any]] = {}
        paths: list[str | None] = list(svc.paths) or [None]
        for path in paths:
            params: dict[str, Any] = {"since": since, "per_page": self.cfg.max_commits}
            if path:
                params["path"] = path
            if svc.branch:
                params["sha"] = svc.branch
            for c in await self.client.get(f"/repos/{repo}/commits", f"repository {repo}", params):
                commit = c.get("commit", {})
                author = commit.get("author") or {}
                commits[c["sha"]] = {
                    "sha": c["sha"][:12],
                    "message": limits.truncate(commit.get("message", "").splitlines()[0], 200)
                    if commit.get("message")
                    else "",
                    "author": author.get("name"),
                    "date": author.get("date"),
                    "url": c.get("html_url"),
                }
        ordered = sorted(commits.values(), key=lambda c: c["date"] or "", reverse=True)
        return {
            "service": svc.name,
            "repo": repo,
            "paths": svc.paths,
            "since_hours": since_hours,
            "commits": ordered[: self.cfg.max_commits],
        }

    async def commit_diff(self, service: str, sha: str) -> dict[str, Any]:
        svc, repo = self._service(service)
        sha = limits.commit_sha(sha)
        data = await self.client.get(f"/repos/{repo}/commits/{sha}", f"commit {sha} in {repo}")
        files = data.get("files") or []
        files.sort(
            key=lambda f: (not _touches(f.get("filename", ""), svc.paths), f.get("filename"))
        )
        budget = self.cfg.max_total_patch_chars
        shown: list[dict[str, Any]] = []
        skipped: list[str] = []
        for f in files:
            name = f.get("filename", "")
            if _skipped(name) or len(shown) >= self.cfg.max_files:
                skipped.append(name)
                continue
            patch = f.get("patch")
            limit = min(self.cfg.max_patch_chars, budget)
            entry: dict[str, Any] = {
                "filename": name,
                "status": f.get("status"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
                "in_service_paths": _touches(name, svc.paths),
            }
            if patch is None:
                entry["patch"] = None
                entry["note"] = "no text diff (binary or too large)"
            else:
                entry["patch"] = patch[:limit]
                entry["patch_truncated"] = len(patch) > limit
                budget -= len(entry["patch"])
            shown.append(entry)
        commit = data.get("commit", {})
        author = commit.get("author") or {}
        stats = data.get("stats") or {}
        return {
            "sha": data.get("sha", sha)[:12],
            "repo": repo,
            "message": limits.truncate(commit.get("message", ""), 1000),
            "author": author.get("name"),
            "date": author.get("date"),
            "stats": {
                "additions": stats.get("additions"),
                "deletions": stats.get("deletions"),
                "files_changed": len(files),
            },
            "files": shown,
            "files_not_shown": skipped,
        }
