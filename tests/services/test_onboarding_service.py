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
