from sqlmodel import Enum


class SubjectClassStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ResourceType(str, Enum):
    textbook = "textbook"
    curriculum = "curriculum"
    document = "document"
    # NOTE: add more types as needed, but keep clean structure with good segregation


class Role(str, Enum):
    admin = "admin"
    teacher = "teacher"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class GradeLevel(str, Enum):
    p1 = "p1"  # primary 1
    p2 = "p2"
    p3 = "p3"
    p4 = "p4"
    p5 = "p5"
    p6 = "p6"
    os1 = "os1"  # ordinary secondary 1 (form 1)
    os2 = "os2"
    os3 = "os3"
    os4 = "os4"
    as1 = "as1"  # advanced secondary 1 (form 5)
    as2 = "as2"


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
    mathematics = "mathematics"

    EMOJI_MAP = {"geography": "🌎", "mathematics": "🔢"}

    @property
    def title_format(self) -> str:
        emoji = self.EMOJI_MAP.get(self, "")
        return f"{self.capitalize()} {emoji}"


class ChunkType(str, Enum):
    text = "text"
    exercise = "exercise"
    image = "image"
    table = "table"
    other = "other"
    # NOTE: add more types as needed, but keep clean structure with good segregation
