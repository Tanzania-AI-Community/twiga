import logging
from typing import List
import requests
from langchain_openai import OpenAIEmbeddings
from langchain_together.embeddings import TogetherEmbeddings
from pydantic import SecretStr
from app.config import embedding_settings, EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Simple HTTP client for retrieving embeddings from an Ollama server."""

    def __init__(self, base_url: str, model: str, provider: EmbeddingProvider):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider = provider

    def _endpoint(self) -> str:
        if self.provider == EmbeddingProvider.OLLAMA:
            return f"{self.base_url}/api/embed"

        return f"{self.base_url}/embed"

    def _request_embedding(self, prompt: str) -> List[float]:
        payload = {"model": self.model, "input": prompt}

        try:
            response = requests.post(
                self._endpoint(),
                json=payload,
                timeout=embedding_settings.ollama_embedding_request_timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("Ollama embedding request failed", exc_info=True)
            raise RuntimeError(f"Failed to fetch embedding from Ollama: {exc}")

        data = response.json()
        embedding = data.get("embeddings")
        if embedding is None:
            raise ValueError("Ollama response did not include an 'embedding' field")
        return embedding[0]

    def embed_query(self, text: str) -> List[float]:
        return self._request_embedding(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._request_embedding(text) for text in texts]


def get_embedding_client():
    """Get the appropriate LangChain embedding client."""
    if embedding_settings.embedding_provider == EmbeddingProvider.OPENAI:
        if not embedding_settings.embedding_api_key:
            raise ValueError("OpenAI embeddings require EMBEDDING_API_KEY to be set.")
        return OpenAIEmbeddings(
            api_key=SecretStr(embedding_settings.embedding_api_key.get_secret_value()),
            model=embedding_settings.embedding_model,
        )
    elif embedding_settings.embedding_provider == EmbeddingProvider.TOGETHER:
        if not embedding_settings.embedding_api_key:
            raise ValueError("Together embeddings require EMBEDDING_API_KEY to be set.")
        return TogetherEmbeddings(
            api_key=SecretStr(embedding_settings.embedding_api_key.get_secret_value()),
            model=embedding_settings.embedding_model,
        )
    elif embedding_settings.embedding_provider == EmbeddingProvider.OLLAMA:
        model_name = (
            embedding_settings.ollama_embedding_model
            or embedding_settings.embedding_model
        )
        if not model_name:
            raise ValueError(
                "Ollama embeddings require a model name. Set OLLAMA_EMBEDDING_MODEL, or EMBEDDING_MODEL."
            )

        base_url = embedding_settings.ollama_embedding_url
        if not base_url:
            raise ValueError(
                "Ollama embeddings require OLLAMA_EMBEDDING_URL to be set."
            )

        base_url = base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")]

        return EmbeddingClient(
            base_url=base_url,
            model=model_name,
            provider=embedding_settings.embedding_provider,
        )

    elif embedding_settings.embedding_provider == EmbeddingProvider.MODAL:
        model_name = (
            embedding_settings.modal_embedding_model
            or embedding_settings.embedding_model
        )
        if not model_name:
            raise ValueError(
                "Modal embeddings require a model name. Set MODAL_EMBEDDING_MODEL or EMBEDDING_MODEL."
            )

        base_url = embedding_settings.modal_embedding_url.get_secret_value()
        if not base_url:
            raise ValueError("Modal embeddings require MODAL_EMBEDDING_URL to be set.")

        return EmbeddingClient(
            base_url=base_url,
            model=model_name,
            provider=embedding_settings.embedding_provider,
        )

    else:
        raise ValueError("No valid embedding provider configured")


def get_embedding(text: str) -> List[float]:
    """Get embedding for a single text."""
    client = get_embedding_client()
    return client.embed_query(text)


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Get embeddings for multiple texts."""
    client = get_embedding_client()
    return client.embed_documents(texts)
