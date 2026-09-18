from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.utils import google_embedder


def response(values=None, *, truncated=False):
    return SimpleNamespace(
        embeddings=[
            SimpleNamespace(
                values=values if values is not None else [0.25] * 1024,
                statistics=SimpleNamespace(truncated=truncated),
            )
        ]
    )


@pytest.fixture
def client(monkeypatch):
    sdk = MagicMock()
    sdk.models.embed_content.return_value = response()
    constructor = MagicMock(return_value=sdk)
    monkeypatch.setattr(google_embedder.genai, "Client", constructor)
    adapter = google_embedder.GoogleEmbeddingClient(project="test-project")
    return adapter, sdk, constructor


def test_vertex_adc_configuration_and_task_types(client):
    adapter, sdk, constructor = client
    kwargs = constructor.call_args.kwargs
    assert kwargs["vertexai"] is True
    assert kwargs["project"] == "test-project"
    assert kwargs["location"] == "global"
    assert "api_key" not in kwargs
    assert kwargs["http_options"].retry_options.attempts == 5
    assert adapter.embed_query("question") == [0.25] * 1024
    config = sdk.models.embed_content.call_args.kwargs["config"]
    assert config.task_type == "RETRIEVAL_QUERY"
    assert config.output_dimensionality == 1024
    assert config.auto_truncate is False
    adapter.embed_documents(["document"])
    assert (
        sdk.models.embed_content.call_args.kwargs["config"].task_type
        == "RETRIEVAL_DOCUMENT"
    )
    adapter.close()
    sdk.close.assert_called_once()


def test_document_requests_preserve_input_order(client):
    adapter, sdk, _ = client
    sdk.models.embed_content.side_effect = lambda **kw: SimpleNamespace(
        embeddings=[response([float(t)] * 1024).embeddings[0] for t in kw["contents"]]
    )
    texts = [str(n) for n in range(20, 0, -1)]
    assert adapter.embed_documents(texts) == [[float(t)] * 1024 for t in texts]
    assert sdk.models.embed_content.call_count == 3
    assert all(
        len(call.kwargs["contents"]) <= 8
        for call in sdk.models.embed_content.call_args_list
    )


@pytest.mark.parametrize(
    "values", [[], [1.0], [0.0] * 1024, [float("nan")] * 1024, [float("inf")] * 1024]
)
def test_rejects_invalid_vectors(client, values):
    adapter, sdk, _ = client
    sdk.models.embed_content.return_value = response(values)
    with pytest.raises(ValueError):
        adapter.embed_query("question")


def test_rejects_truncated_and_missing_responses(client):
    adapter, sdk, _ = client
    sdk.models.embed_content.return_value = response(truncated=True)
    with pytest.raises(ValueError, match="truncated"):
        adapter.embed_query("long question")
    sdk.models.embed_content.return_value = SimpleNamespace(embeddings=[])
    with pytest.raises(ValueError, match="exactly one"):
        adapter.embed_query("question")


def test_rejects_blank_input_without_api_call(client):
    adapter, sdk, _ = client
    with pytest.raises(ValueError, match="empty"):
        adapter.embed_query("  ")
    assert adapter.embed_documents([]) == []
    sdk.models.embed_content.assert_not_called()


def test_configuration_fails_before_authentication():
    with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
        google_embedder.GoogleEmbeddingClient(project="")
    with pytest.raises(ValueError, match="1024"):
        google_embedder.GoogleEmbeddingClient(project="test", dimensions=3072)


def test_provider_failure_is_not_silently_skipped(client):
    adapter, sdk, _ = client
    sdk.models.embed_content.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        adapter.embed_documents(["first", "second"])


def test_document_prefix_preserves_utf8_and_never_truncates_queries(client):
    adapter, sdk, _ = client
    original = "é" * 1500 + "rest of document"
    adapter.embed_documents([original])
    sent = sdk.models.embed_content.call_args.kwargs["contents"][0]
    assert len(sent.encode("utf-8")) == 2048
    assert original.startswith(sent)
    assert original.endswith("rest of document")
    adapter.embed_query(original)
    assert sdk.models.embed_content.call_args.kwargs["contents"] == [original]
