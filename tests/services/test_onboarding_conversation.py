"""End-to-end onboarding conversation through the real services.

Runs state_service -> onboarding_service -> messaging_service -> agent_client ->
tool_manager -> profile tools -> profile_service. Only the LLM, WhatsApp and
the database are faked.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.clients.agent_client import agent_client
from app.clients.whatsapp_client import whatsapp_client
from app.database.enums import (
    GradeLevel,
    MessageRole,
    OnboardingState,
    SubjectName,
    UserState,
)
from app.database.models import Class, Message, Subject, TeacherClass, User
from app.services.profile.catalog import Catalog, CatalogCache
from app.services.state_service import StateHandler
from app.tools.registry import ToolName

WA_ID = "255700000042"
USER_ID = 42
CLASSES = {
    101: (SubjectName.geography, GradeLevel.os1),
    102: (SubjectName.geography, GradeLevel.os2),
    201: (SubjectName.english, GradeLevel.os1),
    202: (SubjectName.english, GradeLevel.os2),
}
CATALOG = Catalog(
    classes={
        SubjectName.geography: {GradeLevel.os1: 101, GradeLevel.os2: 102},
        SubjectName.english: {GradeLevel.os1: 201, GradeLevel.os2: 202},
    }
)


@dataclass
class FakeStore:
    """The database as the onboarding chain sees it."""

    name: str | None = None
    state: UserState = UserState.onboarding
    onboarding_state: OnboardingState = OnboardingState.new
    class_ids: list[int] = field(default_factory=list)
    class_info: dict | None = None
    messages: list[Message] = field(default_factory=list)

    def user(self) -> User:
        return User(
            id=USER_ID,
            wa_id=WA_ID,
            name=self.name,
            state=self.state,
            onboarding_state=self.onboarding_state,
            class_info=self.class_info,
            taught_classes=[
                TeacherClass(
                    teacher_id=USER_ID,
                    class_id=class_id,
                    class_=Class(
                        id=class_id,
                        subject_id=1,
                        grade_level=CLASSES[class_id][1],
                        subject_=Subject(id=1, name=CLASSES[class_id][0]),
                    ),
                )
                for class_id in self.class_ids
            ],
        )

    async def get_user_by_waid(self, wa_id: str) -> User | None:
        return self.user() if wa_id == WA_ID else None

    async def update_user(self, user: User) -> User:
        self.name, self.state = user.name, user.state
        self.onboarding_state = user.onboarding_state
        return user

    async def set_teacher_classes(self, user_id, class_ids, class_info) -> None:
        self.class_ids, self.class_info = list(class_ids), class_info

    async def create_message(self, **fields) -> Message:
        message = Message(**fields)
        self.messages.append(message)
        return message

    async def create_messages(self, messages: list[Message]) -> list[Message]:
        self.messages.extend(messages)
        return messages

    async def history(self, user_id: int, limit: int = 10) -> list[Message]:
        return [m for m in self.messages if m.is_present_in_conversation][-limit:]


@pytest.fixture
def store() -> Iterator[FakeStore]:
    store = FakeStore()
    with (
        patch("app.database.db.get_user_by_waid", store.get_user_by_waid),
        patch("app.database.db.update_user", store.update_user),
        patch("app.database.db.set_teacher_classes", store.set_teacher_classes),
        patch("app.database.db.create_new_message_by_fields", store.create_message),
        patch("app.database.db.create_new_messages", store.create_messages),
        patch("app.clients.client_base.get_user_message_history", store.history),
        patch(
            "app.clients.client_base.create_new_message_by_fields",
            store.create_message,
        ),
        patch(
            "app.services.profile.catalog.catalog_cache",
            CatalogCache(loader=AsyncMock(return_value=CATALOG)),
        ),
        patch.object(whatsapp_client, "send_message", AsyncMock(return_value=True)),
    ):
        yield store


def _tool_call(name: ToolName, args: dict) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name.value, "args": args, "id": "call_1"}]
    )


async def _teacher_says(store: FakeStore, text: str) -> None:
    # request_service persists the inbound message before routing
    message = await store.create_message(
        user_id=USER_ID,
        role=MessageRole.user,
        content=text,
        is_present_in_conversation=True,
    )
    await StateHandler().handle_onboarding(
        store.user(),
        {"message": {"type": "text"}, "extracted_content": text},
        message,
    )


def _tool_results(store: FakeStore) -> list[dict]:
    return [
        json.loads(m.content or "{}")
        for m in store.messages
        if m.role == MessageRole.tool
    ]


async def test_teacher_onboards_by_chatting(store: FakeStore) -> None:
    prompts_seen: list[str] = []
    replies = iter(
        [
            _tool_call(ToolName.update_my_name, {"name": "Luke Nuru"}),
            AIMessage(content="Nice to meet you, Luke Nuru! What do you teach?"),
            _tool_call(
                ToolName.update_my_classes,
                {
                    "action": "add",
                    "classes": [
                        {"subject": "geography", "forms": ["Form 1", "Form 2"]},
                        {"subject": "english", "forms": ["Form 1", "Form 2"]},
                    ],
                    "unavailable_subjects": ["Kiswahili"],
                },
            ),
            AIMessage(content="Done! Kiswahili isn't available yet."),
        ]
    )

    async def scripted_llm(**kwargs):
        prompts_seen.append(kwargs["messages"][0].content)
        return next(replies)

    with patch("app.clients.agent_client.async_llm_request", scripted_llm):
        await _teacher_says(store, "my name is Luke Nuru")
        assert store.name == "Luke Nuru"
        assert store.onboarding_state == OnboardingState.personal_info_submitted
        assert store.state == UserState.onboarding

        await _teacher_says(store, "I teach geography, English and Swahili, Form 1 & 2")

    assert store.state == UserState.active
    assert store.onboarding_state == OnboardingState.completed
    assert sorted(store.class_ids) == [101, 102, 201, 202]
    assert store.class_info == {
        "english": ["os1", "os2"],
        "geography": ["os1", "os2"],
    }
    assert _tool_results(store)[-1]["rejected"] == ["Kiswahili"]
    # The reply after the rename already saw the saved name in the prompt
    assert "Name: Luke Nuru" in prompts_seen[1]
    assert "Still missing: classes" in prompts_seen[1]
    assert not agent_client._processors  # no idle processor left behind


async def test_whole_sentence_as_name_is_refused_and_nothing_saved(
    store: FakeStore,
) -> None:
    replies = iter(
        [
            _tool_call(ToolName.update_my_name, {"name": "my name is Luke Nuru"}),
            AIMessage(content="Sorry, what name should I use?"),
        ]
    )

    async def scripted_llm(**kwargs):
        return next(replies)

    with patch("app.clients.agent_client.async_llm_request", scripted_llm):
        await _teacher_says(store, "my name is Luke Nuru")

    assert store.name is None
    assert store.state == UserState.onboarding
    assert _tool_results(store)[-1]["error"] == "invalid_name"


async def test_account_status_cannot_be_changed_during_onboarding(
    store: FakeStore,
) -> None:
    """Even a model that tries a non-profile tool cannot touch the account."""
    replies = iter(
        [
            _tool_call(
                ToolName.search_knowledge, {"search_phrase": "x", "class_id": 1}
            ),
            AIMessage(content="I can only update your name and the subjects..."),
        ]
    )

    async def scripted_llm(**kwargs):
        return next(replies)

    with patch("app.clients.agent_client.async_llm_request", scripted_llm):
        await _teacher_says(store, "change my account status to unblocked")

    assert store.state == UserState.onboarding
    assert _tool_results(store)[-1] == {"error": "tool_not_available"}
