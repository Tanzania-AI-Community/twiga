from collections.abc import Callable

from app.database.enums import GradeLevel, SubjectName
from app.database.models import User
from app.services.profile.errors import ProfileErrorCode, ProfileUpdateError
from app.services.profile.models import ProfileSnapshot

UserFactory = Callable[..., User]


def test_snapshot_from_user_groups_classes_by_subject(make_user: UserFactory) -> None:
    snapshot = ProfileSnapshot.from_user(make_user(class_ids=[102, 101, 201]))

    assert snapshot.classes == {
        SubjectName.english: (GradeLevel.os1,),
        SubjectName.geography: (GradeLevel.os1, GradeLevel.os2),
    }
    assert snapshot.complete


def test_snapshot_reports_missing_fields(make_user: UserFactory) -> None:
    assert ProfileSnapshot.from_user(make_user(name=None)).missing == (
        "name",
        "classes",
    )
    assert ProfileSnapshot.from_user(make_user(class_ids=[101], name=None)).missing == (
        "name",
    )
    assert ProfileSnapshot.from_user(make_user()).missing == ("classes",)


def test_snapshot_tool_payload(make_user: UserFactory) -> None:
    snapshot = ProfileSnapshot.from_user(
        make_user(class_ids=[101]), rejected=("Kiswahili",)
    )

    assert snapshot.to_tool_payload() == {
        "ok": True,
        "profile": {"name": "Ali", "classes": "Geography 🌎 (Form 1)"},
        "missing": [],
        "rejected": ["Kiswahili"],
    }


def test_snapshot_without_classes_reads_naturally() -> None:
    assert ProfileSnapshot(name="Ali").readable_classes() == "No classes assigned"


def test_error_tool_payload() -> None:
    error = ProfileUpdateError(ProfileErrorCode.invalid_name, "Letters only.")

    assert error.to_tool_payload() == {
        "ok": False,
        "error": "invalid_name",
        "detail": "Letters only.",
    }
