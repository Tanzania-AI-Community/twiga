import pytest

from app.clients.agent_modes import (
    AgentMode,
    active_prompt_variables,
    get_mode_config,
    onboarding_prompt_variables,
    resolve_agent_mode,
)
from app.clients.client_base import ClientBase
from app.config import Prompt
from app.database.enums import UserState
from app.database.models import User
from app.tools.registry import CURRICULUM_TOOLS, PROFILE_TOOLS


@pytest.mark.parametrize(
    ("state", "mode"),
    [
        (UserState.onboarding, AgentMode.onboarding),
        (UserState.active, AgentMode.active),
        (UserState.inactive, AgentMode.active),
    ],
)
def test_resolve_agent_mode(state: UserState, mode: AgentMode) -> None:
    assert resolve_agent_mode(User(wa_id="1", name="Ali", state=state)) is mode


def test_onboarding_mode_only_allows_profile_tools() -> None:
    config = get_mode_config(AgentMode.onboarding)

    assert config.tools == PROFILE_TOOLS
    assert config.prompt is Prompt.TWIGA_ONBOARDING_SYSTEM


def test_active_mode_allows_curriculum_and_profile_tools() -> None:
    config = get_mode_config(AgentMode.active)

    assert config.tools == CURRICULUM_TOOLS | PROFILE_TOOLS
    assert config.prompt is Prompt.TWIGA_AGENT_SYSTEM


def test_active_prompt_variables() -> None:
    user = User(wa_id="1", name=None, class_info={"geography": ["os2"]})

    assert active_prompt_variables(user) == {
        "user_name": "not provided yet",
        "class_info": "Geography 🌎 (Form 2)",
    }


def test_onboarding_prompt_variables_list_what_is_missing() -> None:
    variables = onboarding_prompt_variables(User(wa_id="1", name="Ali"))

    assert variables["missing_fields"] == "classes"
    assert "Name: Ali" in variables["current_profile"]


@pytest.mark.parametrize("mode", list(AgentMode))
def test_every_mode_prompt_renders(mode: AgentMode) -> None:
    config = get_mode_config(mode)
    user = User(wa_id="1", name="Luke Nuru")

    rendered = ClientBase._render_system_prompt(
        user, config.prompt, config.prompt_variables(user)
    )

    assert "<teacher_name>Luke Nuru</teacher_name>" in rendered
    assert "Tell me what you would like to change in your profile" in rendered
