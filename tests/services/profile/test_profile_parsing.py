from app.database.enums import GradeLevel, SubjectName
from app.services.profile.models import SubjectForms
from app.services.profile.parsing import parse_class_requests


def test_parses_subjects_and_forms_with_aliases() -> None:
    parsed = parse_class_requests(
        [
            {"subject": "geography", "forms": ["Form 1", "kidato cha pili"]},
            {"subject": "Maths", "forms": ["F3"]},
        ]
    )

    assert parsed.requested == (
        SubjectForms(
            SubjectName.geography, frozenset({GradeLevel.os1, GradeLevel.os2})
        ),
        SubjectForms(SubjectName.mathematics, frozenset({GradeLevel.os3})),
    )
    assert parsed.unrecognized == ()


def test_unknown_subjects_are_reported() -> None:
    parsed = parse_class_requests(
        [{"subject": "Kiswahili", "forms": ["Form 1"]}],
        unavailable_subjects=["French"],
    )

    assert parsed.requested == ()
    assert parsed.unrecognized == ("French", "Kiswahili")


def test_subject_without_forms_keeps_empty_grades() -> None:
    parsed = parse_class_requests([{"subject": "history", "forms": []}])

    assert parsed.requested == (SubjectForms(SubjectName.history, frozenset()),)


def test_subject_with_only_unknown_forms_is_dropped_not_emptied() -> None:
    # An empty grade set would mean "the whole subject" for a remove
    parsed = parse_class_requests([{"subject": "history", "forms": ["Form 9"]}])

    assert parsed.requested == ()
    assert parsed.unrecognized == ("history Form 9",)


def test_unknown_forms_are_ignored_when_some_forms_are_valid() -> None:
    parsed = parse_class_requests(
        [{"subject": "history", "forms": ["Form 3", "Form 9"]}]
    )

    assert parsed.requested == (
        SubjectForms(SubjectName.history, frozenset({GradeLevel.os3})),
    )


def test_handles_missing_inputs() -> None:
    parsed = parse_class_requests(None, None)

    assert parsed.requested == ()
    assert parsed.unrecognized == ()


def test_long_labels_are_truncated() -> None:
    parsed = parse_class_requests([{"subject": "x" * 200, "forms": ["Form 1"]}])

    assert len(parsed.unrecognized[0]) == 40
