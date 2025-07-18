from enum import Enum


class SubjectClassStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ResourceType(str, Enum):
    textbook = "textbook"
    curriculum = "curriculum"
    document = "document"


class Role(str, Enum):
    admin = "admin"
    teacher = "teacher"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class GradeLevel(str, Enum):
    p1 = "p1"
    p2 = "p2"
    p3 = "p3"
    p4 = "p4"
    p5 = "p5"
    p6 = "p6"
    os1 = "os1"
    os2 = "os2"
    os3 = "os3"
    os4 = "os4"
    as1 = "as1"
    as2 = "as2"

    @property
    def display_format(self) -> str:
        """Returns a nicely formatted string for display"""
        grade_display = {
            "p1": "Standard 1",
            "p2": "Standard 2",
            "p3": "Standard 3",
            "p4": "Standard 4",
            "p5": "Standard 5",
            "p6": "Standard 6",
            "os1": "Form 1",
            "os2": "Form 2",
            "os3": "Form 3",
            "os4": "Form 4",
            "as1": "Form 5",
            "as2": "Form 6",
        }
        return grade_display[self]


class OnboardingState(str, Enum):
    new = "new"
    personal_info_submitted = "personal_info_submitted"
    completed = "completed"


class UserState(str, Enum):
    blocked = "blocked"
    rate_limited = "rate_limited"
    new = "new"
    onboarding = "onboarding"
    active = "active"


class SubjectName(str, Enum):
    geography = "geography"
    history = "history"
    biology = "biology"
    english = "english"
    civics = "civics"
    mathematics = "mathematics"

    @property
    def display_format(self) -> str:
        emoji_map = {
            "geography": "🌎",
            "history": "📙",
            "biology": "🧬",
            "english": "📘",
            "civics": "🏛️",
            "mathematics": "➗",
        }
        emoji = emoji_map.get(self, "")
        return f"{self.capitalize()} {emoji}"


class ChunkType(str, Enum):
    text = "text"
    exercise = "exercise"
    image = "image"
    table = "table"
    other = "other"
