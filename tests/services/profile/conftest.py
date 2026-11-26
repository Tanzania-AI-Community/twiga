from collections.abc import Callable, Iterable

import pytest

from app.database.enums import GradeLevel, SubjectClassStatus, SubjectName
from app.database.models import Class, Subject, TeacherClass, User
from app.services.profile.catalog import Catalog, build_catalog

# (class_id, subject, grade, status); IDs encode the subject for readable asserts
CATALOG_ROWS = [
    (101, SubjectName.geography, GradeLevel.os1, SubjectClassStatus.active),
    (102, SubjectName.geography, GradeLevel.os2, SubjectClassStatus.active),
    (103, SubjectName.geography, GradeLevel.os3, SubjectClassStatus.active),
    (109, SubjectName.geography, GradeLevel.as1, SubjectClassStatus.inactive),
    (201, SubjectName.english, GradeLevel.os1, SubjectClassStatus.active),
    (202, SubjectName.english, GradeLevel.os2, SubjectClassStatus.active),
    (301, SubjectName.history, GradeLevel.os3, SubjectClassStatus.active),
    (401, SubjectName.physics, GradeLevel.os4, SubjectClassStatus.active),
    (501, SubjectName.chemistry, GradeLevel.os1, SubjectClassStatus.active),
]
SUBJECT_IDS = {
    subject: index + 1
    for index, subject in enumerate(dict.fromkeys(row[1] for row in CATALOG_ROWS))
}
CLASS_ROWS = {row[0]: row for row in CATALOG_ROWS}

UserFactory = Callable[..., User]


def _class(class_id: int) -> Class:
    _, subject, grade, status = CLASS_ROWS[class_id]
    return Class(
        id=class_id,
        subject_id=SUBJECT_IDS[subject],
        grade_level=grade,
        status=status,
        subject_=Subject(id=SUBJECT_IDS[subject], name=subject),
    )


@pytest.fixture
def catalog_subjects() -> list[Subject]:
    subjects = {
        subject: Subject(id=subject_id, name=subject, subject_classes=[])
        for subject, subject_id in SUBJECT_IDS.items()
    }
    for class_id, subject, grade, status in CATALOG_ROWS:
        subjects[subject].subject_classes.append(  # type: ignore[union-attr]
            Class(
                id=class_id,
                subject_id=SUBJECT_IDS[subject],
                grade_level=grade,
                status=status,
            )
        )
    return list(subjects.values())


@pytest.fixture
def catalog(catalog_subjects: list[Subject]) -> Catalog:
    return build_catalog(catalog_subjects)


@pytest.fixture
def make_user() -> UserFactory:
    def factory(class_ids: Iterable[int] = (), name: str | None = "Ali") -> User:
        user_id = 7
        return User(
            id=user_id,
            wa_id="255700000007",
            name=name,
            taught_classes=[
                TeacherClass(
                    teacher_id=user_id, class_id=class_id, class_=_class(class_id)
                )
                for class_id in class_ids
            ],
        )

    return factory
