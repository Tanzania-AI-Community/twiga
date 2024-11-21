from typing import Dict, List
from pydantic import BaseModel, ConfigDict
from sqlmodel import Enum

from app.database.models import Subject


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


class SubjectNames(str, Enum):
    geography = "geography"
    mathematics = "mathematics"


class ChunkType(str, Enum):
    text = "text"
    exercise = "exercise"
    image = "image"
    table = "table"
    other = "other"
    # NOTE: add more types as needed, but keep clean structure with good segregation


# NOTE: not really an enum, but fits here for now
class ClassInfo(BaseModel):
    """Maps subjects to their grade levels for a teacher"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    subjects: Dict[str, List[str]]  # keys=Subject, values=List[GradeLevel]

    """ METHODS """

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        return {
            subject: [grade for grade in grades]
            for subject, grades in data["subjects"].items()
        }

    # TODO: Double check this validator
    @classmethod
    def model_validate(cls, data: Dict):
        if data is None:
            return None
        return cls(
            subjects={
                Subject(subject): [GradeLevel(grade) for grade in grades]
                for subject, grades in data.items()
            }
        )
