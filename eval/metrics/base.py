from abc import ABC, abstractmethod
from typing import Any


class Metric(ABC):
    name: str
    required_columns: list[str]

    @abstractmethod
    async def ascore(self, row: dict[str, Any]) -> float | dict:
        """Score a single row. Returns float 0-1 or dict of metric_name→float."""
        ...


class LLMMetric(Metric, ABC):
    """Metric that requires an LLM (and optionally embeddings) to be injected."""

    def __init__(self, llm: Any, embeddings: Any = None) -> None:
        self.llm = llm
        self.embeddings = embeddings
