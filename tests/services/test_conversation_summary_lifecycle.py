"""Persisted Issue #92 scenarios: real PostgreSQL, fake models and delivery."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.clients import client_base
from app.clients.agent_client import AgentClient
from app.database import db
from app.database.enums import MessageRole
from app.database.models import ConversationSummaryBatch, Message, User
from app.services import conversation_summary_runtime as summary_runtime
from app.services import conversation_summary_service as summaries
from app.services import messaging_service as delivery
from app.services.exam_delivery_service import ExamPDFDeliveryDetails
from tests.database import conversation_summary_fixtures as summary_fixtures
from tests.services.test_messaging_service import SAMPLE_LESSON_PLAN

summary_pg = summary_fixtures.summary_pg
summary_pg_schema = summary_fixtures.summary_pg_schema
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
START = datetime(2026, 10, 25, tzinfo=timezone.utc)


async def seed(factory, count):
    user = User(id=1, wa_id="lifecycle-one", name="Teacher")
    async with factory.begin() as session:
        session.add(user)
        await session.flush()
        rows = [
            Message(
                user_id=1,
                role=MessageRole.user,
                content=f"source-{i}",
                created_at=START + timedelta(seconds=i),
                is_present_in_conversation=True,
            )
            for i in range(1, count + 1)
        ]
        session.add_all(rows)
    return user, rows


async def incoming(text="follow-up"):
    return await db.create_new_message_by_fields(
        user_id=1, role=MessageRole.user, content=text, is_present_in_conversation=True
    )


@pytest.fixture
def runtime(monkeypatch):
    # Real pinned tokenizer for most scenarios; budget compaction explicitly
    # substitutes len so large stored counts can be exercised with small fixtures.
    monkeypatch.setattr(
        summary_runtime.llm_settings, "provider", summary_runtime.LLMProvider.TOGETHER
    )
    monkeypatch.setattr(
        summary_runtime, "_resolve_model_name", lambda: "zai-org/GLM-5.3-Flash"
    )
    monkeypatch.setattr(
        summary_runtime.llm_settings,
        "together_fallback_models",
        ["deepseek-ai/DeepSeek-V4.1-Flash"],
    )
    service = summaries.ConversationSummaryService(
        counter=summary_runtime.count_summary_tokens
    )
    monkeypatch.setattr(client_base, "conversation_summary_service", service)
    monkeypatch.setattr(delivery, "conversation_summary_service", service)
    summary_call = AsyncMock(
        return_value=AIMessage(content="Preserved lesson goals and completed results.")
    )
    monkeypatch.setattr(summaries, "async_llm_request", summary_call)
    client = AgentClient()
    think = AsyncMock(return_value=AIMessage(content="Accepted visible answer."))
    monkeypatch.setattr(client, "_think", think)
    monkeypatch.setattr(client, "_tool_call_notification", AsyncMock())
    monkeypatch.setattr(delivery, "agent_client", client)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(delivery.whatsapp_client, "send_message", send)
    monkeypatch.setattr(
        delivery.whatsapp_client, "send_document_message", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(delivery, "render_lesson_plan_pdf", lambda *args: None)
    return service, client, think, summary_call, send, delivery.MessagingService()


async def assert_archive(factory, originals):
    async with factory() as session:
        rows = {m.id: m for m in (await session.execute(select(Message))).scalars()}
    for original in originals:
        actual = rows[original.id]
        assert (
            actual.content,
            actual.role,
            actual.created_at,
            actual.is_present_in_conversation,
        ) == (
            original.content,
            original.role,
            original.created_at,
            original.is_present_in_conversation,
        )
    return rows


async def test_soft_append_and_next_prompt_keep_visible_sources(summary_pg, runtime):
    factory, _ = summary_pg
    user, rows = await seed(factory, 25)
    service, client, think, summary_call, send, messaging = runtime

    async def delivery_after_commit(*args, **kwargs):
        assert (await db.get_conversation_summary_snapshot(1)).version == 1
        return True

    send.side_effect = delivery_after_commit
    await messaging.handle_chat_message(user, rows[-1])
    state = await db.get_conversation_summary_snapshot(1)
    assert state.version == 1 and not state.pending_sources
    archive = await assert_archive(factory, rows)
    visible = [
        m
        for m in archive.values()
        if m.role == MessageRole.assistant and m.is_present_in_conversation
    ]
    hidden = [
        m
        for m in archive.values()
        if m.role == MessageRole.assistant and not m.is_present_in_conversation
    ]
    assert len(visible) == len(hidden) == 1
    assert state.covered_message_ids == {*(m.id for m in rows), visible[0].id}
    assert hidden[0].id not in state.covered_message_ids
    assert state.active_batches[0].token_count == summary_runtime.count_summary_tokens(
        state.active_batches[0].summary_text
    )
    await messaging.handle_chat_message(user, await incoming())
    payload = think.await_args.kwargs["api_messages"]
    assert [m.type for m in payload] == ["system", "ai", "human"]
    assert payload[1].content == state.active_batches[0].summary_text
    assert payload[-1].content == "follow-up"
    assert summary_call.await_count == 1


async def test_hard_protected_request_survives_soft_hook_then_later_cycle(
    summary_pg, runtime
):
    factory, _ = summary_pg
    user, rows = await seed(factory, 31)
    _, _, think, summary_call, _, messaging = runtime
    await messaging.handle_chat_message(user, rows[-1])
    state = await db.get_conversation_summary_snapshot(1)
    assert state.covered_message_ids == frozenset(m.id for m in rows[:-1])
    assert [s.content for s in state.pending_sources] == [
        "source-31",
        "Accepted visible answer.",
    ]
    assert len(think.await_args.kwargs["api_messages"]) == 3
    assert summary_call.await_count == 1
    # A later, non-hard request can include the previously protected interaction.
    for i in range(23):
        latest = await incoming(f"later-{i}")
    await messaging.handle_chat_message(user, latest)
    after = await db.get_conversation_summary_snapshot(1)
    assert after.version == 2 and not after.pending_sources
    assert rows[-1].id in after.covered_message_ids
    await assert_archive(factory, rows)


async def test_soft_failure_stays_pending_delivers_then_retries(summary_pg, runtime):
    factory, _ = summary_pg
    user, rows = await seed(factory, 25)
    _, _, _, summary_call, send, messaging = runtime
    summary_call.side_effect = RuntimeError("summary unavailable")
    await messaging.handle_chat_message(user, rows[-1])
    before = await db.get_conversation_summary_snapshot(1)
    assert before.version is None and len(before.pending_sources) == 26
    send.assert_awaited_once()
    summary_call.side_effect = None
    await messaging.handle_chat_message(user, await incoming("retry later"))
    after = await db.get_conversation_summary_snapshot(1)
    assert after.version == 1 and not after.pending_sources
    assert set(s.id for s in before.pending_sources) <= after.covered_message_ids
    await assert_archive(factory, rows)


async def test_many_appends_compact_and_next_prompt_uses_rollup(summary_pg, runtime):
    factory, _ = summary_pg
    user, rows = await seed(factory, 30)
    service, _, think, _, _, messaging = runtime
    service.counter = (
        len  # Deliberate injected counter, separate from real-tokenizer checks.
    )
    for i in range(1, 6):
        await db.commit_conversation_summary(
            db.SummaryUpdate(
                1, i - 1 if i > 1 else None, i, (rows[i - 1].id,), "b" * 15000, 15000
            )
        )
    await messaging.handle_chat_message(user, rows[-1])
    state = await db.get_conversation_summary_snapshot(1)
    assert state.version == 6 and state.compacted_through_batch == 1
    assert [b.sequence_number for b in state.active_batches] == [2, 3, 4, 5, 6]
    assert all(b.summary_text == "b" * 15000 for b in state.active_batches[:4])
    assert state.token_count == len(state.older_history_summary) <= 25000
    assert sum(b.token_count for b in state.active_batches) <= 75000
    assert not state.pending_sources
    await messaging.handle_chat_message(user, await incoming())
    payload = think.await_args.kwargs["api_messages"]
    assert [m.content for m in payload[1:-1]] == [
        state.older_history_summary,
        *(b.summary_text for b in state.active_batches),
    ]
    assert payload[-1].content == "follow-up"
    await assert_archive(factory, rows)


async def test_successive_replacements_forget_old_rollup_but_keep_coverage(
    summary_pg, runtime
):
    factory, _ = summary_pg
    user, rows = await seed(factory, 30)
    service, _, think, summary_call, _, messaging = runtime
    service.counter = lambda text: 15000 if "NEW-BATCH" in text else len(text)
    for i in range(1, 6):
        marker = f"BATCH-{i}-"
        text = marker + "a" * (15000 - len(marker))
        assert (
            await db.commit_conversation_summary(
                db.SummaryUpdate(
                    1, i - 1 if i > 1 else None, i, (rows[i - 1].id,), text, 15000
                )
            )
            is db.SummaryWriteResult.COMMITTED
        )

    rollup_calls = []
    batch_number = 0

    async def generate(**kwargs):
        nonlocal batch_number
        if kwargs["run_name"] == "conversation_summary_rollup":
            rollup_calls.append(kwargs["messages"][1].content)
            return AIMessage(content=f"ROLLUP-{len(rollup_calls)}")
        assert kwargs["run_name"] == "conversation_summary_batch"
        batch_number += 1
        return AIMessage(content=f"NEW-BATCH-{batch_number}")

    summary_call.side_effect = generate
    before = await db.get_conversation_summary_snapshot(1)
    first_source = next(s for s in before.pending_sources if s.id == rows[5].id)
    first = await service._candidate(before, (first_source,))
    assert first.rollup.compacted_sequences == (1,)
    assert (
        await db.commit_conversation_summary(first) is db.SummaryWriteResult.COMMITTED
    )
    after_first = await db.get_conversation_summary_snapshot(1)
    assert "ROLLUP-1" in after_first.older_history_summary
    assert await db.commit_conversation_summary(first) is db.SummaryWriteResult.STALE
    assert await db.get_conversation_summary_snapshot(1) == after_first

    second_source = next(s for s in after_first.pending_sources if s.id == rows[6].id)
    second = await service._candidate(after_first, (second_source,))
    assert second.rollup.compacted_sequences == (2,)
    bad = replace(second, rollup=replace(second.rollup, compacted_sequences=(99,)))
    with pytest.raises(ValueError, match="older prefix"):
        await db.commit_conversation_summary(bad)
    assert await db.get_conversation_summary_snapshot(1) == after_first
    assert (
        await db.commit_conversation_summary(second) is db.SummaryWriteResult.COMMITTED
    )
    state = await db.get_conversation_summary_snapshot(1)

    assert "BATCH-1-" in rollup_calls[0] and "BATCH-2-" not in rollup_calls[0]
    assert "BATCH-2-" in rollup_calls[1] and "BATCH-1-" not in rollup_calls[1]
    assert "ROLLUP-1" not in rollup_calls[1]
    assert "ROLLUP-2" in state.older_history_summary
    assert "ROLLUP-1" not in state.older_history_summary
    assert state.compacted_through_batch == 2
    assert [b.sequence_number for b in state.active_batches] == [3, 4, 5, 6, 7]
    assert sum(b.token_count for b in state.active_batches) == 75000
    assert state.token_count <= 25000
    assert state.covered_message_ids == frozenset(row.id for row in rows[:7])
    assert not state.covered_message_ids.intersection(
        s.id for s in state.pending_sources
    )
    async with factory() as session:
        batches = (
            (
                await session.execute(
                    select(ConversationSummaryBatch).order_by(
                        ConversationSummaryBatch.sequence_number
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [(b.is_compacted, b.covered_message_ids) for b in batches[:2]] == [
        (True, [rows[0].id]),
        (True, [rows[1].id]),
    ]
    await messaging.handle_chat_message(user, rows[-1])
    payload = think.await_args.kwargs["api_messages"]
    assert state.older_history_summary in [m.content for m in payload]
    assert all("ROLLUP-1" not in m.content for m in payload)
    assert all(m.content not in {rows[0].content, rows[1].content} for m in payload)
    await assert_archive(factory, rows)


async def test_new_arrival_during_finalization_remains_raw(
    summary_pg, runtime, monkeypatch
):
    factory, _ = summary_pg
    user, rows = await seed(factory, 25)
    service, _, _, _, _, messaging = runtime
    finalize = service.finalize
    new = None

    async def arrive(request, result_ids):
        nonlocal new
        new = await incoming("arrived during finalization")
        return await finalize(request, result_ids)

    monkeypatch.setattr(service, "finalize", arrive)
    await messaging.handle_chat_message(user, rows[-1])
    state = await db.get_conversation_summary_snapshot(1)
    assert [s.id for s in state.pending_sources] == [new.id]
    assert new.id not in state.covered_message_ids
    assert state.version == 1


async def test_two_soft_finalizers_have_one_durable_winner(summary_pg, runtime):
    factory, _ = summary_pg
    _, rows = await seed(factory, 26)
    service, _, _, summary_call, _, _ = runtime
    barrier = asyncio.Barrier(2)

    async def generate(**kwargs):
        await barrier.wait()
        return AIMessage(content="One accepted history summary")

    summary_call.side_effect = generate
    request = summaries.SummaryRequestContext(
        1, tuple(m.id for m in rows), (rows[-1].id,)
    )
    outcomes = await asyncio.wait_for(
        asyncio.gather(service.finalize(request, ()), service.finalize(request, ())),
        timeout=15,
    )
    assert sorted(outcomes) == ["committed", "no_op"]
    state = await db.get_conversation_summary_snapshot(1)
    assert state.version == 1 and len(state.active_batches) == 1
    assert not state.pending_sources and len(state.covered_message_ids) == 26
    await assert_archive(factory, rows)


@pytest.mark.parametrize("artifact", ["lesson", "exam"])
async def test_artifact_result_is_summarized_before_first_document(
    summary_pg, runtime, monkeypatch, tmp_path, artifact
):
    factory, _ = summary_pg
    user, rows = await seed(factory, 25)
    _, client, think, summary_call, _, messaging = runtime
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    if artifact == "exam":
        think.return_value = AIMessage(
            content='{{TWIGA_EXAM_DELIVERY:{"exam_id":"' + exam_id + '"}}}'
        )
        details = ExamPDFDeliveryDetails(
            exam_id,
            tmp_path / "exam.pdf",
            tmp_path / "solution.pdf",
            True,
            True,
            "Geography",
            ["Climate"],
        )
        monkeypatch.setattr(
            delivery.exam_delivery_service,
            "get_exam_delivery_details",
            AsyncMock(return_value=details),
        )
    else:
        think.side_effect = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "create_lesson_plan", "args": {}, "id": "lesson-call"}
                ],
            ),
            AIMessage(content="The lesson is ready."),
        ]
        monkeypatch.setattr(
            client.tool_manager,
            "process_tool_calls",
            AsyncMock(
                return_value=[
                    Message(
                        user_id=1,
                        role=MessageRole.tool,
                        tool_name="create_lesson_plan",
                        tool_call_id="lesson-call",
                        content=json.dumps(SAMPLE_LESSON_PLAN),
                    )
                ]
            ),
        )

    async def send_document(**kwargs):
        state = await db.get_conversation_summary_snapshot(1)
        assert state.version == 1
        assert summary_call.await_count == 1
        return True

    monkeypatch.setattr(
        delivery.whatsapp_client, "send_document_message", send_document
    )
    await messaging.handle_chat_message(user, rows[-1])
    state = await db.get_conversation_summary_snapshot(1)
    assert state.version == 1 and len(state.active_batches) == 1
    prompt = summary_call.await_args.kwargs["messages"][1].content
    if artifact == "exam":
        assert f"Generated exam {exam_id}" in prompt and "subject: Geography" in prompt
        assert len(state.pending_sources) == 1  # Actual post-send status stays raw.
        assert "Here is your practice exam" in state.pending_sources[0].content
    else:
        assert "Introduction to Algebra" in prompt
        assert not state.pending_sources
        assert "tool_call" not in prompt
    await assert_archive(factory, rows)


@pytest.mark.parametrize("when", ["initial", "stale_retry"])
@pytest.mark.parametrize("compacted", [False, True])
async def test_covered_protected_input_never_reaches_agent(
    summary_pg, runtime, monkeypatch, when, compacted
):
    factory, _ = summary_pg
    user, rows = await seed(factory, 31)
    service, client, think, summary_call, _, _ = runtime
    service.counter = len  # Coverage fixture counts; not tokenizer verification.
    original_write = db.commit_conversation_summary
    protected = rows[0] if when == "initial" else rows[-1]
    peer_ids = (protected.id,) if when == "initial" else (rows[0].id, protected.id)

    async def peer_summarizes_protected():
        assert (
            await original_write(
                db.SummaryUpdate(
                    1,
                    None,
                    1,
                    peer_ids,
                    "peer summary",
                    len("peer summary"),
                )
            )
            is db.SummaryWriteResult.COMMITTED
        )
        if compacted:
            # Fold the protected input's batch into the rollup, leaving five
            # active batches that do not themselves carry its covered ID.
            for sequence in range(2, 7):
                rollup = (
                    db.RollupUpdate((1,), "peer rollup", len("peer rollup"))
                    if sequence == 6
                    else None
                )
                assert (
                    await original_write(
                        db.SummaryUpdate(
                            1,
                            sequence - 1,
                            sequence,
                            (rows[sequence - 1].id,),
                            "other batch",
                            len("other batch"),
                            rollup,
                        )
                    )
                    is db.SummaryWriteResult.COMMITTED
                )

    stale_attempts = []
    if when == "initial":
        await peer_summarizes_protected()
    else:

        async def race(candidate):
            stale_attempts.append(candidate)
            await peer_summarizes_protected()
            return await original_write(candidate)

        monkeypatch.setattr(db, "commit_conversation_summary", race)

    result = await client.generate_response(user, protected)
    assert result is None  # Existing safe preparation-failure result.
    think.assert_not_awaited()
    assert summary_call.await_count == int(when == "stale_retry")
    if when == "stale_retry":
        assert len(stale_attempts) == 1
        assert protected.id not in stale_attempts[0].covered_message_ids
    state = await db.get_conversation_summary_snapshot(1)
    assert protected.id in state.covered_message_ids
    assert protected.id not in {s.id for s in state.pending_sources}
    if compacted:
        assert (
            state.compacted_through_batch == 1
            and state.older_history_summary == "peer rollup"
        )
        assert protected.id not in {
            i for batch in state.active_batches for i in batch.covered_message_ids
        }
        async with factory() as session:
            archived = (
                await session.execute(
                    select(ConversationSummaryBatch).where(
                        ConversationSummaryBatch.sequence_number == 1
                    )
                )
            ).scalar_one()
        assert archived.is_compacted and archived.summary_text == ""
        assert protected.id in archived.covered_message_ids
    await assert_archive(factory, rows)


@pytest.mark.parametrize(
    "scenario", ["primary", "fallback", "timeout", "soft_exhausted", "hard_exhausted"]
)
async def test_persisted_delivery_with_summary_router(
    summary_pg, runtime, monkeypatch, scenario
):
    from types import SimpleNamespace

    from pydantic import SecretStr

    from app.utils import llm_utils
    from app.utils.llm_failover import TogetherModelRouter
    from tests.utils.test_llm_failover import api_error

    factory, _ = summary_pg
    user, rows = await seed(factory, 31 if scenario == "hard_exhausted" else 25)
    _, _, think, _, send, messaging = runtime
    primary = "zai-org/GLM-5.3-Flash"
    fallback = "deepseek-ai/DeepSeek-V4.1-Flash"
    monkeypatch.setattr(summary_runtime.llm_settings, "llm_name", primary)
    monkeypatch.setattr(
        summary_runtime.llm_settings, "api_key", SecretStr("synthetic-test-key")
    )
    monkeypatch.setattr(llm_utils, "together_router", TogetherModelRouter())
    monkeypatch.setattr(summaries, "async_llm_request", llm_utils.async_llm_request)
    called = []
    if scenario == "timeout":
        monkeypatch.setattr(
            summaries,
            "summary_settings",
            SimpleNamespace(
                **{
                    **summaries.summary_settings.model_dump(),
                    "operation_timeout_seconds": 3,
                }
            ),
        )

    def create_client(**kwargs):
        model = kwargs["model_name"]

        async def invoke(messages, **options):
            called.append(model)
            if scenario == "timeout" and model == primary:
                await asyncio.Event().wait()
            if scenario in {"soft_exhausted", "hard_exhausted"} or (
                scenario == "fallback" and model == primary
            ):
                raise api_error(503)
            return AIMessage(content="Synthetic preserved summary.")

        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(llm_utils, "_create_llm_client", create_client)
    await messaging.handle_chat_message(user, rows[-1])
    snapshot = await db.get_conversation_summary_snapshot(1)
    assert called == ([primary] if scenario == "primary" else [primary, fallback])
    if scenario in {"primary", "fallback", "timeout"}:
        assert (
            snapshot.active_batches and think.await_count == 1 and send.await_count >= 1
        )
    else:
        assert not snapshot.active_batches and not snapshot.covered_message_ids
        if scenario == "soft_exhausted":
            assert think.await_count == 1 and send.await_count >= 1
        else:
            think.assert_not_awaited()
