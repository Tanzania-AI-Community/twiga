import pytest

from app.database.enums import GradeLevel, SubjectName
from app.services.profile.aliases import resolve_form, resolve_subject


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("geography", SubjectName.geography),
        ("Geography 🌎", SubjectName.geography),
        ("GEOGRAPHY", SubjectName.geography),
        ("Jiografia", SubjectName.geography),
        ("maths", SubjectName.mathematics),
        ("Basic Mathematics", SubjectName.mathematics),
        ("ICS", SubjectName.information_and_computer_studies),
        (
            "information_and_computer_studies",
            SubjectName.information_and_computer_studies,
        ),
        ("Kiingereza", SubjectName.english),
        ("literature in english", SubjectName.literature_in_english),
        ("  physics. ", SubjectName.physics),
    ],
)
def test_resolve_subject_maps_synonyms(text: str, expected: SubjectName) -> None:
    assert resolve_subject(text) is expected


@pytest.mark.parametrize("text", ["Kiswahili", "Swahili", "French", "", "form 2"])
def test_resolve_subject_returns_none_for_unsupported(text: str) -> None:
    assert resolve_subject(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Form 1", GradeLevel.os1),
        ("form2", GradeLevel.os2),
        ("F3", GradeLevel.os3),
        ("kidato cha nne", GradeLevel.os4),
        ("Kidato cha Pili", GradeLevel.os2),
        ("kidato 5", GradeLevel.as1),
        ("Form 6", GradeLevel.as2),
        ("os1", GradeLevel.os1),
        ("Standard 3", GradeLevel.p3),
        ("darasa la tatu", GradeLevel.p3),
    ],
)
def test_resolve_form_maps_english_and_swahili(text: str, expected: GradeLevel) -> None:
    assert resolve_form(text) is expected


@pytest.mark.parametrize("text", ["Form 7", "form", "year 2", ""])
def test_resolve_form_returns_none_for_unknown(text: str) -> None:
    assert resolve_form(text) is None
