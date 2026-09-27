"""Vertex AI embeddings, shared by retrieval and the re-embedding scripts."""

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONS = 1024
DOCUMENT_MAX_BYTES = 2048


def validate_embedding(values: list[float], dimensions: int) -> list[float]:
    if len(values) != dimensions or not all(math.isfinite(v) for v in values):
        raise ValueError(f"Expected {dimensions} finite embedding values.")
    if not any(values):
        raise ValueError("Embedding must not be a zero vector.")
    return values


class GoogleEmbeddingClient:
    provider = "google"
    document_max_bytes = DOCUMENT_MAX_BYTES

    def __init__(
        self,
        project: str,
        location: str = "global",
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        timeout_seconds: int = 60,
        max_workers: int = 4,
    ):
        if not project or not project.strip():
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT is required for Vertex AI embeddings."
            )
        if dimensions != DEFAULT_DIMENSIONS:
            raise ValueError("Twiga's database requires EMBEDDING_DIMENSIONS=1024.")
        if max_workers < 1 or timeout_seconds < 1:
            raise ValueError("Embedding workers and timeout must be positive.")
        self.model = model
        self.dimensions = dimensions
        self.max_workers = max_workers
        # Explicit Vertex configuration avoids changing the Google chat provider.
        # Credentials are resolved via ADC, never via EMBEDDING_API_KEY.
        self.client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(
                api_version="v1",
                timeout=timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(
                    attempts=5,
                    initial_delay=1,
                    max_delay=20,
                    http_status_codes=[429, 500, 502, 503, 504],
                ),
            ),
        )

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise ValueError("Cannot embed empty text.")
        response = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self.dimensions,
                auto_truncate=False,
            ),
        )
        if not response.embeddings or len(response.embeddings) != len(texts):
            raise ValueError("Google must return exactly one embedding per input.")
        vectors = []
        for embedding in response.embeddings:
            if embedding.statistics and embedding.statistics.truncated:
                raise ValueError("Google truncated the embedding input.")
            vectors.append(validate_embedding(embedding.values or [], self.dimensions))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        # Small batches bound request size; map preserves order across concurrent calls.
        # Verified against gemini-embedding-001 on Vertex's global endpoint.
        # Preserve stored content; only the document embedding input is bounded.
        # UTF-8 bytes are a conservative bound, unlike a different model's tokenizer.
        prepared = [
            text.encode("utf-8")[: self.document_max_bytes].decode(
                "utf-8", errors="ignore"
            )
            for text in texts
        ]
        batches = [prepared[start : start + 8] for start in range(0, len(prepared), 8)]
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = executor.map(self._embed_documents_batch, batches)
            return [vector for batch in results for vector in batch]

    def _embed_documents_batch(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def close(self) -> None:
        self.client.close()
