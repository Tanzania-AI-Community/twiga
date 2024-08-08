from typing import List
import logging

from openai import OpenAI
import chromadb

from app.config import llm_settings
from app.tools.generate_exercise.models import ChunkSchema, Metadata


class ChromaDBLoader:

    def __init__(self):
        self.embedding_client = OpenAI(
            api_key=llm_settings.openai_api_key.get_secret_value(),
            organization=llm_settings.openai_org,
        )
        self.logger = logging.getLogger(__name__)
        self.client = chromadb.PersistentClient(path="db/twiga_vector_store")

        self.logger.info(self.client.heartbeat())
        self.collection = None

        self.logger.info("Connected to Chroma!")

        try:
            self.collection = self.client.get_collection(name="twiga_documents")
        except ValueError as e:
            self.logger.error("Collection doesn't exist, you have to create one.")

    def get_embedding(
        self, text: str, model: str = "text-embedding-3-small"
    ) -> List[float]:
        text = text.replace("\n", " ")
        return (
            self.embedding_client.embeddings.create(input=[text], model=model)
            .data[0]
            .embedding
        )

    def search(self, query: str, n_results: int, where: dict) -> chromadb.QueryResult:
        embedding = self.get_embedding(query)
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas"],
        )


vector_client = ChromaDBLoader()
