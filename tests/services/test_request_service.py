from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

import app.database.enums as enums
from app.database.models import Message, User
from app.services import request_service
from app.utils.whatsapp_utils import RequestType


class _DummyRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_handle_request_awaits_flow_complete_handler() -> None:
    body = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    request = _DummyRequest(body)
    expected_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch(
            "app.services.request_service.get_request_type",
            return_value=RequestType.FLOW_COMPLETE,
        ),
        patch("app.services.request_service.record_whatsapp_event"),
        patch(
            "app.services.request_service.whatsapp_client.handle_flow_message_complete",
            AsyncMock(return_value=expected_response),
        ) as mock_flow_complete_handler,
    ):
        response = await request_service.handle_request(request)

    assert response is expected_response
    mock_flow_complete_handler.assert_awaited_once_with(body)


@pytest.mark.asyncio
async def test_handle_chat_message_persists_inbound_message_and_routes_active() -> None:
    user = User(
        id=7,
        wa_id="255700000000",
        name="Teacher",
        state=enums.UserState.active,
    )
    persisted_message = Message(
        user_id=user.id,
        role=enums.MessageRole.user,
        content="Hello",
        is_present_in_conversation=True,
    )

    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.db.create_new_message_by_fields",
            AsyncMock(return_value=persisted_message),
        ) as mock_create_new_message_by_fields,
        patch(
            "app.services.request_service.state_client._handle_rate_limiting",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.request_service.state_client.handle_active",
            AsyncMock(
                return_value=JSONResponse(content={"status": "ok"}, status_code=200)
            ),
        ) as mock_handle_active,
    ):
        response = await request_service.handle_chat_message(
            phone_number=user.wa_id,
            message_info={"extracted_content": "Hello"},
        )

    assert response.status_code == 200
    assert mock_create_new_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.user,
        "content": "Hello",
        "is_present_in_conversation": True,
    }
    mock_handle_active.assert_awaited_once_with(
        user,
        {"extracted_content": "Hello"},
        persisted_message,
    )


@pytest.mark.asyncio
async def test_handle_chat_message_persists_inbound_message_before_rate_limit_return() -> (
    None
):
    user = User(
        id=8,
        wa_id="255700000001",
        name="Teacher",
        state=enums.UserState.active,
    )
    rate_limit_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.db.create_new_message_by_fields",
            AsyncMock(
                return_value=Message(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content="Hi",
                    is_present_in_conversation=True,
                )
            ),
        ) as mock_create_new_message_by_fields,
        patch(
            "app.services.request_service.state_client._handle_rate_limiting",
            AsyncMock(return_value=rate_limit_response),
        ),
        patch(
            "app.services.request_service.state_client.handle_active",
            AsyncMock(),
        ) as mock_handle_active,
    ):
        response = await request_service.handle_chat_message(
            phone_number=user.wa_id,
            message_info={"extracted_content": "Hi"},
        )

    assert response is rate_limit_response
    mock_create_new_message_by_fields.assert_awaited_once()
    mock_handle_active.assert_not_awaited()
