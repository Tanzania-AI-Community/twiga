from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.database.enums as enums
from app.database.models import Message, User
from app.services.citation_service import CitationRenderResult
from app.services.exam_delivery_service import ExamPDFDeliveryDetails
from app.services.messaging_service import MessagingService


@pytest.mark.asyncio
async def test_command_settings_persists_visible_message() -> None:
    service = MessagingService()
    user = User(id=31, wa_id="255700000222", name="Teacher")

    with (
        patch(
            "app.services.messaging_service.strings.get_string",
            side_effect=["Settings intro", "Personal info", "Classes and subjects"],
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ) as mock_persist_visible,
    ):
        await service._command_settings(user)

    mock_send_message.assert_awaited_once_with(
        user.wa_id,
        "Settings intro",
        ["Personal info", "Classes and subjects"],
    )
    mock_persist_visible.assert_awaited_once_with(user, "Settings intro")


@pytest.mark.asyncio
async def test_handle_chat_message_marks_final_response_as_hidden_and_persists_visible() -> (
    None
):
    service = MessagingService()
    user = User(id=1, wa_id="255700000000", name="Teacher")
    user_message = Message(
        user_id=1,
        role=enums.MessageRole.user,
        content="What is photosynthesis?",
    )
    final_message = Message(
        user_id=1,
        role=enums.MessageRole.assistant,
        content="Photosynthesis is how plants make food.",
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ) as mock_create_messages,
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ) as mock_persist_visible,
        patch("app.services.messaging_service.record_messages_generated"),
        patch(
            "app.services.messaging_service.looks_like_latex",
            return_value=False,
        ),
    ):
        response = await service.handle_chat_message(
            user=user,
            user_message=user_message,
        )

    assert response.status_code == 200
    assert final_message.is_present_in_conversation is False
    mock_create_messages.assert_awaited_once_with([final_message])
    mock_send_message.assert_awaited_once_with(user.wa_id, final_message.content)
    mock_persist_visible.assert_awaited_once_with(
        user=user, content=final_message.content, source_chunk_ids=None
    )


@pytest.mark.asyncio
async def test_handle_chat_message_persists_general_error_when_llm_returns_none() -> (
    None
):
    service = MessagingService()
    user = User(id=3, wa_id="255700000000", name="Teacher")
    user_message = Message(
        user_id=3,
        role=enums.MessageRole.user,
        content="Hi",
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.messaging_service.strings.get_string",
            return_value="Something went wrong.",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.messaging_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user,
            user_message=user_message,
        )

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, "Something went wrong.")
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Something went wrong.",
        "is_present_in_conversation": True,
        "source_chunk_ids": None,
    }


@pytest.mark.asyncio
async def test_handle_chat_message_persists_tool_leakage_fallback_as_visible() -> None:
    service = MessagingService()
    user = User(id=4, wa_id="255700000123", name="Teacher")
    user_message = Message(
        user_id=4,
        role=enums.MessageRole.user,
        content="Tell me more",
    )
    leaked_message = Message(
        user_id=4,
        role=enums.MessageRole.assistant,
        content="I will use search_knowledge now.",
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[leaked_message]),
        ),
        patch(
            "app.services.messaging_service.strings.get_string",
            return_value="Tool leakage fallback",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ) as mock_create_new_messages,
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user, user_message=user_message
        )

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, "Tool leakage fallback")
    persisted_messages = mock_create_new_messages.await_args.args[0]
    assert len(persisted_messages) == 2
    assert persisted_messages[1].content == "Tool leakage fallback"
    assert persisted_messages[1].is_present_in_conversation is True


