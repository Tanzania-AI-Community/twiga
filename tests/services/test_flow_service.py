from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import PlainTextResponse

import app.database.enums as enums
from app.database.models import User
from app.services.flow_service import FlowService


@pytest.mark.asyncio
async def test_send_personal_and_school_info_flow_persists_flow_message() -> None:
    user = User(id=41, wa_id="255700000333", name="Teacher")
    flow_strings = {
        "start_onboarding_header": "Welcome",
        "start_onboarding_body": "Please complete your profile",
        "start_onboarding_cta": "Start",
    }

    with (
        patch("app.services.flow_service.settings.onboarding_flow_id", "flow-123"),
        patch(
            "app.services.flow_service.strings.get_category",
            return_value=flow_strings,
        ),
        patch(
            "app.services.flow_service.futil.send_whatsapp_flow_message",
            AsyncMock(),
        ),
        patch.object(
            FlowService,
            "_persist_flow_message",
            AsyncMock(),
        ) as mock_persist_flow_message,
    ):
        service = FlowService()
        await service.send_personal_and_school_info_flow(user)

    assert mock_persist_flow_message.await_args.kwargs == {
        "user": user,
        "flow_id": "flow-123",
        "header_text": "Welcome",
        "body_text": "Please complete your profile",
    }


@pytest.mark.asyncio
async def test_send_user_settings_flow_persists_flow_message() -> None:
    user = User(id=42, wa_id="255700000334", name="Teacher")
    flow_strings = {
        "personal_settings_header": "Update profile",
        "personal_settings_body": "Change your details",
        "personal_settings_cta": "Update",
    }

    with (
        patch("app.services.flow_service.settings.onboarding_flow_id", "flow-999"),
        patch(
            "app.services.flow_service.strings.get_category",
            return_value=flow_strings,
        ),
        patch(
            "app.services.flow_service.futil.send_whatsapp_flow_message",
            AsyncMock(),
        ),
        patch.object(
            FlowService,
            "_persist_flow_message",
            AsyncMock(),
        ) as mock_persist_flow_message,
    ):
        service = FlowService()
        await service.send_user_settings_flow(user)

    assert mock_persist_flow_message.await_args.kwargs == {
        "user": user,
        "flow_id": "flow-999",
        "header_text": "Update profile",
        "body_text": "Change your details",
    }


@pytest.mark.asyncio
async def test_send_subjects_classes_flow_persists_flow_message() -> None:
    user = User(id=43, wa_id="255700000335", name="Teacher")
    flow_strings = {
        "subjects_classes_flow_header": "Subjects",
        "subjects_classes_flow_body": "Choose subjects and classes",
        "subjects_classes_flow_cta": "Continue",
    }

    with (
        patch(
            "app.services.flow_service.settings.subjects_classes_flow_id",
            "flow-subjects-1",
        ),
        patch(
            "app.services.flow_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.flow_service.strings.get_category",
            return_value=flow_strings,
        ),
        patch.object(
            FlowService,
            "_build_subject_selection_screen_data",
            AsyncMock(return_value={}),
        ),
        patch(
            "app.services.flow_service.futil.create_flow_response_payload",
            return_value={"screen": "select_subject", "data": {}},
        ),
        patch(
            "app.services.flow_service.futil.send_whatsapp_flow_message",
            AsyncMock(),
        ),
        patch.object(
            FlowService,
            "_persist_flow_message",
            AsyncMock(),
        ) as mock_persist_flow_message,
    ):
        service = FlowService()
        await service.send_subjects_classes_flow(user)

    assert mock_persist_flow_message.await_args.kwargs == {
        "user": user,
        "flow_id": "flow-subjects-1",
        "header_text": "Subjects",
        "body_text": "Choose subjects and classes",
    }


