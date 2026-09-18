from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import EmbeddingProvider, EmbeddingSettings
from app.utils import embedder, google_embedder
from scripts.database.resource_ingestion import validate_book_embeddings


def test_google_settings_and_routing_without_api_key(monkeypatch):
    config = EmbeddingSettings(
        _env_file=None,
        embedding_provider="google",
        embedding_model="gemini-embedding-001",
        embedding_dimensions=1024,
        google_cloud_project="test-project",
    )
    assert config.api_key is None
    monkeypatch.setattr(embedder, "embedding_settings", config)
    factory = MagicMock()
    monkeypatch.setattr(google_embedder, "GoogleEmbeddingClient", factory)
    embedder.get_embedding_client.cache_clear()
    try:
        embedder.get_embedding("teacher query")
        embedder.get_embeddings(["document"])
        factory.assert_called_once_with(
            project="test-project",
            location="global",
            model="gemini-embedding-001",
            dimensions=1024,
        )
        factory.return_value.embed_query.assert_called_once_with("teacher query")
        factory.return_value.embed_documents.assert_called_once_with(["document"])
    finally:
        embedder.get_embedding_client.cache_clear()


def test_ingestion_refuses_legacy_embeddings(monkeypatch):
    from scripts.database import resource_ingestion

    monkeypatch.setattr(
        resource_ingestion,
        "embedding_settings",
        SimpleNamespace(
            provider=EmbeddingProvider.GOOGLE,
            embedder_name="gemini-embedding-001",
            dimensions=1024,
        ),
    )
    payload = {"chunks": [{"embedding": [1.0] * 1024}]}
    with pytest.raises(ValueError, match="do not match"):
        validate_book_embeddings(payload)
    payload["embedding_metadata"] = {
        "provider": "google",
        "model": "gemini-embedding-001",
        "dimensions": 1024,
        "task_type": "RETRIEVAL_DOCUMENT",
        "document_max_bytes": 2048,
    }
    validate_book_embeddings(payload)
    payload["chunks"][0]["embedding"] = [1.0] * 768
    with pytest.raises(ValueError, match="1024"):
        validate_book_embeddings(payload)


def test_existing_openai_and_together_clients_construct_with_google_dependencies():
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_together import ChatTogether, TogetherEmbeddings

    # No requests: catch incompatible HTTP SDK upgrades that mocked factories miss.
    for factory, kwargs in [
        (ChatOpenAI, {}),
        (OpenAIEmbeddings, {}),
        (ChatTogether, {"model": "offline-model"}),
        (TogetherEmbeddings, {"model": "offline-model"}),
    ]:
        assert factory(api_key="offline-test", **kwargs) is not None
