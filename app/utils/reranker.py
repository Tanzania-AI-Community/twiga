"""Second-stage reranking for search_knowledge: score query-chunk pairs, keep the best."""

import asyncio
import logging
from typing import Protocol, Sequence

import google.auth
import httpx
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

TOGETHER_RERANK_URL = "https://api.together.xyz/v1/rerank"
VERTEX_RANK_URL = (
    "https://discoveryengine.googleapis.com/v1/projects/{project}/locations/global"
    "/rankingConfigs/default_ranking_config:rank"
)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class Reranker(Protocol):
    async def rank(self, query: str, documents: Sequence[str]) -> list[int]:
        """Return document indices, most relevant first."""
        ...


class TogetherReranker:
    def __init__(self, api_key: str, model: str, timeout_seconds: float):
        if not api_key:
            raise ValueError("LLM_API_KEY is required for Together reranking.")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def rank(self, query: str, documents: Sequence[str]) -> list[int]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                TOGETHER_RERANK_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "query": query,
                    "documents": list(documents),
                    "top_n": len(documents),
                },
            )
            response.raise_for_status()
        results = response.json()["results"]
        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        return [r["index"] for r in results]


class VertexReranker:
    def __init__(self, project: str, model: str, timeout_seconds: float):
        if not project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Vertex reranking.")
        self.project = project
        self.model = model
        self.timeout_seconds = timeout_seconds
        # Credentials are resolved via ADC, like the Vertex embedder.
        self._credentials = None

    def _access_token(self) -> str:
        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=GOOGLE_SCOPES)
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials.token

    async def rank(self, query: str, documents: Sequence[str]) -> list[int]:
        token = await asyncio.to_thread(self._access_token)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                VERTEX_RANK_URL.format(project=self.project),
                headers={
                    "Authorization": f"Bearer {token}",
                    "x-goog-user-project": self.project,
                },
                json={
                    "model": self.model,
                    "query": query,
                    "records": [
                        {"id": str(i), "content": doc}
                        for i, doc in enumerate(documents)
                    ],
                    "topN": len(documents),
                },
            )
            response.raise_for_status()
        # Vertex returns records sorted by score, highest first.
        return [int(record["id"]) for record in response.json()["records"]]


def get_reranker(
    provider: str,
    model: str,
    timeout_seconds: float,
    api_key: str | None = None,
    project: str | None = None,
) -> Reranker:
    if provider == "vertex":
        return VertexReranker(project or "", model, timeout_seconds)
    if provider == "together":
        return TogetherReranker(api_key or "", model, timeout_seconds)
    raise ValueError(f"Unsupported rerank provider: {provider}")