@pytest.mark.asyncio
async def test_handle_other_message_persists_visible_error() -> None:
    service = MessagingService()
    user = User(id=9, wa_id="255700000555", name="Teacher")
    user_message = Message(
        user_id=user.id,
        role=enums.MessageRole.user,
        content=None,
    )

    with (
        patch(
            "app.services.messaging_service.strings.get_string",
            return_value="Unsupported message",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_read_receipt_with_typing_indicator",
            AsyncMock(),
        ) as mock_send_typing_indicator,
        patch(
            "app.services.messaging_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_other_message(user, user_message)

    assert response.status_code == 200
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Unsupported message",
        "is_present_in_conversation": True,
        "source_chunk_ids": None,
    }
    mock_send_typing_indicator.assert_awaited_once_with("")
    mock_send_message.assert_awaited_once_with(
        wa_id=user.wa_id,
        message="Unsupported message",
    )


@pytest.mark.asyncio
async def test_handle_other_message_sends_typing_indicator_with_inbound_message_id() -> (
    None
):
    service = MessagingService()
    user = User(id=10, wa_id="255700000556", name="Teacher")
    user_message = Message(
        user_id=user.id,
        role=enums.MessageRole.user,
        content="Audio file",
    )

    with (
        patch(
            "app.services.messaging_service.strings.get_string",
            return_value="Unsupported message",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_read_receipt_with_typing_indicator",
            AsyncMock(),
        ) as mock_send_typing_indicator,
        patch(
            "app.services.messaging_service.db.create_new_message_by_fields",
            AsyncMock(),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ),
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_other_message(
            user, user_message, inbound_message_id="wamid.OTHER002"
        )

    assert response.status_code == 200
    mock_send_typing_indicator.assert_awaited_once_with("wamid.OTHER002")


@pytest.mark.asyncio
async def test_persist_visible_assistant_message_skips_when_user_id_is_missing() -> (
    None
):
    service = MessagingService()
    user = User(id=None, wa_id="255700000999", name="Teacher")

    with patch(
        "app.services.messaging_service.db.create_new_message_by_fields",
        AsyncMock(),
    ) as mock_create_message_by_fields:
        await service._persist_visible_assistant_message(user, "Visible content")

    mock_create_message_by_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_chat_message_exam_marker_sends_documents_and_strips_marker() -> (
    None
):
    service = MessagingService()
    user = User(id=11, wa_id="255700000101", name="Teacher")
    user_message = Message(
        user_id=11,
        role=enums.MessageRole.user,
        content="Create an exam",
    )
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    llm_content = (
        "Your exam is ready.\n"
        '{{TWIGA_EXAM_DELIVERY:{"exam_id":"b1740ac9-bfea-415f-8b3a-c7f06ee8c353"}}}'
    )
    final_message = Message(
        user_id=11,
        role=enums.MessageRole.assistant,
        content=llm_content,
    )

    artifacts = ExamPDFDeliveryDetails(
        exam_id=exam_id,
        exam_pdf_path=Path(f"outputs/exam_pdfs/exam_{exam_id}.pdf"),
        solution_pdf_path=Path(f"outputs/exam_pdfs/exam_{exam_id}_solution.pdf"),
        exam_pdf_ready=True,
        solution_pdf_ready=True,
        subject="Geography",
        topics=["Climate", "Weather"],
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ) as mock_create_messages,
        patch(
            "app.services.messaging_service.exam_delivery_service.get_exam_delivery_details",
            AsyncMock(return_value=artifacts),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_document_message",
            AsyncMock(return_value=True),
        ) as mock_send_document,
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ),
        patch("app.services.messaging_service.looks_like_latex", return_value=False),
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user, user_message=user_message
        )

    assert response.status_code == 200
    mock_create_messages.assert_awaited_once_with([final_message])
    assert final_message.content == llm_content
    assert mock_send_document.await_count == 2
    mock_send_message.assert_awaited_once_with(
        user.wa_id,
        "Here is your practice exam in Geography on topics: Climate, Weather.",
    )


@pytest.mark.asyncio
async def test_handle_chat_message_invalid_exam_marker_falls_back_to_clean_text() -> (
    None
):
    service = MessagingService()
    user = User(id=12, wa_id="255700000102", name="Teacher")
    user_message = Message(
        user_id=12,
        role=enums.MessageRole.user,
        content="Create an exam",
    )
    final_message = Message(
        user_id=12,
        role=enums.MessageRole.assistant,
        content='Here you go {{TWIGA_EXAM_DELIVERY:{"exam_id":"not-a-uuid"}}}',
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch(
            "app.services.messaging_service.citation_service.render_citations",
            AsyncMock(
                return_value=CitationRenderResult(
                    marker_found=False,
                    rendered_content="Here you go",
                    ordered_chunk_ids=[],
                    valid_reference_count=0,
                    invalid_reference_count=0,
                )
            ),
        ),
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ),
        patch(
            "app.services.messaging_service.exam_delivery_service.get_exam_delivery_details",
            AsyncMock(),
        ) as mock_ensure_artifacts,
        patch(
            "app.services.messaging_service.whatsapp_client.send_document_message",
            AsyncMock(return_value=True),
        ) as mock_send_document,
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ),
        patch("app.services.messaging_service.looks_like_latex", return_value=False),
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user, user_message=user_message
        )

    assert response.status_code == 200
    mock_ensure_artifacts.assert_not_awaited()
    mock_send_document.assert_not_awaited()
    mock_send_message.assert_awaited_once_with(user.wa_id, "Here you go")


