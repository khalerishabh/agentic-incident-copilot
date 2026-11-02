import os
from datetime import datetime, timedelta, timezone

import httpx
from fastmcp import FastMCP

REPO = os.getenv("GITHUB_REPO", "")
API = "https://api.github.com"
MAX_PATCH_CHARS = 4000

mcp = FastMCP("github")


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


@mcp.tool
def recent_commits(since_hours: int = 24, path: str = "") -> list[dict]:
    """Commits on the default branch in the last N hours, optionally touching a path."""
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    params = {"since": since, "per_page": 30}
    if path:
        params["path"] = path
    r = httpx.get(f"{API}/repos/{REPO}/commits", params=params, headers=_headers(), timeout=15)
    r.raise_for_status()
    return [
        {
            "sha": c["sha"][:10],
            "message": c["commit"]["message"].splitlines()[0],
            "author": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
        }
        for c in r.json()
    ]


@mcp.tool
def commit_diff(sha: str) -> dict:
    """Files changed by a commit, with truncated patches."""
    r = httpx.get(f"{API}/repos/{REPO}/commits/{sha}", headers=_headers(), timeout=15)
    r.raise_for_status()
    data = r.json()
    return {
        "sha": data["sha"][:10],
        "message": data["commit"]["message"],
        "files": [
            {
                "filename": f["filename"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": (f.get("patch") or "")[:MAX_PATCH_CHARS],
            }
            for f in data.get("files", [])
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "9103")))
