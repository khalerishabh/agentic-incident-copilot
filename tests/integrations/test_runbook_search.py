import os
import uuid

import httpx
import pytest

from copilot.config import EmbeddingConfig, RunbooksIntegration
from mcp_servers.common.errors import IntegrationError, InvalidInput
from mcp_servers.common.http import RetryPolicy
from mcp_servers.runbook.embeddings import HttpEmbedder
from mcp_servers.runbook.search import KeywordSearch
from mcp_servers.runbook.store import PgVectorSearch
from mcp_servers.runbook.tools import RunbookTools

from .runbook_fixtures import FakeEmbedder, write_runbooks

PG_URL = os.getenv("COPILOT_TEST_POSTGRES_URL")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set COPILOT_TEST_POSTGRES_URL to run")


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def folder(tmp_path):
    return write_runbooks(tmp_path / "runbooks")


async def test_keyword_search_finds_exact_error_text(folder):
    search = KeywordSearch(folder, 1500)
    hits, notes = await search.search("QueuePool limit reached", 3)
    assert hits[0].runbook == "db-pool-exhaustion"
    assert hits[0].section == "Symptoms"
    assert notes == []


async def test_tools_validate_runbook_names(folder):
    tools = RunbookTools(KeywordSearch(folder, 1500), RunbooksIntegration(directory=folder))
    assert (await tools.get_runbook("memory-leak"))["content"].startswith("# Memory leak")
    for bad in ["../../etc/passwd", "memory-leak/../x", "missing", ".hidden"]:
        with pytest.raises(InvalidInput):
            await tools.get_runbook(bad)
    names = [r["name"] for r in await tools.list_runbooks()]
    assert names == ["bad-deploy", "db-pool-exhaustion", "memory-leak"]


async def test_tools_reject_empty_and_huge_queries(folder):
    tools = RunbookTools(KeywordSearch(folder, 1500), RunbooksIntegration(directory=folder))
    for query in ["", "   ", "x" * 501]:
        with pytest.raises(InvalidInput):
            await tools.search_runbooks(query)


def _embedder(handler, **cfg) -> HttpEmbedder:
    return HttpEmbedder(
        EmbeddingConfig(**cfg),
        transport=httpx.MockTransport(handler),
        policy=RetryPolicy(max_attempts=1, sleep=_no_sleep),
    )


async def test_ollama_embedder_batches_requests():
    batches = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(req.content)
        batches.append(len(body["input"]))
        assert req.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.1] * 8 for _ in body["input"]]})

    emb = _embedder(handler, dimensions=8, batch_size=2)
    vectors = await emb.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert batches == [2, 1]


async def test_openai_embedder_orders_by_index_and_sends_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/embeddings"
        assert req.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [2.0] * 8},
                    {"index": 0, "embedding": [1.0] * 8},
                ]
            },
        )

    emb = _embedder(handler, provider="openai", model="text-embedding-3-small", dimensions=8)
    assert await emb.embed(["first", "second"]) == [[1.0] * 8, [2.0] * 8]


async def test_dimension_mismatch_explains_the_config_fix():
    emb = _embedder(lambda r: httpx.Response(200, json={"embeddings": [[0.1] * 3]}), dimensions=768)
    with pytest.raises(IntegrationError, match="returned 3 dimensions but config says 768"):
        await emb.embed(["x"])


@pytest.fixture
async def pg(folder):
    prefix = f"t_{uuid.uuid4().hex[:8]}"
    cfg = RunbooksIntegration(directory=folder, table_prefix=prefix)
    embedder = FakeEmbedder()
    store = PgVectorSearch(cfg, PG_URL or "", embedder)
    await store.open()
    yield store, embedder, folder
    async with store.pool.connection() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {prefix}_chunks, {prefix}_meta")
    await store.aclose()


@needs_pg
async def test_sync_is_incremental(pg):
    store, embedder, folder = pg
    first = await store.sync()
    assert first == {"runbooks": 3, "chunks": 6, "embedded": 6, "deleted": 0, "unchanged": 0}

    again = await store.sync()
    assert again["embedded"] == 0 and again["unchanged"] == 6

    (folder / "bad-deploy.md").unlink()
    path = folder / "memory-leak.md"
    path.write_text(path.read_text().replace("OOM killed", "killed by the OOM killer"))
    third = await store.sync()
    assert third == {"runbooks": 2, "chunks": 4, "embedded": 1, "deleted": 2, "unchanged": 3}
    assert (await store.stats())["chunks"] == 4


@needs_pg
async def test_hybrid_search_ranks_the_right_runbook(pg):
    store, _, _ = pg
    await store.sync()
    hits, notes = await store.search("QueuePool limit reached in orders", 3)
    assert notes == []
    assert hits[0].runbook == "db-pool-exhaustion"
    assert set(hits[0].matched_by) == {"vector", "text"}

    hits, _ = await store.search("memory keeps growing until OOM", 3)
    assert hits[0].runbook == "memory-leak"


@needs_pg
async def test_search_falls_back_to_text_when_embeddings_are_down(pg):
    store, embedder, _ = pg
    await store.sync()
    embedder.fail = True
    hits, notes = await store.search("roll back previous image tag", 3)
    assert hits[0].runbook == "bad-deploy"
    assert hits[0].matched_by == ["text"]
    assert "vector search unavailable" in notes[0]


@needs_pg
async def test_changing_the_model_rebuilds_the_index(pg):
    store, embedder, _ = pg
    await store.sync()
    embedder.model = "another-model"
    embedder.dimensions = 32
    result = await store.sync()
    assert result["embedded"] == 6
    assert (await store.stats())["dimensions"] == 32
