import app.tools.generate_exercise.vector_database as vector_database
from sentence_transformers import SentenceTransformer
import os
import json

# from src.models import ChunkSchema
from typing import List

# from src.utils import load_json_to_chunkschema
import uuid

"""
I use this class if I want to modify the data I have stored in Elastic Search in some way.
"""


class ChromaDBLoader:

    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.client = vector_database.PersistentClient(path="chroma_db")
        print(self.client.heartbeat())
        self.collection = None
        try:
            self.collection = self.client.get_collection(name="twiga_documents")
        except ValueError as e:
            print("Collection doesn't exist, you have to create it.")

        print("Connected to Chroma!")

    def get_embedding(self, text):
        return self.model.encode(text)

    def create_index(self):
        try:
            self.client.delete_collection(name="twiga_documents")
        except ValueError as e:
            print("No index deletion required, it doesn't exist anyway.")

        # self.client.get_or_create_collection(index='twiga_documents')
        self.collection = self.client.create_collection(
            name="twiga_documents",
            metadata={"hnsw:space": "cosine"},  # l2 is the default
        )

    def search(
        self, query: str, n_results: int, where: dict
    ) -> vector_database.QueryResult:
        embedding = self.get_embedding(query).tolist()
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas"],
        )

    def retrieve_document(self, id: str):
        # This method gets the document associated with a specific ID in the elasticsearch database
        return self.collection.get(ids=[id])


if __name__ == "__main__":

    chromadb_loader = ChromaDBLoader()

    print(
        chromadb_loader.collection.peek()
    )  # returns a list of the first 10 items in the collection
    print(
        chromadb_loader.collection.count()
    )  # returns the number of items in the collection

    # Search for documents
    res = chromadb_loader.search(
        query="Nomadic pastoralism", n_results=2, where={"doc_type": "Exercise"}
    )
    print(res["documents"][0])
