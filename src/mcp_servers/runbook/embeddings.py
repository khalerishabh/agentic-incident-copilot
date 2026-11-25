import os
from typing import Any, Protocol

import httpx

from copilot.config import EmbeddingConfig

from ..common.errors import IntegrationError
from ..common.http import RetryPolicy, request

INTEGRATION = "runbooks/embeddings"


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def aclose(self) -> None: ...


class HttpEmbedder:
    """Ollama (/api/embed) or any OpenAI-compatible /embeddings endpoint, batched."""

    def __init__(
        self,
        cfg: EmbeddingConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.cfg = cfg
        self.model = cfg.model
        self.dimensions = cfg.dimensions
        self.policy = policy or RetryPolicy(max_attempts=cfg.max_attempts)
        headers: dict[str, str] = {}
        if cfg.provider == "openai":
            base = cfg.base_url or "https://api.openai.com/v1"
            key = cfg.api_key.get_secret_value() if cfg.api_key else os.getenv("OPENAI_API_KEY")
            if key:
                headers["Authorization"] = f"Bearer {key}"
        else:
            base = cfg.base_url or "http://localhost:11434"
        self._client = httpx.AsyncClient(
            base_url=base.rstrip("/"),
            timeout=cfg.timeout_seconds,
            headers=headers,
            transport=transport,
        )

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {"model": self.model, "input": texts}
        if self.cfg.provider == "openai":
            resp = await request(
                self._client,
                "POST",
                "/embeddings",
                integration=INTEGRATION,
                policy=self.policy,
                json=body,
            )
            data = resp.json().get("data", [])
            vectors = [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]
        else:
            resp = await request(
                self._client,
                "POST",
                "/api/embed",
                integration=INTEGRATION,
                policy=self.policy,
                json=body,
            )
            vectors = resp.json().get("embeddings", [])
        if len(vectors) != len(texts):
            raise IntegrationError(
                INTEGRATION, f"asked for {len(texts)} embeddings, got {len(vectors)}"
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise IntegrationError(
                    INTEGRATION,
                    f"{self.model} returned {len(vector)} dimensions but config says "
                    f"{self.dimensions}; set integrations.runbooks.embeddings.dimensions",
                )
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        size = self.cfg.batch_size
        for start in range(0, len(texts), size):
            out += await self._batch(texts[start : start + size])
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
