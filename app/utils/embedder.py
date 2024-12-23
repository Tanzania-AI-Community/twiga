from typing import List
from app.config import llm_settings
from together import Together
from openai import OpenAI

if llm_settings.llm_api_key:
    client = (
        OpenAI(api_key=llm_settings.llm_api_key.get_secret_value())
        if llm_settings.ai_provider == "openai"
        else Together(api_key=llm_settings.llm_api_key.get_secret_value())
    )


def get_embedding(text: str) -> List[float]:
    assert client
    response = client.embeddings.create(
        model=llm_settings.embedding_model,
        input=text,
    )
    assert response.data
    embedding = response.data[0].embedding

    if embedding is None:
        raise ValueError("Failed to generate embedding")

    return embedding


def get_embeddings(texts: List[str]) -> List[List[float]]:
    assert client
    response = client.embeddings.create(
        model=llm_settings.embedding_model,
        input=texts,
    )
    assert response.data
    embeddings = []
    for i, embedding_data in enumerate(response.data):
        if embedding_data.embedding is None:
            raise ValueError(f"Failed to generate embedding for text at index {i}")
        embeddings.append(embedding_data.embedding)
    return embeddings
