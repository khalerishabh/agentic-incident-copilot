"""Index the runbook folder into pgvector.

    python -m mcp_servers.runbook.index

Safe to run repeatedly: only new or changed sections are embedded, and sections of
deleted runbooks are removed. Changing the embedding model rebuilds the index.
"""

import json
import sys

from copilot.config import settings

from ..common.errors import IntegrationError
from ..common.runtime import run
from .factory import build_search
from .store import PgVectorSearch


async def main() -> int:
    search = build_search(settings)
    if not isinstance(search, PgVectorSearch):
        print("integrations.runbooks.backend is 'keyword'; nothing to index.")
        return 0
    try:
        await search.open()
        result = await search.sync()
    except IntegrationError as exc:
        print(f"Indexing failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await search.aclose()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run(main()))
