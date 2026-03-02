import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.database.reembed_chunks_in_db import (
    _to_pgvector_literal,
    normalize_database_url,
    rewrite_container_hostname,
    validate_table_name,
)
from scripts.database.reembed_chunks_json import (
    reembed_chunks_file,
    reembed_chunks_payload,
)
from scripts.database.reembedding_utils import (
    TogetherEmbeddingClient,
    chunked,
    read_env_value,
)


class _MockResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


@pytest.mark.unittest
def test_chunked_splits_list_in_fixed_batches() -> None:
    batches = list(chunked([1, 2, 3, 4, 5], 2))
    assert batches == [[1, 2], [3, 4], [5]]


@pytest.mark.unittest
def test_chunked_raises_for_invalid_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size must be greater than 0"):
        list(chunked([1], 0))


@pytest.mark.unittest
def test_together_embed_documents_uses_single_batched_call_and_index_order() -> None:
    client = TogetherEmbeddingClient(api_key="test-key", model="test-model")
    payload = {
        "data": [
            {"index": 1, "embedding": [2.0]},
            {"index": 0, "embedding": [1.0]},
        ]
    }

    with patch(
        "scripts.database.reembedding_utils.requests.post",
        return_value=_MockResponse(payload),
    ) as mock_post:
        embeddings = client.embed_documents(["first", "second"])

    assert embeddings == [[1.0], [2.0]]
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"model": "test-model", "input": ["first", "second"]}
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.unittest
def test_together_embed_documents_raises_when_response_count_mismatches() -> None:
    client = TogetherEmbeddingClient(api_key="test-key", model="test-model")
    payload = {"data": [{"index": 0, "embedding": [1.0]}]}

    with patch(
        "scripts.database.reembedding_utils.requests.post",
        return_value=_MockResponse(payload),
    ):
        with pytest.raises(
            ValueError, match="does not contain embeddings for every input"
        ):
            client.embed_documents(["first", "second"])


@pytest.mark.unittest
def test_normalize_database_url_converts_postgresql_scheme() -> None:
    normalized = normalize_database_url("postgresql://user:pass@localhost:5432/twiga")
    assert normalized == "postgresql+asyncpg://user:pass@localhost:5432/twiga"


@pytest.mark.unittest
def test_normalize_database_url_adds_ssl_for_neon() -> None:
    normalized = normalize_database_url("postgresql://user:pass@mydb.neon.tech/twiga")
    assert normalized.startswith("postgresql+asyncpg://user:pass@mydb.neon.tech/twiga")
    assert "ssl=require" in normalized


@pytest.mark.unittest
def test_normalize_database_url_rewrites_sslmode_and_drops_channel_binding() -> None:
    normalized = normalize_database_url(
        "postgresql://user:pass@host:5432/db?sslmode=require&channel_binding=require"
    )
    assert "sslmode" not in normalized
    assert "channel_binding" not in normalized
    assert "ssl=require" in normalized


@pytest.mark.unittest
def test_rewrite_container_hostname_swaps_db_for_localhost() -> None:
    rewritten = rewrite_container_hostname(
        "postgresql+asyncpg://postgres:password@db:5432/twiga_db"
    )
    assert rewritten == "postgresql+asyncpg://postgres:password@localhost:5432/twiga_db"


@pytest.mark.unittest
def test_read_env_value_uses_dotenv_when_runtime_var_missing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('EMBEDDING_API_KEY="abc123"\n', encoding="utf-8")

    with patch.dict("os.environ", {}, clear=True):
        value = read_env_value("EMBEDDING_API_KEY", env_file=env_file)

    assert value == "abc123"


@pytest.mark.unittest
def test_validate_table_name_rejects_invalid_identifier() -> None:
    with pytest.raises(ValueError):
        validate_table_name("chunks;DROP TABLE chunks;")


@pytest.mark.unittest
def test_to_pgvector_literal_builds_pgvector_string() -> None:
    literal = _to_pgvector_literal([1.0, 2.5, -3.2])
    assert literal == "[1,2.5,-3.2]"


@pytest.mark.unittest
def test_reembed_chunks_payload_updates_embeddings_in_batches() -> None:
    chunks = [
        {"chunk": "first", "metadata": {"chapter": "1"}, "embedding": [0.0]},
        {"chunk": "second", "metadata": {"chapter": "2"}, "embedding": [0.0]},
        {"chunk": "third", "metadata": {"chapter": "3"}, "embedding": [0.0]},
    ]
    embedder = MagicMock()
    embedder.embed_documents.side_effect = [
        [[1.0], [2.0]],
        [[3.0]],
    ]

    updated = reembed_chunks_payload(
        chunks=chunks,
        embedding_client=embedder,
        batch_size=2,
    )

    assert [item["embedding"] for item in updated] == [[1.0], [2.0], [3.0]]
    assert [item["chunk"] for item in updated] == ["first", "second", "third"]
    assert updated[0]["metadata"] == {"chapter": "1"}
    embedder.embed_documents.assert_any_call(["first", "second"])
    embedder.embed_documents.assert_any_call(["third"])


@pytest.mark.unittest
def test_reembed_chunks_file_writes_updated_output(tmp_path: Path) -> None:
    input_file = tmp_path / "chunks_BAAI.json"
    output_file = tmp_path / "chunks_multilingual.json"

    with input_file.open("w", encoding="utf-8") as file:
        json.dump(
            [{"chunk": "hello", "metadata": {"chapter": 1}, "embedding": [0.0]}], file
        )

    embedder = MagicMock()
    embedder.embed_documents.return_value = [[9.0, 8.0]]

    total = reembed_chunks_file(
        input_file=input_file,
        output_file=output_file,
        embedding_client=embedder,
        batch_size=8,
    )

    assert total == 1
    with output_file.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    assert payload[0]["chunk"] == "hello"
    assert payload[0]["embedding"] == [9.0, 8.0]
