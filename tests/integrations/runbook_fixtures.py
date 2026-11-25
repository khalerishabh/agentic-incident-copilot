import hashlib
import math
import re
from pathlib import Path

RUNBOOKS = {
    "db-pool-exhaustion": """# Database connection pool exhaustion

## Symptoms
Requests fail with "QueuePool limit reached" or pool timeout errors. Latency climbs first.

## Remediation
Restart the service to release connections, then find the slow transaction.
""",
    "memory-leak": """# Memory leak

## Symptoms
Resident memory grows steadily under constant traffic until the container is OOM killed.

## Remediation
Restart to reclaim memory, then roll back the commit that introduced the growth.
""",
    "bad-deploy": """# Bad deploy

## Symptoms
Errors start right after a release. Only the new version fails.

## Remediation
Roll back to the previous image tag.
""",
}


def write_runbooks(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in RUNBOOKS.items():
        (directory / f"{name}.md").write_text(text)
    return directory


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder: texts sharing words get similar vectors.
    Lets the real pgvector path be tested without an embedding model."""

    model = "fake-hash"

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []
        self.fail = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from mcp_servers.common.errors import IntegrationError

        if self.fail:
            raise IntegrationError("runbooks/embeddings", "connection failed (ConnectError)")
        self.calls.append(texts)
        out = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for word in re.findall(r"[a-z]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.dimensions] += 1.0 if (h >> 8) % 2 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out

    async def aclose(self) -> None:
        return None
