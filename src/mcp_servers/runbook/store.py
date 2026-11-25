import logging
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from copilot.config import RunbooksIntegration

from ..common.errors import IntegrationError
from .chunking import load_runbooks
from .embeddings import Embedder
from .search import Hit, terms

log = logging.getLogger("mcp.runbooks")
INTEGRATION = "runbooks/pgvector"
RRF_K = 60
CANDIDATES = 50


class PgVectorSearch:
    """Runbook chunks in Postgres. Search fuses two rankings with reciprocal rank fusion:
    vector similarity (meaning) and full-text match (exact words such as error messages)."""

    name = "pgvector"

    def __init__(self, cfg: RunbooksIntegration, dsn: str, embedder: Embedder) -> None:
        self.cfg = cfg
        self.embedder = embedder
        self.dsn = dsn
        self.chunks = sql.Identifier(f"{cfg.table_prefix}_chunks")
        self.meta = sql.Identifier(f"{cfg.table_prefix}_meta")
        self.pool = AsyncConnectionPool(
            dsn, min_size=1, max_size=4, open=False, configure=self._configure
        )

    @staticmethod
    async def _configure(conn: AsyncConnection) -> None:
        await register_vector_async(conn)

    async def open(self) -> None:
        try:
            async with await AsyncConnection.connect(self.dsn, autocommit=True) as c:
                await c.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await self.pool.open(wait=True, timeout=10)
        except Exception as exc:
            raise IntegrationError(INTEGRATION, f"cannot open database: {exc}") from exc

    async def aclose(self) -> None:
        await self.pool.close()
        await self.embedder.aclose()

    async def ensure_schema(self) -> None:
        """Create tables; if the embedding model or dimensions changed, start the index over,
        because vectors from different models cannot be compared."""
        dims = self.embedder.dimensions
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                sql.SQL("CREATE TABLE IF NOT EXISTS {} (key text PRIMARY KEY, value text)").format(
                    self.meta
                )
            )
            rows = await (
                await conn.execute(sql.SQL("SELECT key, value FROM {}").format(self.meta))
            ).fetchall()
            meta: dict[str, str] = {str(k): str(v) for k, v in rows}
            wanted = {"model": self.embedder.model, "dimensions": str(dims)}
            if meta and meta != wanted:
                log.warning("embedding model changed from %s to %s; rebuilding index", meta, wanted)
                await conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(self.chunks))
            await conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {chunks} (
                        id bigserial PRIMARY KEY,
                        runbook text NOT NULL,
                        chunk_index int NOT NULL,
                        title text NOT NULL,
                        section text NOT NULL,
                        content text NOT NULL,
                        digest text NOT NULL,
                        embedding vector({dims}) NOT NULL,
                        tsv tsvector GENERATED ALWAYS AS (
                            to_tsvector('english', title || ' ' || section || ' ' || content)
                        ) STORED,
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        UNIQUE (runbook, chunk_index)
                    )
                    """
                ).format(chunks=self.chunks, dims=sql.Literal(dims))
            )
            await conn.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw (embedding vector_cosine_ops)"
                ).format(sql.Identifier(f"{self.cfg.table_prefix}_chunks_embedding"), self.chunks)
            )
            await conn.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING gin (tsv)").format(
                    sql.Identifier(f"{self.cfg.table_prefix}_chunks_tsv"), self.chunks
                )
            )
            for key, value in wanted.items():
                await conn.execute(
                    sql.SQL(
                        "INSERT INTO {} (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                    ).format(self.meta),
                    (key, value),
                )

    async def sync(self) -> dict[str, int]:
        """Bring the index in line with the runbook folder. Only new or changed chunks are
        embedded; chunks of deleted runbooks or sections are removed."""
        await self.ensure_schema()
        chunks = load_runbooks(self.cfg.directory, self.cfg.max_chunk_chars)
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    sql.SQL("SELECT runbook, chunk_index, digest FROM {}").format(self.chunks)
                )
            ).fetchall()
        existing = {(r, i): d for r, i, d in rows}
        wanted = {(c.runbook, c.index): c for c in chunks}
        changed = [c for key, c in wanted.items() if existing.get(key) != c.digest]
        stale = [key for key in existing if key not in wanted]

        prefix = self.embedder_document_prefix
        vectors = await self.embedder.embed([prefix + c.text for c in changed]) if changed else []
        async with self.pool.connection() as conn, conn.transaction():
            for runbook, index in stale:
                await conn.execute(
                    sql.SQL("DELETE FROM {} WHERE runbook = %s AND chunk_index = %s").format(
                        self.chunks
                    ),
                    (runbook, index),
                )
            for chunk, vector in zip(changed, vectors, strict=True):
                await conn.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (runbook, chunk_index, title, section, content, digest,
                                        embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT (runbook, chunk_index) DO UPDATE SET
                            title = EXCLUDED.title, section = EXCLUDED.section,
                            content = EXCLUDED.content, digest = EXCLUDED.digest,
                            embedding = EXCLUDED.embedding, updated_at = now()
                        """
                    ).format(self.chunks),
                    (
                        chunk.runbook,
                        chunk.index,
                        chunk.title,
                        chunk.section,
                        chunk.content,
                        chunk.digest,
                        vector,
                    ),
                )
        return {
            "runbooks": len({c.runbook for c in chunks}),
            "chunks": len(chunks),
            "embedded": len(changed),
            "deleted": len(stale),
            "unchanged": len(chunks) - len(changed),
        }

    @property
    def embedder_document_prefix(self) -> str:
        return self.cfg.embeddings.document_prefix

    async def search(self, query: str, k: int) -> tuple[list[Hit], list[str]]:
        notes: list[str] = []
        vector = None
        try:
            vector = (await self.embedder.embed([self.cfg.embeddings.query_prefix + query]))[0]
        except IntegrationError as exc:
            notes.append(f"vector search unavailable, using text match only: {exc}")
        words = terms(query)
        tsquery = " | ".join(dict.fromkeys(words)) if words else None
        if vector is None and tsquery is None:
            return [], notes
        query_sql = sql.SQL(
            """
            WITH v AS (
                SELECT id, row_number() OVER (ORDER BY embedding <=> %(vec)s::vector) AS r
                FROM {chunks}
                WHERE %(vec)s::vector IS NOT NULL
                ORDER BY embedding <=> %(vec)s::vector
                LIMIT %(n)s
            ),
            t AS (
                SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS r
                FROM {chunks}, to_tsquery('english', coalesce(%(tsq)s, '')) q
                WHERE %(tsq)s IS NOT NULL AND tsv @@ q
                ORDER BY ts_rank_cd(tsv, q) DESC
                LIMIT %(n)s
            )
            SELECT c.runbook, c.title, c.section, c.content,
                   coalesce(1.0 / (%(rrf)s + v.r), 0) + coalesce(1.0 / (%(rrf)s + t.r), 0)
                       AS score,
                   v.r IS NOT NULL AS by_vector,
                   t.r IS NOT NULL AS by_text
            FROM {chunks} c
            LEFT JOIN v ON v.id = c.id
            LEFT JOIN t ON t.id = c.id
            WHERE v.id IS NOT NULL OR t.id IS NOT NULL
            ORDER BY score DESC
            LIMIT %(k)s
            """
        ).format(chunks=self.chunks)
        params: dict[str, Any] = {
            "vec": vector,
            "tsq": tsquery,
            "n": CANDIDATES,
            "rrf": RRF_K,
            "k": k,
        }
        try:
            async with self.pool.connection() as conn:
                cur = conn.cursor(row_factory=dict_row)
                await cur.execute(query_sql, params)
                rows = await cur.fetchall()
        except Exception as exc:
            raise IntegrationError(INTEGRATION, f"search failed: {exc}") from exc
        hits = [
            Hit(
                runbook=r["runbook"],
                title=r["title"],
                section=r["section"],
                content=r["content"],
                score=float(r["score"]),
                matched_by=[
                    m for m, ok in (("vector", r["by_vector"]), ("text", r["by_text"])) if ok
                ],
            )
            for r in rows
        ]
        return hits, notes

    async def stats(self) -> dict[str, Any]:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    sql.SQL("SELECT count(*), count(DISTINCT runbook) FROM {}").format(self.chunks)
                )
            ).fetchone()
        chunks, runbooks = row if row else (0, 0)
        return {
            "runbooks": runbooks,
            "chunks": chunks,
            "model": self.embedder.model,
            "dimensions": self.embedder.dimensions,
        }