@pytest.mark.asyncio
async def test_subjects_classes_load_action_returns_select_classes_screen() -> None:
    user = User(id=101, wa_id="255700009999", name="Teacher")
    service = FlowService()
    payload = {
        "data": {
            "component_action": "load_subject_classes",
            "selected_subject_id": "4",
        }
    }
    expected_payload = {"screen": "select_classes", "data": {"any": "data"}}
    encrypted_response = PlainTextResponse("encrypted", status_code=200)

    with (
        patch.object(
            service,
            "_build_subject_classes_screen_data",
            AsyncMock(return_value={"any": "data"}),
        ) as mock_build_classes_data,
        patch(
            "app.services.flow_service.futil.create_flow_response_payload",
            return_value=expected_payload,
        ) as mock_create_payload,
        patch.object(
            service,
            "process_response",
            AsyncMock(return_value=encrypted_response),
        ) as mock_process_response,
    ):
        response = await service.handle_subjects_classes_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=b"aes-key",
            initial_vector="iv",
            background_tasks=BackgroundTasks(),
        )

    mock_build_classes_data.assert_awaited_once_with(user=user, subject_id=4)
    mock_create_payload.assert_called_once_with(
        screen=service._FLOW_SCREEN_SELECT_CLASSES,
        data={"any": "data"},
    )
    mock_process_response.assert_awaited_once_with(expected_payload, b"aes-key", "iv")
    assert response == encrypted_response


@pytest.mark.asyncio
async def test_subjects_classes_save_action_parses_ids_and_returns_subject_screen() -> (
    None
):
    user = User(id=202, wa_id="255700008888", name="Teacher")
    service = FlowService()
    payload = {
        "data": {
            "component_action": "save_subject_classes",
            "selected_subject_id": "12",
            "selected_class_ids": ["71", "72"],
        }
    }
    expected_payload = {"screen": "select_subject", "data": {"saved": True}}
    encrypted_response = PlainTextResponse("encrypted", status_code=200)

    with (
        patch.object(
            service,
            "_save_subject_selection",
            AsyncMock(return_value=user),
        ) as mock_save_subject_selection,
        patch.object(
            service,
            "_build_subject_selection_screen_data",
            AsyncMock(return_value={"saved": True}),
        ),
        patch(
            "app.services.flow_service.futil.create_flow_response_payload",
            return_value=expected_payload,
        ),
        patch.object(
            service,
            "process_response",
            AsyncMock(return_value=encrypted_response),
        ),
    ):
        response = await service.handle_subjects_classes_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=b"aes-key",
            initial_vector="iv",
            background_tasks=BackgroundTasks(),
        )

    mock_save_subject_selection.assert_awaited_once_with(
        user=user,
        subject_id=12,
        selected_class_ids=[71, 72],
    )
    assert response == encrypted_response


@pytest.mark.asyncio
async def test_subjects_classes_complete_action_requires_at_least_one_class() -> None:
    user = User(id=303, wa_id="255700007777", name="Teacher")
    service = FlowService()
    payload = {"data": {"component_action": "complete_subject_configuration"}}

    with patch.object(
        service,
        "_finalize_subject_configuration",
        AsyncMock(side_effect=ValueError("No classes selected for any subject")),
    ):
        response = await service.handle_subjects_classes_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=b"aes-key",
            initial_vector="iv",
            background_tasks=BackgroundTasks(),
        )

    assert response.status_code == 422
    assert b"No classes selected for any subject" in response.body


@pytest.mark.asyncio
async def test_persist_visible_assistant_message_persists_visible_flag() -> None:
    user = User(id=91, wa_id="255700001111", name="Teacher")
    service = FlowService()

    with patch(
        "app.services.flow_service.db.create_new_message_by_fields",
        AsyncMock(),
    ) as mock_create_message_by_fields:
        await service._persist_visible_assistant_message(user, "Flow visible message")

    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Flow visible message",
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_update_user_profile_failure_persists_error_message() -> None:
    user = User(id=55, wa_id="255700000888", name="Teacher")
    service = FlowService()

    with (
        patch(
            "app.services.flow_service.db.update_user",
            AsyncMock(side_effect=Exception("db failed")),
        ),
        patch(
            "app.services.flow_service.strings.get_string",
            return_value="General error",
        ),
        patch(
            "app.services.flow_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ) as mock_persist_visible,
    ):
        await service.update_user_profile(user, data={}, is_updating=False)

    mock_send_message.assert_awaited_once_with(user.wa_id, "General error")
    mock_persist_visible.assert_awaited_once_with(user, "General error")


@pytest.mark.asyncio
async def test_persist_flow_message_builds_visible_payload() -> None:
    user = User(id=77, wa_id="255700000777", name="Teacher")
    service = FlowService()

    with patch.object(
        service,
        "_persist_visible_assistant_message",
        AsyncMock(),
    ) as mock_persist_visible:
        await service._persist_flow_message(
            user=user,
            flow_id="flow-abc",
            header_text="Header",
            body_text="Body",
        )

    mock_persist_visible.assert_awaited_once_with(
        user,
        "[FLOW_SENT] id=flow-abc | header=Header | body=Body",
    )
