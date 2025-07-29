from typing import List
from langchain_openai import OpenAIEmbeddings
from langchain_together.embeddings import TogetherEmbeddings
from pydantic import SecretStr
from app.config import llm_settings


def get_embedding_client():
    """Get the appropriate LangChain embedding client."""
    if llm_settings.ai_provider == "openai" and llm_settings.llm_api_key:
        return OpenAIEmbeddings(
            api_key=SecretStr(llm_settings.llm_api_key.get_secret_value()),
            model=llm_settings.embedding_model,
        )
    elif llm_settings.ai_provider == "together" and llm_settings.llm_api_key:
        return TogetherEmbeddings(
            api_key=SecretStr(llm_settings.llm_api_key.get_secret_value()),
            model=llm_settings.embedding_model,
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
