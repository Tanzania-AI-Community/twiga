from functools import lru_cache
from pathlib import Path
import os
import requests
from typing import Iterator, Sequence, TypeVar


TOGETHER_BASE_URL = "https://api.together.xyz/v1"

T = TypeVar("T")


def project_root() -> Path:
    """Resolve repository root from this module's location."""
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=8)
def _parse_dotenv_file(dotenv_path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(dotenv_path)
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].strip()

        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        else:
            comment_idx = value.find(" #")
            if comment_idx != -1:
                value = value[:comment_idx].strip()

        values[key] = value

    return values


def read_env_value(
    key: str,
    *,
    env_file: Path | None = None,
    default: str | None = None,
) -> str | None:
    """Read an env var from OS env first, then fallback to a .env file."""
    runtime_value = os.getenv(key)
    if runtime_value:
        return runtime_value

    dotenv_path = env_file or (project_root() / ".env")
    dotenv_values = _parse_dotenv_file(str(dotenv_path))
    value_from_file = dotenv_values.get(key)
    if value_from_file:
        return value_from_file

    return default


def chunked(items: Sequence[T], batch_size: int) -> Iterator[Sequence[T]]:
    """Yield fixed-size slices from a sequence."""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")

    for start_idx in range(0, len(items), batch_size):
        yield items[start_idx : start_idx + batch_size]


class TogetherEmbeddingClient:
    """Small Together API client for batched embeddings calls."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = TOGETHER_BASE_URL,
        timeout_seconds: int = 60,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("A Together API key is required.")
        if not model or not model.strip():
            raise ValueError("A Together embedding model is required.")

        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in one Together request."""
        if not texts:
            return []

        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "input": list(texts)},
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Intentionally using print for immediate visibility in terminal runs.
            print(
                (
                    "[Together Embeddings HTTP Error] "
                    f"status={response.status_code} "
                    f"url={response.url} "
                    f"model={self.model} "
                    f"batch_size={len(texts)} "
                    f"text_lengths={[len(text) for text in texts]} "
                    f"response_body={response.text}"
                ),
                flush=True,
            )
            raise exc

        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Together response did not include a valid 'data' list.")

        embeddings_by_index: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(
                    "Together response included an invalid embedding item."
                )

            index = item.get("index")
            embedding = item.get("embedding")
            if not isinstance(index, int) or not isinstance(embedding, list):
                raise ValueError("Together response has an invalid embedding shape.")

            embeddings_by_index[index] = embedding

        expected_indices = set(range(len(texts)))
        if set(embeddings_by_index.keys()) != expected_indices:
            raise ValueError(
                "Together response does not contain embeddings for every input."
            )

        return [embeddings_by_index[idx] for idx in range(len(texts))]
