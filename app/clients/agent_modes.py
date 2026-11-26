"""Which prompt and tools the agent uses for a teacher.

A mode is a (system prompt, allowed tools, prompt variables) triple chosen
from the teacher's state. It is the single place that decides what the model
can do: onboarding teachers only get the profile tools.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.config import Prompt
from app.database.enums import UserState
from app.database.models import User
from app.services.profile import ProfileSnapshot
from app.tools.registry import CURRICULUM_TOOLS, PROFILE_TOOLS, ToolName

_NAME_NOT_PROVIDED = "not provided yet"

PromptVariables = Callable[[User], dict[str, str]]


class AgentMode(str, Enum):
    onboarding = "onboarding"
    active = "active"


@dataclass(frozen=True)
class AgentModeConfig:
    mode: AgentMode
    prompt: Prompt
    tools: frozenset[ToolName]
    prompt_variables: PromptVariables


def active_prompt_variables(user: User) -> dict[str, str]:
    return {
        "user_name": user.name or _NAME_NOT_PROVIDED,
        "class_info": user.formatted_class_info,
    }


def onboarding_prompt_variables(user: User) -> dict[str, str]:
    snapshot = ProfileSnapshot.from_user(user)
    return {
        "user_name": user.name or _NAME_NOT_PROVIDED,
        "current_profile": (
            f"Name: {snapshot.name or _NAME_NOT_PROVIDED}\n"
            f"Classes: {snapshot.readable_classes()}"
        ),
        "missing_fields": ", ".join(snapshot.missing) or "nothing",
    }


MODE_CONFIGS: dict[AgentMode, AgentModeConfig] = {
    AgentMode.onboarding: AgentModeConfig(
        mode=AgentMode.onboarding,
        prompt=Prompt.TWIGA_ONBOARDING_SYSTEM,
        tools=PROFILE_TOOLS,
        prompt_variables=onboarding_prompt_variables,
    ),
    AgentMode.active: AgentModeConfig(
        mode=AgentMode.active,
        prompt=Prompt.TWIGA_AGENT_SYSTEM,
        tools=CURRICULUM_TOOLS | PROFILE_TOOLS,
        prompt_variables=active_prompt_variables,
    ),
}


def resolve_agent_mode(user: User) -> AgentMode:
    if user.state == UserState.onboarding:
        return AgentMode.onboarding
    return AgentMode.active


def get_mode_config(mode: AgentMode) -> AgentModeConfig:
    return MODE_CONFIGS[mode]