@pytest.mark.asyncio
async def test_handle_chat_message_rewrites_citation_markers_for_user_output() -> None:
    service = MessagingService()
    user = User(id=15, wa_id="255700000105", name="Teacher")
    user_message = Message(
        user_id=15,
        role=enums.MessageRole.user,
        content="Explain photosynthesis",
    )
    final_message = Message(
        user_id=15,
        role=enums.MessageRole.assistant,
        content=(
            "Plants make food using sunlight"
            '{{TWIGA_CITATION:{"chunk_id":501}}}, and chlorophyll helps capture light'
            '{{TWIGA_CITATION:{"chunk_id":502}}}.'
        ),
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch(
            "app.services.messaging_service.citation_service.render_citations",
            AsyncMock(
                return_value=CitationRenderResult(
                    marker_found=True,
                    rendered_content=(
                        "Plants make food using sunlight [1], and chlorophyll helps capture light [2].\n\n"
                        "Sources:\n"
                        "[1] Book, page 1\n"
                        "[2] Book, page 2"
                    ),
                    ordered_chunk_ids=[501, 502],
                    valid_reference_count=2,
                    invalid_reference_count=0,
                )
            ),
        ),
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ) as mock_persist_visible,
        patch("app.services.messaging_service.looks_like_latex", return_value=False),
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user,
            user_message=user_message,
        )

    rendered_content = (
        "Plants make food using sunlight [1], and chlorophyll helps capture light [2].\n\n"
        "Sources:\n"
        "[1] Book, page 1\n"
        "[2] Book, page 2"
    )

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, rendered_content)
    mock_persist_visible.assert_awaited_once_with(
        user=user,
        content=rendered_content,
        source_chunk_ids=None,
    )


@pytest.mark.asyncio
async def test_handle_chat_message_exam_marker_partial_failure_appends_notice() -> None:
    service = MessagingService()
    user = User(id=13, wa_id="255700000103", name="Teacher")
    user_message = Message(
        user_id=13,
        role=enums.MessageRole.user,
        content="Create an exam",
    )
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    final_message = Message(
        user_id=13,
        role=enums.MessageRole.assistant,
        content=(
            "I have prepared your exam documents."
            '{{TWIGA_EXAM_DELIVERY:{"exam_id":"b1740ac9-bfea-415f-8b3a-c7f06ee8c353"}}}'
        ),
    )
    artifacts = ExamPDFDeliveryDetails(
        exam_id=exam_id,
        exam_pdf_path=Path(f"outputs/exam_pdfs/exam_{exam_id}.pdf"),
        solution_pdf_path=Path(f"outputs/exam_pdfs/exam_{exam_id}_solution.pdf"),
        exam_pdf_ready=True,
        solution_pdf_ready=True,
        subject="Geography",
        topics=["Climate", "Weather"],
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ),
        patch(
            "app.services.messaging_service.exam_delivery_service.get_exam_delivery_details",
            AsyncMock(return_value=artifacts),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_document_message",
            AsyncMock(side_effect=[True, False]),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ),
        patch("app.services.messaging_service.looks_like_latex", return_value=False),
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user, user_message=user_message
        )

    assert response.status_code == 200
    sent_text = mock_send_message.await_args.args[1]
    assert sent_text == "Sorry, something went wrong in generating the exam solution."


@pytest.mark.asyncio
async def test_handle_chat_message_marker_only_skips_text_send_after_documents() -> (
    None
):
    service = MessagingService()
    user = User(id=14, wa_id="255700000104", name="Teacher")
    user_message = Message(
        user_id=14,
        role=enums.MessageRole.user,
        content="Create an exam",
    )
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    final_message = Message(
        user_id=14,
        role=enums.MessageRole.assistant,
        content='{{TWIGA_EXAM_DELIVERY:{"exam_id":"b1740ac9-bfea-415f-8b3a-c7f06ee8c353"}}}',
    )
    artifacts = ExamPDFDeliveryDetails(
        exam_id=exam_id,
        exam_pdf_path=Path(f"outputs/exam_pdfs/exam_{exam_id}.pdf"),
        solution_pdf_path=Path(f"outputs/exam_pdfs/exam_{exam_id}_solution.pdf"),
        exam_pdf_ready=True,
        solution_pdf_ready=True,
        subject="Geography",
        topics=["Climate", "Weather"],
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch(
            "app.services.messaging_service.db.create_new_messages",
            AsyncMock(),
        ),
        patch(
            "app.services.messaging_service.exam_delivery_service.get_exam_delivery_details",
            AsyncMock(return_value=artifacts),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_document_message",
            AsyncMock(side_effect=[True, True]),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ),
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user, user_message=user_message
        )

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(
        user.wa_id,
        "Here is your practice exam in Geography on topics: Climate, Weather.",
    )
