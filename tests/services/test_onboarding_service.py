from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

import app.database.enums as enums
from app.database.models import User
from app.services.onboarding_service import OnboardingHandler


@pytest.mark.asyncio
async def test_handle_completed_persists_pending_approval_as_visible_message() -> None:
    user = User(id=61, wa_id="255700000444", name="Teacher")
    service = OnboardingHandler()

    with (
        patch(
            "app.services.onboarding_service.strings.get_string",
            return_value="Pending approval",
        ),
        patch(
            "app.services.onboarding_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.onboarding_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        await service.handle_completed(user)

    mock_send_message.assert_awaited_once_with(user.wa_id, "Pending approval")
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Pending approval",
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_handle_default_persists_general_error_as_visible_message() -> None:
    user = User(id=62, wa_id="255700000445", name="Teacher")
    service = OnboardingHandler()

    with (
        patch(
            "app.services.onboarding_service.strings.get_string",
            return_value="General error",
        ),
        patch(
            "app.services.onboarding_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.onboarding_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        await service.handle_default(user)

    mock_send_message.assert_awaited_once_with(user.wa_id, "General error")
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "General error",
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_handle_new_saves_name_and_sends_subjects_flow() -> None:
    birthday = date(1990, 1, 1)
    user = User(
        id=70,
        wa_id="255700000470",
        name=None,
        onboarding_state=enums.OnboardingState.new,
        birthday=birthday,
        region="Dar es Salaam",
        school_name="Twiga School",
    )
    service = OnboardingHandler()

    with (
        patch(
            "app.services.onboarding_service.db.update_user",
            AsyncMock(return_value=user),
        ) as mock_update_user,
        patch.object(
            service.flow_client,
            "send_subjects_classes_flow",
            AsyncMock(),
        ) as mock_send_subjects_flow,
        patch(
            "app.services.onboarding_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
    ):
        await service.handle_new(user, "  Amina  ")

    assert user.name == "Amina"
    assert user.onboarding_state == enums.OnboardingState.personal_info_submitted
    assert user.birthday == birthday
    assert user.region == "Dar es Salaam"
    assert user.school_name == "Twiga School"
    mock_update_user.assert_awaited_once_with(user)
    mock_send_subjects_flow.assert_awaited_once_with(user)
    mock_send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["   ", "A" * 51])
async def test_handle_new_rejects_blank_or_too_long_name(reply: str) -> None:
    user = User(
        id=71,
        wa_id="255700000471",
        name=None,
        onboarding_state=enums.OnboardingState.new,
    )
    service = OnboardingHandler()

    with (
        patch(
            "app.services.onboarding_service.strings.get_string",
            return_value="Please send a shorter name",
        ),
        patch(
            "app.services.onboarding_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.onboarding_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
        patch(
            "app.services.onboarding_service.db.update_user",
            AsyncMock(),
        ) as mock_update_user,
        patch.object(
            service.flow_client,
            "send_subjects_classes_flow",
            AsyncMock(),
        ) as mock_send_subjects_flow,
    ):
        await service.handle_new(user, reply)

    assert user.name is None
    assert user.onboarding_state == enums.OnboardingState.new
    mock_update_user.assert_not_awaited()
    mock_send_subjects_flow.assert_not_awaited()
    mock_send_message.assert_awaited_once_with(user.wa_id, "Please send a shorter name")
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Please send a shorter name",
        "is_present_in_conversation": True,
    }
