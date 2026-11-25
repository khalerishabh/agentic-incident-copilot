import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .chunking import Chunk, load_runbooks

WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by for from has in is it of on or the to was were with what why how "
    "when which this that there".split()
)


def terms(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


@dataclass
class Hit:
    runbook: str
    title: str
    section: str
    content: str
    score: float
    matched_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runbook": self.runbook,
            "title": self.title,
            "section": self.section,
            "score": round(self.score, 4),
            "matched_by": self.matched_by,
            "content": self.content,
        }


class RunbookSearch(Protocol):
    name: str

    async def search(self, query: str, k: int) -> tuple[list[Hit], list[str]]:
        """Hits, best first, plus notes about degraded search (for example no embeddings)."""
        ...

    async def stats(self) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


class KeywordSearch:
    """BM25 over chunks in memory. No database or embedding model needed; good enough for a
    handful of runbooks, and the fallback when vector search is unavailable."""

    name = "keyword"

    def __init__(self, directory: Path, max_chunk_chars: int) -> None:
        self.directory = directory
        self.max_chunk_chars = max_chunk_chars

    def _chunks(self) -> list[Chunk]:
        return load_runbooks(self.directory, self.max_chunk_chars)

    async def search(self, query: str, k: int) -> tuple[list[Hit], list[str]]:
        chunks = self._chunks()
        wanted = set(terms(query))
        if not chunks or not wanted:
            return [], []
        docs = [Counter(terms(c.text)) for c in chunks]
        avg_len = sum(sum(d.values()) for d in docs) / len(docs)
        df = Counter(t for d in docs for t in set(d) if t in wanted)
        k1, b = 1.5, 0.75
        hits = []
        for chunk, doc in zip(chunks, docs, strict=True):
            length = sum(doc.values())
            score = 0.0
            for t in wanted:
                tf = doc.get(t, 0)
                if not tf:
                    continue
                idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
            if score > 0:
                hits.append(
                    Hit(chunk.runbook, chunk.title, chunk.section, chunk.content, score, ["text"])
                )
        hits.sort(key=lambda h: -h.score)
        return hits[:k], []

    async def stats(self) -> dict[str, Any]:
        chunks = self._chunks()
        return {"runbooks": len({c.runbook for c in chunks}), "chunks": len(chunks)}

    async def aclose(self) -> None:
        return None
