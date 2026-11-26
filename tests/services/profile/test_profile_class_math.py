import pytest

from app.database.enums import GradeLevel, SubjectName
from app.services.profile.class_math import (
    MAX_CLASSES,
    build_class_info,
    check_limits,
    compute_target_class_ids,
)
from app.services.profile.errors import ProfileErrorCode, ProfileUpdateError
from app.services.profile.models import ClassUpdateAction

CURRENT = frozenset({101, 102})


@pytest.mark.parametrize(
    ("action", "requested", "expected"),
    [
        (ClassUpdateAction.add, frozenset({102, 201}), {101, 102, 201}),
        (ClassUpdateAction.remove, frozenset({102, 999}), {101}),
        (ClassUpdateAction.replace, frozenset({301}), {301}),
    ],
)
def test_compute_target_class_ids(
    action: ClassUpdateAction, requested: frozenset[int], expected: set[int]
) -> None:
    assert compute_target_class_ids(CURRENT, action, requested) == expected


@pytest.mark.parametrize("action", list(ClassUpdateAction))
def test_compute_target_class_ids_is_idempotent(action: ClassUpdateAction) -> None:
    requested = frozenset({102, 201})
    once = compute_target_class_ids(CURRENT, action, requested)

    assert compute_target_class_ids(once, action, requested) == once


def _keys(*subjects: SubjectName, per_subject: int = 1) -> dict:
    grades = list(GradeLevel)
    return {
        index * 100 + offset: (subject, grades[offset])
        for index, subject in enumerate(subjects, start=1)
        for offset in range(per_subject)
    }


def test_check_limits_accepts_three_subjects() -> None:
    keys = _keys(SubjectName.geography, SubjectName.english, SubjectName.history)

    check_limits(frozenset(keys), keys)


def test_check_limits_rejects_a_fourth_subject() -> None:
    keys = _keys(
        SubjectName.geography,
        SubjectName.english,
        SubjectName.history,
        SubjectName.physics,
    )

    with pytest.raises(ProfileUpdateError) as error:
        check_limits(frozenset(keys), keys)

    assert error.value.code is ProfileErrorCode.limit_exceeded


def test_check_limits_rejects_too_many_classes() -> None:
    keys = _keys(SubjectName.geography, SubjectName.english, per_subject=6)
    assert len(keys) > MAX_CLASSES

    with pytest.raises(ProfileUpdateError) as error:
        check_limits(frozenset(keys), keys)

    assert error.value.code is ProfileErrorCode.limit_exceeded


def test_check_limits_rejects_no_classes() -> None:
    with pytest.raises(ProfileUpdateError) as error:
        check_limits(frozenset(), {})

    assert error.value.code is ProfileErrorCode.would_remove_all


def test_build_class_info_groups_and_orders_grades() -> None:
    keys = {
        1: (SubjectName.geography, GradeLevel.as1),
        2: (SubjectName.geography, GradeLevel.os2),
        3: (SubjectName.english, GradeLevel.os1),
    }

    assert build_class_info(frozenset(keys), keys) == {
        "english": ["os1"],
        "geography": ["os2", "as1"],
    }
