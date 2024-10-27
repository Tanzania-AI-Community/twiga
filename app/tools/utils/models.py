from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# Define a ChatMessage type
class ChatMessage(BaseModel):
    content: str
    role: Literal["system", "user", "assistant"]


class RewrittenQuery(BaseModel):
    rewritten_query_str: str
    embedding: List[float]

    def to_dict(self):
        return {
            "rewritten_query_str": self.rewritten_query_str,
            "embedding": self.embedding,
        }


class EvalQuery(BaseModel):
    query: str = Field(
        ...,
        description="The query provided by the Tanzanian teacher asking the model to generate an exercise/question.",
    )
    requested_exercise_format: Literal["short-answer", "long-answer", "true-false"] = (
        Field(
            ..., description="The type of question or exercise that is being requested."
        )
    )
    topic: str
    embedding: Optional[List[float]] = None
    rewritten_query: Optional[RewrittenQuery] = None

    def to_dict(self):
        if self.embedding is not None:
            return {
                "query": self.query,
                "requested_exercise_format": self.requested_exercise_format,
                "topic": self.topic,
                "embedding": self.embedding,
                "rewritten_query": (
                    self.rewritten_query.to_dict()
                    if self.rewritten_query is not None
                    else None
                ),
            }
        else:
            return {
                "query": self.query,
                "requested_exercise_format": self.requested_exercise_format,
                "topic": self.topic,
            }


class Metadata(BaseModel):
    title: Optional[str] = None
    chapter: Optional[str] = None
    subsection: Optional[str] = None
    subsubsection: Optional[str] = None
    doc_type: Literal["Content", "Exercise"]
    exercise_format: Optional[
        Literal[
            "short-answer",
            "long-answer",
            "true-false",
            "multiple-choice",
            "match",
            "draw",
        ]
    ] = None

    def to_dict(self):
        return {
            "title": self.title if self.title is not None else None,
            "chapter": self.chapter if self.chapter is not None else None,
            "subsection": self.subsection if self.subsection is not None else None,
            "subsubsection": (
                self.subsubsection if self.subsubsection is not None else None
            ),
            "doc_type": self.doc_type,
            "exercise_format": (
                self.exercise_format if self.exercise_format is not None else None
            ),
        }


class ChunkSchema(BaseModel):
    chunk: str
    metadata: Metadata
    embedding: Optional[List[float]] = None

    def to_dict(self):
        return {
            "chunk": self.chunk,
            "metadata": self.metadata.to_dict(),
            "embedding": self.embedding,
        }


class RetrievedDocSchema(BaseModel):
    retrieval_type: str
    score: Optional[float] = None
    rank: Optional[int] = None
    id: str
    source: ChunkSchema

    def to_dict(self):
        return {
            "retrieval_type": self.retrieval_type,
            "score": self.score if self.score is not None else None,
            "rank": self.rank if self.rank is not None else None,
            "id": self.id,
            "source": self.source.to_dict(),
        }


class ResponseSchema(BaseModel):
    text: str
    embedding: List[float]
    invoked_file_search: Optional[bool] = (
        None  # this one is only for the OpenAI assistants run
    )

    def to_dict(self):
        if self.invoked_file_search is None:
            return {"text": self.text, "embedding": self.embedding}
        else:
            return {
                "text": self.text,
                "embedding": self.embedding,
                "invoked_file_search": self.invoked_file_search,
            }


class PipelineData(BaseModel):
    query: EvalQuery  # this contains the query string, the requested exercise format, the topic, the embedding, and the string and embedding of the rewritten query for retrieval
    retrieved_docs: Optional[List[RetrievedDocSchema]] = None
    response: Optional[ResponseSchema] = None

    def to_dict(self):
        return {
            "query": self.query.to_dict(),
            "retrieved": (
                [retrieved_doc.to_dict() for retrieved_doc in self.retrieved_docs]
                if self.retrieved_docs is not None
                else None
            ),
            "response": self.response.to_dict() if self.response is not None else None,
        }
