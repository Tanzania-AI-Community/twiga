from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import PlainTextResponse

import app.database.db as db
import app.database.enums as enums
from app.database.models import Class, Subject, User
from app.services.flows.flow_service import FlowService


class _DummyRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_send_personal_and_school_info_flow_persists_flow_message() -> None:
    user = User(id=41, wa_id="255700000333", name="Teacher")
    flow_strings = {
        "start_onboarding_header": "Welcome",
        "start_onboarding_body": "Please complete your profile",
        "start_onboarding_cta": "Start",
    }

    with (
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.settings.onboarding_flow_id",
            "flow-123",
        ),
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.strings.get_category",
            return_value=flow_strings,
        ),
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.whatsapp_client.send_whatsapp_flow_message",
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
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.settings.onboarding_flow_id",
            "flow-999",
        ),
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.strings.get_category",
            return_value=flow_strings,
        ),
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.whatsapp_client.send_whatsapp_flow_message",
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
    service = FlowService()
    flow_strings = {
        "subjects_classes_flow_header": "Subjects",
        "subjects_classes_flow_body": "Choose subjects and classes",
        "subjects_classes_flow_cta": "Continue",
    }

    with (
        patch(
            "app.services.flows.handlers.subjects_classes_flow_handler.settings.subjects_classes_flow_id",
            "flow-subjects-1",
        ),
        patch(
            "app.services.flows.handlers.subjects_classes_flow_handler.strings.get_category",
            return_value=flow_strings,
        ),
        patch.object(
            service._subjects_classes_flow_handler,
            "_build_subject_selection_screen_data",
            AsyncMock(return_value={}),
        ),
        patch.object(
            service._subjects_classes_flow_handler,
            "_refresh_user_by_wa_id",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.flows.flow_service.flow_utils.create_flow_response_payload",
            return_value={"screen": "select_subject", "data": {}},
        ),
        patch(
            "app.services.flows.handlers.subjects_classes_flow_handler.whatsapp_client.send_whatsapp_flow_message",
            AsyncMock(),
        ),
        patch.object(
            FlowService,
            "_persist_flow_message",
            AsyncMock(),
        ) as mock_persist_flow_message,
    ):
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
            "selected_subject_ids": ["4"],
        }
    }
    expected_payload = {"screen": "select_classes", "data": {"any": "data"}}
    encrypted_response = PlainTextResponse("encrypted", status_code=200)

    with (
        patch.object(
            service._subjects_classes_flow_handler,
            "_build_subject_classes_screen_data",
            AsyncMock(return_value={"any": "data"}),
        ) as mock_build_classes_data,
        patch(
            "app.services.flows.flow_service.flow_utils.create_flow_response_payload",
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

    mock_build_classes_data.assert_awaited_once_with(
        user=user, selected_subject_ids=[4]
    )
    mock_create_payload.assert_called_once_with(
        screen=service._subjects_classes_flow_handler._FLOW_SCREEN_SELECT_CLASSES,
        data={"any": "data"},
    )
    mock_process_response.assert_awaited_once_with(expected_payload, b"aes-key", "iv")
    assert response == encrypted_response


@pytest.mark.asyncio
async def test_subjects_classes_back_action_returns_select_subject_screen() -> None:
    user = User(id=102, wa_id="255700009998", name="Teacher")
    service = FlowService()
    payload = {"action": "back", "data": {}}
    expected_payload = {"screen": "select_subject", "data": {"subject_options": []}}
    encrypted_response = PlainTextResponse("encrypted", status_code=200)

    with (
        patch.object(
            service._subjects_classes_flow_handler,
            "_build_subject_selection_screen_data",
            AsyncMock(return_value={"subject_options": []}),
        ) as mock_build_subject_data,
        patch(
            "app.services.flows.flow_service.flow_utils.create_flow_response_payload",
            return_value=expected_payload,
        ) as mock_create_payload,
        patch.object(
            service,
            "process_response",
            AsyncMock(return_value=encrypted_response),
        ) as mock_process_response,
    ):
        response = await service.handle_subjects_classes_back_action(
            user=user,
            payload=payload,
            aes_key=b"aes-key",
            initial_vector="iv",
            background_tasks=BackgroundTasks(),
        )

    mock_build_subject_data.assert_awaited_once_with(user)
    mock_create_payload.assert_called_once_with(
        screen=service._subjects_classes_flow_handler._FLOW_SCREEN_SELECT_SUBJECT,
        data={"subject_options": []},
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
            service._subjects_classes_flow_handler,
            "_save_subject_selection",
            AsyncMock(return_value=user),
        ) as mock_save_subject_selection,
        patch.object(
            service._subjects_classes_flow_handler,
            "_build_subject_selection_screen_data",
            AsyncMock(return_value={"saved": True}),
        ),
        patch(
            "app.services.flows.flow_service.flow_utils.create_flow_response_payload",
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
async def test_subjects_classes_complete_action_requires_subject_selection() -> None:
    user = User(id=303, wa_id="255700007777", name="Teacher")
    service = FlowService()
    payload = {"data": {"component_action": "complete_subject_configuration"}}

    response = await service.handle_subjects_classes_data_exchange_action(
        user=user,
        payload=payload,
        aes_key=b"aes-key",
        initial_vector="iv",
        background_tasks=BackgroundTasks(),
    )

    assert response.status_code == 422
    assert b"No subject selected" in response.body


@pytest.mark.asyncio
async def test_subjects_classes_complete_action_requires_class_selection() -> None:
    user = User(id=304, wa_id="255700007778", name="Teacher")
    service = FlowService()
    payload = {
        "data": {
            "component_action": "complete_subject_configuration",
            "selected_subject_ids": ["1"],
            "selected_class_ids": [],
        }
    }

    response = await service.handle_subjects_classes_data_exchange_action(
        user=user,
        payload=payload,
        aes_key=b"aes-key",
        initial_vector="iv",
        background_tasks=BackgroundTasks(),
    )

    assert response.status_code == 422
    assert b"No classes selected for selected subjects" in response.body


@pytest.mark.asyncio
async def test_subjects_classes_complete_action_uses_grouped_class_fields() -> None:
    user = User(
        id=305,
        wa_id="255700007779",
        name="Teacher",
        onboarding_state=enums.OnboardingState.completed,
    )
    service = FlowService()
    payload = {
        "flow_token": "flow-token",
        "data": {
            "component_action": "complete_subject_configuration",
            "selected_subject_ids": ["1", "2"],
            "selected_class_ids": [],
            "subject1_selected_class_ids": ["101", "102"],
            "subject2_selected_class_ids": ["201"],
            "subject3_selected_class_ids": [],
        },
    }
    encrypted_response = PlainTextResponse("encrypted", status_code=200)

    with (
        patch.object(
            service._subjects_classes_flow_handler,
            "_save_multi_subject_class_selection",
            AsyncMock(),
        ) as mock_save_selection,
        patch.object(
            service._subjects_classes_flow_handler,
            "_finalize_subject_configuration",
            AsyncMock(return_value=user),
        ),
        patch.object(
            service,
            "_create_flow_response_payload",
            return_value={"screen": "SUCCESS", "data": {}, "flow_token": "flow-token"},
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

    mock_save_selection.assert_awaited_once_with(
        user=user,
        selected_subject_ids=[1, 2],
        selected_class_ids=[101, 102, 201],
    )
    mock_create_payload.assert_called_once_with(
        screen="SUCCESS",
        data={},
        encrypted_flow_token="flow-token",
    )
    mock_process_response.assert_awaited_once()
    assert response is encrypted_response


def test_parse_grouped_class_ids_collects_unique_ids_in_subject_order() -> None:
    service = FlowService()

    grouped_ids = service._subjects_classes_flow_handler._parse_grouped_class_ids(
        {
            "subject1_selected_class_ids": ["11", "12", "12"],
            "subject2_selected_class_ids": ["21"],
            "subject3_selected_class_ids": ["12", "31"],
        }
    )

    assert grouped_ids == [11, 12, 21, 31]


@pytest.mark.asyncio
async def test_handle_flow_request_dispatches_data_exchange_to_flow_handler() -> None:
    user = User(id=500, wa_id="255700005000", name="Teacher")
    service = FlowService()
    expected_response = PlainTextResponse("encrypted", status_code=200)
    mock_flow_handler = AsyncMock(return_value=expected_response)
    service.data_exchange_action_handlers = {"flow-subjects": mock_flow_handler}
    payload = {"action": "data_exchange", "flow_token": "token", "data": {}}

    with (
        patch.object(
            service,
            "_decrypt_flow_request",
            AsyncMock(return_value=(payload, b"aes-key", "iv")),
        ),
        patch.object(
            service,
            "_decrypt_flow_token",
            return_value=(user.wa_id, "flow-subjects"),
        ),
        patch.object(
            db,
            "get_user_by_waid",
            AsyncMock(return_value=user),
        ),
    ):
        response = await service.handle_flow_request(
            _DummyRequest(body={"encrypted_flow_data": "payload"}),
            BackgroundTasks(),
        )

    assert response is expected_response
    called_args = mock_flow_handler.await_args.args
    assert called_args[0] == user
    assert called_args[1] == payload
    assert called_args[2] == b"aes-key"
    assert called_args[3] == "iv"
    assert isinstance(called_args[4], BackgroundTasks)


@pytest.mark.asyncio
async def test_handle_flow_request_unknown_init_falls_back_to_unknown_flow() -> None:
    user = User(id=501, wa_id="255700005001", name="Teacher")
    service = FlowService()
    expected_response = PlainTextResponse("encrypted", status_code=200)
    payload = {"action": "INIT", "flow_token": "token", "data": {}}

    with (
        patch.object(
            service,
            "_decrypt_flow_request",
            AsyncMock(return_value=(payload, b"aes-key", "iv")),
        ),
        patch.object(
            service,
            "_decrypt_flow_token",
            return_value=(user.wa_id, "unknown-flow-id"),
        ),
        patch.object(
            db,
            "get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch.object(
            service,
            "handle_unknown_flow",
            AsyncMock(return_value=expected_response),
        ) as mock_unknown_flow,
    ):
        response = await service.handle_flow_request(
            _DummyRequest(body={"encrypted_flow_data": "payload"}),
            BackgroundTasks(),
        )

    assert response is expected_response
    mock_unknown_flow.assert_awaited_once_with(user, payload, b"aes-key", "iv")


@pytest.mark.asyncio
async def test_handle_flow_request_dispatches_back_to_flow_handler() -> None:
    user = User(id=502, wa_id="255700005002", name="Teacher")
    service = FlowService()
    expected_response = PlainTextResponse("encrypted", status_code=200)
    mock_back_handler = AsyncMock(return_value=expected_response)
    service.back_action_handlers = {"flow-subjects": mock_back_handler}
    payload = {"action": "BACK", "flow_token": "token", "data": {}}

    with (
        patch.object(
            service,
            "_decrypt_flow_request",
            AsyncMock(return_value=(payload, b"aes-key", "iv")),
        ),
        patch.object(
            service,
            "_decrypt_flow_token",
            return_value=(user.wa_id, "flow-subjects"),
        ),
        patch.object(
            db,
            "get_user_by_waid",
            AsyncMock(return_value=user),
        ),
    ):
        response = await service.handle_flow_request(
            _DummyRequest(body={"encrypted_flow_data": "payload"}),
            BackgroundTasks(),
        )

    assert response is expected_response
    called_args = mock_back_handler.await_args.args
    assert called_args[0] == user
    assert called_args[1] == payload
    assert called_args[2] == b"aes-key"
    assert called_args[3] == "iv"
    assert isinstance(called_args[4], BackgroundTasks)


@pytest.mark.asyncio
async def test_handle_flow_request_dispatches_lowercase_back_to_flow_handler() -> None:
    user = User(id=503, wa_id="255700005003", name="Teacher")
    service = FlowService()
    expected_response = PlainTextResponse("encrypted", status_code=200)
    mock_back_handler = AsyncMock(return_value=expected_response)
    service.back_action_handlers = {"flow-subjects": mock_back_handler}
    payload = {"action": "back", "flow_token": "token", "data": {}}

    with (
        patch.object(
            service,
            "_decrypt_flow_request",
            AsyncMock(return_value=(payload, b"aes-key", "iv")),
        ),
        patch.object(
            service,
            "_decrypt_flow_token",
            return_value=(user.wa_id, "flow-subjects"),
        ),
        patch.object(
            db,
            "get_user_by_waid",
            AsyncMock(return_value=user),
        ),
    ):
        response = await service.handle_flow_request(
            _DummyRequest(body={"encrypted_flow_data": "payload"}),
            BackgroundTasks(),
        )

    assert response is expected_response
    called_args = mock_back_handler.await_args.args
    assert called_args[0] == user
    assert called_args[1] == payload
    assert called_args[2] == b"aes-key"
    assert called_args[3] == "iv"
    assert isinstance(called_args[4], BackgroundTasks)


@pytest.mark.asyncio
async def test_build_subject_option_prefixes_emoji_from_display_format() -> None:
    service = FlowService()
    subject = Subject(id=1, name=enums.SubjectName.geography)

    option = service._subjects_classes_flow_handler._build_subject_option(subject)

    assert option == {"id": "1", "title": "Geography 🌎"}


@pytest.mark.asyncio
async def test_build_subject_selection_screen_data_respects_chips_limits() -> None:
    service = FlowService()
    user = User(id=405, wa_id="255700006665", name="Teacher")
    subjects = [
        Subject(
            id=index + 1,
            name=subject_name,
            subject_classes=[
                Class(
                    id=1000 + index,
                    subject_id=index + 1,
                    grade_level=enums.GradeLevel.os1,
                    status=enums.SubjectClassStatus.active,
                )
            ],
        )
        for index, subject_name in enumerate(list(enums.SubjectName)[:25])
    ]

    with patch(
        "app.services.flows.handlers.subjects_classes_flow_handler.db.read_subjects",
        AsyncMock(return_value=subjects),
    ):
        data = await service._subjects_classes_flow_handler._build_subject_selection_screen_data(
            user=user
        )

    assert len(data["subject_options"]) == 20
    assert all(len(option["title"]) <= 30 for option in data["subject_options"])


@pytest.mark.asyncio
async def test_build_subject_selection_screen_data_excludes_subjects_without_active_classes() -> (
    None
):
    service = FlowService()
    user = User(id=406, wa_id="255700006664", name="Teacher")
    subjects = [
        Subject(
            id=1,
            name=enums.SubjectName.geography,
            subject_classes=[
                Class(
                    id=101,
                    subject_id=1,
                    grade_level=enums.GradeLevel.os1,
                    status=enums.SubjectClassStatus.inactive,
                )
            ],
        ),
        Subject(
            id=2,
            name=enums.SubjectName.biology,
            subject_classes=[
                Class(
                    id=201,
                    subject_id=2,
                    grade_level=enums.GradeLevel.os1,
                    status=enums.SubjectClassStatus.active,
                )
            ],
        ),
        Subject(
            id=3,
            name=enums.SubjectName.history,
            subject_classes=[],
        ),
    ]

    with patch(
        "app.services.flows.handlers.subjects_classes_flow_handler.db.read_subjects",
        AsyncMock(return_value=subjects),
    ):
        data = await service._subjects_classes_flow_handler._build_subject_selection_screen_data(
            user=user
        )

    assert data["subject_options"] == [{"id": "2", "title": "Biology 🧬"}]
    assert data["selected_subject_ids"] == []
    assert data["has_subject_options"] is True


def test_build_class_option_title_keeps_form_prefix_when_truncating() -> None:
    service = FlowService()

    title = service._subjects_classes_flow_handler._build_class_option_title(
        subject_title="Information And Computer Studies",
        grade_label="Form 1",
    )

    assert len(title) <= 30
    assert title.startswith("Form 1 - ")


@pytest.mark.asyncio
async def test_build_subject_classes_screen_data_sorts_subject_level_titles() -> None:
    service = FlowService()
    user = User(id=404, wa_id="255700006666", name="Teacher")

    geography = Subject(
        id=1,
        name=enums.SubjectName.geography,
        subject_classes=[
            Class(
                id=101,
                subject_id=1,
                grade_level=enums.GradeLevel.os2,
                status=enums.SubjectClassStatus.active,
            ),
            Class(
                id=102,
                subject_id=1,
                grade_level=enums.GradeLevel.os1,
                status=enums.SubjectClassStatus.active,
            ),
        ],
    )
    biology = Subject(
        id=2,
        name=enums.SubjectName.biology,
        subject_classes=[
            Class(
                id=201,
                subject_id=2,
                grade_level=enums.GradeLevel.os1,
                status=enums.SubjectClassStatus.active,
            ),
        ],
    )

    with patch(
        "app.services.flows.handlers.subjects_classes_flow_handler.db.read_subjects",
        AsyncMock(return_value=[geography, biology]),
    ):
        data = await service._subjects_classes_flow_handler._build_subject_classes_screen_data(
            user=user, selected_subject_ids=[1, 2]
        )

    assert data["classes_for_subject"] == [
        {"id": "201", "title": "Form 1 - Biology 🧬"},
        {"id": "102", "title": "Form 1 - Geography 🌎"},
        {"id": "101", "title": "Form 2 - Geography 🌎"},
    ]
    assert data["subject1_title"] == "Biology 🧬"
    assert data["subject1_class_options"] == [{"id": "201", "title": "Form 1"}]
    assert data["subject2_title"] == "Geography 🌎"
    assert data["subject2_class_options"] == [
        {"id": "102", "title": "Form 1"},
        {"id": "101", "title": "Form 2"},
    ]
    assert data["subject3_title"] == ""
    assert data["subject3_class_options"] == []


def test_parse_subject_ids_enforces_max_limit() -> None:
    service = FlowService()

    with pytest.raises(ValueError, match="up to 3 subjects"):
        service._subjects_classes_flow_handler._parse_subject_ids(["1", "2", "3", "4"])


def test_parse_class_ids_enforces_max_limit() -> None:
    service = FlowService()

    with pytest.raises(ValueError, match="up to 10 classes"):
        service._subjects_classes_flow_handler._parse_class_ids(
            [str(i) for i in range(1, 12)]
        )


@pytest.mark.asyncio
async def test_persist_visible_assistant_message_persists_visible_flag() -> None:
    user = User(id=91, wa_id="255700001111", name="Teacher")
    service = FlowService()

    with patch(
        "app.services.flows.flow_service.db.create_new_message_by_fields",
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
            "app.services.flows.handlers.onboarding_flow_handler.db.update_user",
            AsyncMock(side_effect=Exception("db failed")),
        ),
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.strings.get_string",
            return_value="General error",
        ),
        patch(
            "app.services.flows.handlers.onboarding_flow_handler.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch.object(
            service,
            "_persist_visible_assistant_message",
            AsyncMock(),
        ) as mock_persist_visible,
    ):
        await service._onboarding_flow_handler.update_user_profile(
            user, data={}, is_updating=False
        )

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
