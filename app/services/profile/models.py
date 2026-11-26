from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from app.database.enums import GradeLevel, SubjectName
from app.database.models import ClassInfo, User

MissingField = Literal["name", "classes"]


class ClassUpdateAction(str, Enum):
    """How requested classes combine with the teacher's current ones."""

    add = "add"
    remove = "remove"
    replace = "replace"


@dataclass(frozen=True)
class SubjectForms:
    """One subject and the forms it is taught in.

    Empty `grades` is only meaningful for `remove`, where it means the whole subject.
    """

    subject: SubjectName
    grades: frozenset[GradeLevel] = frozenset()


@dataclass(frozen=True)
class ProfileSnapshot:
    """The teacher's profile as the agent and onboarding see it."""

    name: str | None
    classes: Mapping[SubjectName, tuple[GradeLevel, ...]] = field(default_factory=dict)
    # Requested items that could not be saved (e.g. "Kiswahili"), for the reply
    rejected: tuple[str, ...] = ()

    @property
    def missing(self) -> tuple[MissingField, ...]:
        missing: list[MissingField] = []
        if not self.name:
            missing.append("name")
        if not self.classes:
            missing.append("classes")
        return tuple(missing)

    @property
    def complete(self) -> bool:
        return not self.missing

    def readable_classes(self) -> str:
        return ClassInfo(
            classes={
                subject.value: [grade.value for grade in grades]
                for subject, grades in self.classes.items()
            }
        ).format_readable()

    def to_tool_payload(self) -> dict:
        return {
            "ok": True,
            "profile": {"name": self.name, "classes": self.readable_classes()},
            "missing": list(self.missing),
            "rejected": list(self.rejected),
        }

    @classmethod
    def from_user(cls, user: User, rejected: tuple[str, ...] = ()) -> "ProfileSnapshot":
        """Build from a user whose `taught_classes -> class_ -> subject_` is loaded."""
        grades_by_subject: dict[SubjectName, set[GradeLevel]] = {}
        for taught_class in user.taught_classes or []:
            class_ = taught_class.class_
            if class_ is None:
                continue
            grades_by_subject.setdefault(class_.subject_.name, set()).add(
                class_.grade_level
            )

        grade_order = list(GradeLevel)
        classes = {
            subject: tuple(sorted(grades, key=grade_order.index))
            for subject, grades in sorted(
                grades_by_subject.items(), key=lambda item: item[0].value
            )
        }
        return cls(name=user.name, classes=classes, rejected=rejected)
