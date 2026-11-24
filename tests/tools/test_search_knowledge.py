"""
Tests for the search_knowledge tool and its optional reranking step.

The database, embedder and reranker are mocked, so no external services are called.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.database.models import Chunk
from app.tools.tool_code.search_knowledge import main as search_main
from app.utils.reranker import TogetherReranker, VertexReranker, get_reranker

MODULE = "app.tools.tool_code.search_knowledge.main"


def _chunks(n: int) -> list[Chunk]:
    return [Chunk(id=i, content=f"chunk {i}", resource_id=1) for i in range(n)]


def _settings(rerank: bool, n_results: int = 3, pool: int = 10, timeout: float = 3):
    return MagicMock(
        search_knowledge_n_results=n_results,
        search_knowledge_rerank_enabled=rerank,
        search_knowledge_rerank_candidate_pool=pool,
        search_knowledge_rerank_timeout=timeout,
    )


async def _search(settings, chunks, reranker=None):
    with (
        patch(f"{MODULE}.tool_settings", settings),
        patch(f"{MODULE}.db.get_class_resources", AsyncMock(return_value=[1])),
        patch(f"{MODULE}.vector_search", AsyncMock(return_value=chunks)) as vs,
        patch(f"{MODULE}._get_reranker", return_value=reranker),
    ):
        result = await search_main.search_knowledge("soil profile", class_id=1)
    return result, vs


@pytest.mark.asyncio
async def test_rerank_disabled_keeps_vector_search_unchanged():
    reranker = MagicMock(rank=AsyncMock())
    result, vs = await _search(_settings(rerank=False), _chunks(3), reranker)

    assert vs.await_args.kwargs["n_results"] == 3
    reranker.rank.assert_not_awaited()
    assert result["source_chunk_ids"] == [0, 1, 2]


@pytest.mark.asyncio
async def test_rerank_fetches_pool_and_returns_reranked_top_n():
    reranker = MagicMock(rank=AsyncMock(return_value=[7, 2, 9, 0, 1]))
    result, vs = await _search(_settings(rerank=True), _chunks(10), reranker)

    assert vs.await_args.kwargs["n_results"] == 10
    reranker.rank.assert_awaited_once_with(
        "soil profile", [f"chunk {i}" for i in range(10)]
    )
    assert result["source_chunk_ids"] == [7, 2, 9]
    assert result["content"].index('"chunk_id":7') < result["content"].index(
        '"chunk_id":2'
    )


@pytest.mark.asyncio
async def test_rerank_pool_is_never_smaller_than_n_results():
    reranker = MagicMock(rank=AsyncMock(return_value=[0]))
    _, vs = await _search(
        _settings(rerank=True, n_results=15, pool=5), _chunks(15), reranker
    )

    assert vs.await_args.kwargs["n_results"] == 15


@pytest.mark.asyncio
async def test_rerank_error_falls_back_to_vector_order():
    reranker = MagicMock(rank=AsyncMock(side_effect=httpx.ConnectError("down")))
    result, _ = await _search(_settings(rerank=True), _chunks(10), reranker)

    assert result["source_chunk_ids"] == [0, 1, 2]


@pytest.mark.asyncio
async def test_rerank_timeout_falls_back_to_vector_order():
    async def slow_rank(query, documents):
        await asyncio.sleep(1)
        return [9, 8, 7]

    reranker = MagicMock(rank=slow_rank)
    result, _ = await _search(
        _settings(rerank=True, timeout=0.01), _chunks(10), reranker
    )

    assert result["source_chunk_ids"] == [0, 1, 2]


@pytest.mark.asyncio
async def test_rerank_ignores_invalid_and_duplicate_indices():
    reranker = MagicMock(rank=AsyncMock(return_value=[4, 4, 99, -1, 1]))
    result, _ = await _search(_settings(rerank=True), _chunks(5), reranker)

    assert result["source_chunk_ids"] == [4, 1]


@pytest.mark.asyncio
async def test_rerank_with_no_valid_indices_falls_back_to_vector_order():
    reranker = MagicMock(rank=AsyncMock(return_value=[99]))
    result, _ = await _search(_settings(rerank=True), _chunks(5), reranker)

    assert result["source_chunk_ids"] == [0, 1, 2]


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://x"))


@pytest.mark.asyncio
async def test_together_reranker_orders_by_relevance_score():
    payload = {
        "results": [
            {"index": 0, "relevance_score": 0.1},
            {"index": 2, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.5},
        ]
    }
    with patch(
        "httpx.AsyncClient.post", AsyncMock(return_value=_response(payload))
    ) as post:
        order = await TogetherReranker("key", "model", 3).rank("q", ["a", "b", "c"])

    assert order == [2, 1, 0]
    assert post.await_args.kwargs["json"]["documents"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_vertex_reranker_returns_record_ids_in_order():
    payload = {"records": [{"id": "1", "score": 0.8}, {"id": "0", "score": 0.2}]}
    reranker = VertexReranker("project", "semantic-ranker-default@latest", 3)
    with (
        patch.object(reranker, "_access_token", return_value="token"),
        patch(
            "httpx.AsyncClient.post", AsyncMock(return_value=_response(payload))
        ) as post,
    ):
        order = await reranker.rank("q", ["a", "b"])

    assert order == [1, 0]
    assert post.await_args.kwargs["json"]["records"] == [
        {"id": "0", "content": "a"},
        {"id": "1", "content": "b"},
    ]


def test_get_reranker_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported rerank provider"):
        get_reranker("unknown", "model", 3)
