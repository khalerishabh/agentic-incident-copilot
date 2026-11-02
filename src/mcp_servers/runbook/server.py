import os
import re
from pathlib import Path

from fastmcp import FastMCP

RUNBOOK_DIR = Path(os.getenv("RUNBOOK_DIR", "./runbooks"))
mcp = FastMCP("runbook")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@mcp.tool
def search_runbooks(query: str, k: int = 3) -> list[dict]:
    """Find runbook sections relevant to a symptom description.
    v0 uses keyword overlap; replace with pgvector embeddings in week 2."""
    q = _tokens(query)
    scored = []
    for path in RUNBOOK_DIR.glob("*.md"):
        text = path.read_text()
        overlap = len(q & _tokens(text))
        if overlap:
            scored.append((overlap, path.stem, text[:1500]))
    scored.sort(reverse=True)
    return [{"runbook": name, "score": s, "content": body} for s, name, body in scored[:k]]


@mcp.tool
def get_runbook(name: str) -> str:
    """Full text of one runbook by name."""
    path = RUNBOOK_DIR / f"{name}.md"
    return path.read_text() if path.exists() else f"no runbook named {name}"


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "9104")))
