from pathlib import Path
from typing import Any

from copilot.config import RunbooksIntegration

from ..common.errors import InvalidInput
from ..common.limits import truncate
from .chunking import NAME
from .search import RunbookSearch

MAX_QUERY_CHARS = 500
MAX_RUNBOOK_CHARS = 20_000


class RunbookTools:
    def __init__(self, search: RunbookSearch, cfg: RunbooksIntegration) -> None:
        self.search_backend = search
        self.cfg = cfg

    def _path(self, name: str) -> Path:
        """Resolve a runbook name to a file inside the runbook folder and nowhere else."""
        if not NAME.match(name) or ".." in name:
            raise InvalidInput(f"invalid runbook name {name!r}")
        root = self.cfg.directory.resolve()
        path = (root / f"{name}.md").resolve()
        if path.parent != root or not path.is_file():
            raise InvalidInput(f"no runbook named {name!r}; call list_runbooks to see them")
        return path

    async def search_runbooks(self, query: str, k: int = 3) -> dict[str, Any]:
        query = query.strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            raise InvalidInput(f"query must be 1-{MAX_QUERY_CHARS} characters")
        k = max(1, min(k, self.cfg.max_results))
        hits, notes = await self.search_backend.search(query, k)
        out: dict[str, Any] = {
            "query": query,
            "backend": self.search_backend.name,
            "results": [h.to_dict() for h in hits],
        }
        if notes:
            out["notes"] = notes
        if not hits:
            out["notes"] = [*notes, "no matching runbook sections"]
        return out

    async def list_runbooks(self) -> list[dict[str, str]]:
        out = []
        for path in sorted(self.cfg.directory.glob("*.md")):
            if not NAME.match(path.stem):
                continue
            first = next(
                (ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()), ""
            )
            out.append({"name": path.stem, "title": first.lstrip("# ").strip() or path.stem})
        return out

    async def get_runbook(self, name: str) -> dict[str, Any]:
        text = self._path(name).read_text(encoding="utf-8")
        return {
            "name": name,
            "content": truncate(text, MAX_RUNBOOK_CHARS),
            "truncated": len(text) > MAX_RUNBOOK_CHARS,
        }
