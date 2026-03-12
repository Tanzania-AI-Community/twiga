from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Environment
from app.database.enums import MessageRole, UserState
from app.database.models import Message, User
from app.services.state_service import StateHandler


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_handle_blocked_skips_duplicate_visible_message() -> None:
    user = User(id=1, wa_id="255700000001", name="Teacher", state=UserState.blocked)
    service = StateHandler()
    blocked_text = "You are blocked"

    with (
        patch(
            "app.services.state_service.strings.get_string",
            return_value=blocked_text,
        ),
        patch(
            "app.services.state_service.db.get_latest_user_message_by_role",
            AsyncMock(
                return_value=Message(
                    user_id=user.id,
                    role=MessageRole.assistant,
                    content=blocked_text,
                )
            ),
        ),
        patch(
            "app.services.state_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.state_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        response = await service.handle_blocked(user)

    assert response.status_code == 200
    mock_send_message.assert_not_awaited()
    mock_create_message_by_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_rate_limited_persists_visible_message_when_not_duplicate() -> (
    None
):
    user = User(id=2, wa_id="255700000002", name="Teacher", state=UserState.active)
    service = StateHandler()
    rate_limit_text = "You are rate limited"

    with (
        patch(
            "app.services.state_service.strings.get_string",
            return_value=rate_limit_text,
        ),
        patch(
            "app.services.state_service.db.get_latest_user_message_by_role",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.state_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.state_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
        patch("app.services.state_service.record_messages_generated"),
    ):
        response = await service.handle_rate_limited(user)

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, rate_limit_text)
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": MessageRole.assistant,
        "content": rate_limit_text,
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_handle_in_review_user_persists_visible_message_when_not_duplicate() -> (
    None
):
    user = User(id=3, wa_id="255700000003", name="Teacher", state=UserState.in_review)
    service = StateHandler()
    pending_text = "Pending approval"

    with (
        patch(
            "app.services.state_service.strings.get_string",
            return_value=pending_text,
        ),
        patch(
            "app.services.state_service.db.get_latest_user_message_by_role",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.state_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.state_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        response = await service.handle_in_review_user(user)

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, pending_text)
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": MessageRole.assistant,
        "content": pending_text,
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_handle_new_approved_user_in_production_persists_visible_template_message() -> (
    None
):
    user = User(id=4, wa_id="255700000004", name="Teacher", state=UserState.approved)
    service = StateHandler()

    with (
        patch(
            "app.services.state_service.db.update_user",
            AsyncMock(return_value=user),
        ),
        patch("app.config.settings.environment", Environment.PRODUCTION),
        patch("app.config.settings.welcome_template_id", "welcome-template-1"),
        patch(
            "app.services.state_service.whatsapp_client.send_template_message",
            AsyncMock(),
        ) as mock_send_template_message,
        patch(
            "app.services.state_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
        patch(
            "app.services.state_service.flow_client.send_personal_and_school_info_flow",
            AsyncMock(),
        ) as mock_send_onboarding_flow,
    ):
        response = await service.handle_new_approved_user(user)

    assert response.status_code == 200
    mock_send_template_message.assert_awaited_once_with(
        user.wa_id,
        "welcome-template-1",
        language_code="en_US",
    )
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": MessageRole.assistant,
        "content": "Welcome template sent: welcome-template-1",
        "is_present_in_conversation": True,
    }
    mock_send_onboarding_flow.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_handle_new_dummy_persists_visible_onboarding_override() -> None:
    user = User(id=5, wa_id="255700000005", name="Teacher", state=UserState.in_review)
    service = StateHandler()

    with (
        patch(
            "app.services.state_service.db.get_class_ids_from_class_info",
            AsyncMock(return_value=[1]),
        ),
        patch(
            "app.services.state_service.db.update_user",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.state_service.db.assign_teacher_to_classes",
            AsyncMock(),
        ),
        patch(
            "app.services.state_service.strings.get_string",
            return_value="Onboarding override",
        ),
        patch(
            "app.services.state_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.state_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        response = await service.handle_new_dummy(user)

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, "Onboarding override")
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": MessageRole.assistant,
        "content": "Onboarding override",
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_handle_new_user_registration_in_production_persists_visible_message() -> (
    None
):
    service = StateHandler()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    async def _refresh_user(user: User) -> None:
        user.id = 501

    session.refresh = AsyncMock(side_effect=_refresh_user)

    with (
        patch(
            "app.database.engine.get_session",
            return_value=_SessionContext(session),
        ),
        patch("app.config.settings.environment", Environment.PRODUCTION),
        patch(
            "app.services.state_service.strings.get_string",
            return_value="Registration started",
        ),
        patch(
            "app.services.state_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.state_service.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        response = await service.handle_new_user_registration(
            phone_number="255700000006",
            message_info={"extracted_content": "Hi"},
        )

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with("255700000006", "Registration started")
    assert mock_create_message_by_fields.await_args.kwargs == {
        "user_id": 501,
        "role": MessageRole.assistant,
        "content": "Registration started",
        "is_present_in_conversation": True,
    }
