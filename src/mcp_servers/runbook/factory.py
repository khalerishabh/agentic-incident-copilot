from copilot.config import Settings

from .embeddings import HttpEmbedder
from .search import KeywordSearch, RunbookSearch
from .store import PgVectorSearch


def build_search(settings: Settings) -> RunbookSearch:
    cfg = settings.integrations.runbooks
    if cfg.backend == "keyword":
        return KeywordSearch(cfg.directory, cfg.max_chunk_chars)
    return PgVectorSearch(
        cfg, settings.postgres_url.get_secret_value(), HttpEmbedder(cfg.embeddings)
    )
