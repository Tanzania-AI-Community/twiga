from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.clients.agent_modes import AgentMode
from app.database.enums import (
    GradeLevel,
    MessageRole,
    OnboardingState,
    SubjectName,
    UserState,
)
from app.database.models import Class, Message, Subject, TeacherClass, User
from app.services.onboarding_service import OnboardingService
from app.utils.string_manager import StringCategory, strings

INTRO = strings.get_string(StringCategory.ONBOARDING, "intro")
TEXT_ONLY = strings.get_string(StringCategory.ONBOARDING, "text_only")


def _user(
    name: str | None = None,
    with_class: bool = False,
    state: UserState = UserState.onboarding,
    onboarding_state: OnboardingState = OnboardingState.new,
) -> User:
    taught_classes = []
    if with_class:
        taught_classes = [
            TeacherClass(
                teacher_id=5,
                class_id=102,
                class_=Class(
                    id=102,
                    subject_id=1,
                    grade_level=GradeLevel.os2,
                    subject_=Subject(id=1, name=SubjectName.geography),
                ),
            )
        ]
    return User(
        id=5,
        wa_id="255700000005",
        name=name,
        state=state,
        onboarding_state=onboarding_state,
        taught_classes=taught_classes,
    )


def _message_info(message_type: str, content: str = "hello") -> dict:
    return {"message": {"type": message_type}, "extracted_content": content}


@dataclass
class Mocks:
    send_message: AsyncMock
    create_message: AsyncMock
    get_user: AsyncMock
    update_user: AsyncMock
    generate_and_deliver: AsyncMock


@pytest.fixture
def mocks() -> Iterator[Mocks]:
    module = "app.services.onboarding_service"
    with (
        patch(
            f"{module}.whatsapp_client.send_message", AsyncMock(return_value=True)
        ) as send_message,
        patch(f"{module}.db.create_new_message_by_fields", AsyncMock()) as create,
        patch(f"{module}.db.get_user_by_waid", AsyncMock()) as get_user,
        patch(f"{module}.db.update_user", AsyncMock()) as update_user,
        patch(
            f"{module}.messaging_client.generate_and_deliver", AsyncMock()
        ) as generate_and_deliver,
    ):
        yield Mocks(send_message, create, get_user, update_user, generate_and_deliver)


# --- intro ------------------------------------------------------------------


async def test_send_intro_sends_and_records_the_intro(mocks: Mocks) -> None:
    user = _user()

    assert await OnboardingService().send_intro(user) is True

    mocks.send_message.assert_awaited_once_with(user.wa_id, INTRO)
    assert mocks.create_message.await_args.kwargs == {
        "user_id": user.id,
        "role": MessageRole.assistant,
        "content": INTRO,
        "is_present_in_conversation": True,
    }


def test_intro_asks_for_name_subjects_and_forms_and_keeps_privacy_note() -> None:
    assert "What should I call you" in INTRO
    assert "subjects and forms" in INTRO
    assert "improve Twiga" in INTRO


async def test_failed_send_is_not_recorded(mocks: Mocks) -> None:
    mocks.send_message.return_value = False

    assert await OnboardingService().send_intro(_user()) is False

    mocks.create_message.assert_not_awaited()


# --- message routing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("message_type", "content"),
    [
        ("text", "my name is Luke Nuru"),
        ("audio", "I teach geography in form two"),  # transcribed voice note
        ("text", "settings"),  # answered by the model, not a menu
    ],
)
async def test_text_and_voice_go_to_the_agent_in_onboarding_mode(
    mocks: Mocks, message_type: str, content: str
) -> None:
    user = _user()
    user_message = Message(user_id=5, role=MessageRole.user, content=content)
    mocks.get_user.return_value = _user()

    response = await OnboardingService().handle_message(
        user, _message_info(message_type, content), user_message
    )

    assert response.status_code == 200
    mocks.generate_and_deliver.assert_awaited_once_with(
        user, user_message, mode=AgentMode.onboarding
    )
    mocks.get_user.assert_awaited_once()  # progress checked after the turn


@pytest.mark.parametrize("message_type", ["image", "sticker", "interactive"])
async def test_other_message_types_ask_for_text(
    mocks: Mocks, message_type: str
) -> None:
    user = _user()

    await OnboardingService().handle_message(
        user,
        _message_info(message_type),
        Message(user_id=5, role=MessageRole.user, content="x"),
    )

    mocks.generate_and_deliver.assert_not_awaited()
    mocks.send_message.assert_awaited_once_with(user.wa_id, TEXT_ONLY)


# --- completion gate ---------------------------------------------------------


async def test_name_only_marks_personal_info_submitted(mocks: Mocks) -> None:
    fresh = _user(name="Luke Nuru")
    mocks.get_user.return_value = fresh

    assert await OnboardingService().update_progress(_user()) is False

    assert fresh.onboarding_state == OnboardingState.personal_info_submitted
    assert fresh.state == UserState.onboarding
    mocks.update_user.assert_awaited_once_with(fresh)


async def test_classes_without_name_stay_in_onboarding(mocks: Mocks) -> None:
    fresh = _user(with_class=True)
    mocks.get_user.return_value = fresh

    assert await OnboardingService().update_progress(_user()) is False

    assert fresh.state == UserState.onboarding
    mocks.update_user.assert_not_awaited()  # still `new`


async def test_name_and_classes_complete_onboarding(mocks: Mocks) -> None:
    fresh = _user(name="Luke Nuru", with_class=True)
    mocks.get_user.return_value = fresh

    assert await OnboardingService().update_progress(_user()) is True

    assert fresh.state == UserState.active
    assert fresh.onboarding_state == OnboardingState.completed
    mocks.update_user.assert_awaited_once_with(fresh)


async def test_completion_happens_only_once(mocks: Mocks) -> None:
    fresh = _user(name="Luke Nuru", with_class=True)
    mocks.get_user.return_value = fresh
    service = OnboardingService()

    assert await service.update_progress(_user()) is True
    assert await service.update_progress(_user()) is False  # now active

    mocks.update_user.assert_awaited_once()


async def test_user_mid_onboarding_from_old_flow_is_left_waiting_for_classes(
    mocks: Mocks,
) -> None:
    fresh = _user(name="Ali", onboarding_state=OnboardingState.personal_info_submitted)
    mocks.get_user.return_value = fresh

    assert await OnboardingService().update_progress(fresh) is False

    mocks.update_user.assert_not_awaited()


@pytest.mark.parametrize("fresh", [None, _user(name="Ali", state=UserState.active)])
async def test_progress_ignores_missing_or_non_onboarding_users(
    mocks: Mocks, fresh: User | None
) -> None:
    mocks.get_user.return_value = fresh

    assert await OnboardingService().update_progress(_user()) is False

    mocks.update_user.assert_not_awaited()
