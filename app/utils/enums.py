from enum import Enum


class Prompt(str, Enum):
    """Enumeration for system prompt names."""

    TWIGA_SYSTEM = "twiga_system"
    TWIGA_AGENT_SYSTEM = "twiga_agent_system"
