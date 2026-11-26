"""Pure set maths for a teacher's classes.

Every operation is idempotent: the agent may re-run a turn (and its tool
calls) when new messages arrive mid-turn, so applying the same update twice
must leave the same result.
"""

from collections.abc import Mapping

from app.database.enums import GradeLevel, SubjectName
from app.services.profile.errors import ProfileErrorCode, ProfileUpdateError
from app.services.profile.models import ClassUpdateAction

MAX_SUBJECTS = 3
MAX_CLASSES = 10

ClassKey = tuple[SubjectName, GradeLevel]


def compute_target_class_ids(
    current: frozenset[int],
    action: ClassUpdateAction,
    requested: frozenset[int],
) -> frozenset[int]:
    match action:
        case ClassUpdateAction.add:
            return current | requested
        case ClassUpdateAction.remove:
            return current - requested
        case ClassUpdateAction.replace:
            return requested
    raise ValueError(f"Unsupported class update action: {action}")


def check_limits(target: frozenset[int], class_keys: Mapping[int, ClassKey]) -> None:
    """Raise when the resulting classes are empty or over the limits."""
    if not target:
        raise ProfileUpdateError(
            ProfileErrorCode.would_remove_all,
            "You need at least one class. Tell me which subjects and forms you teach.",
        )

    subjects = {class_keys[class_id][0] for class_id in target}
    if len(subjects) > MAX_SUBJECTS or len(target) > MAX_CLASSES:
        raise ProfileUpdateError(
            ProfileErrorCode.limit_exceeded,
            f"You can have up to {MAX_SUBJECTS} subjects and {MAX_CLASSES} "
            "classes in total. Tell me which ones to keep.",
        )


def build_class_info(
    target: frozenset[int], class_keys: Mapping[int, ClassKey]
) -> dict[str, list[str]]:
    """Project class IDs into the `users.class_info` JSON shape."""
    grade_order = list(GradeLevel)
    grades_by_subject: dict[SubjectName, set[GradeLevel]] = {}
    for class_id in target:
        subject, grade = class_keys[class_id]
        grades_by_subject.setdefault(subject, set()).add(grade)

    return {
        subject.value: [grade.value for grade in sorted(grades, key=grade_order.index)]
        for subject, grades in sorted(
            grades_by_subject.items(), key=lambda item: item[0].value
        )
    }
