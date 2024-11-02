# This is in scripts/database for now but will be moved to app/database
from typing import List
from app.config import settings, llm_settings
from together import Together
from together.types import EmbeddingResponse

client = Together(
    api_key=llm_settings.together_api_key.get_secret_value(),
)


def get_embedding(text: str) -> List[float]:
    response = client.embeddings.create(
        model=llm_settings.embedding_model,
        input=text,
    )
    return response.data[0].embedding


def get_embeddings(texts: List[str]) -> List[List[float]]:
    response = client.embeddings.create(
        model=llm_settings.embedding_model,
        input=texts,
    )
    return [embedding.embedding for embedding in response.data]
