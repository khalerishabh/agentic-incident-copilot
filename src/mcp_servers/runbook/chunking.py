import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")


@dataclass(frozen=True)
class Chunk:
    runbook: str
    title: str
    section: str
    index: int
    content: str

    @property
    def text(self) -> str:
        """What gets embedded and full-text indexed: the chunk plus where it lives."""
        return f"{self.title}\n{self.section}\n{self.content}"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split on paragraph boundaries, then hard-wrap any paragraph that is still too long."""
    parts: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        while len(para) > max_chars:
            parts.append(para[:max_chars])
            para = para[max_chars:]
        if current and len(current) + len(para) + 2 > max_chars:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def chunk_markdown(runbook: str, text: str, max_chars: int) -> list[Chunk]:
    """One chunk per section, where a section is the text under a heading. The section name
    keeps its parent headings ("Diagnosis > Database"), so a chunk makes sense on its own."""
    title = runbook
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        match = None if in_code else HEADING.match(line)
        if not match:
            sections[-1][1].append(line)
            continue
        level, name = len(match.group(1)), match.group(2)
        if level == 1 and title == runbook:
            title = name
            continue
        stack = [(lvl, n) for lvl, n in stack if lvl < level] + [(level, name)]
        sections.append((" > ".join(n for _, n in stack), []))

    chunks: list[Chunk] = []
    for section, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        for part in _split_long(body, max_chars):
            chunks.append(Chunk(runbook, title, section or "Overview", len(chunks), part))
    return chunks


def load_runbooks(directory: Path, max_chars: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        if NAME.match(path.stem):
            chunks += chunk_markdown(path.stem, path.read_text(encoding="utf-8"), max_chars)
    return chunks
