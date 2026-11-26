"""Pure mapping of how teachers name subjects and forms to the canonical enums.

The tool schema already constrains the model to enum values; this is the
server-side backstop for synonyms, abbreviations and Swahili names.
"""

import re
import unicodedata

from app.database.enums import GradeLevel, SubjectName

_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z ]+")

_EXTRA_SUBJECT_ALIASES: dict[str, SubjectName] = {
    # English abbreviations and variants
    "math": SubjectName.mathematics,
    "maths": SubjectName.mathematics,
    "basic math": SubjectName.mathematics,
    "basic maths": SubjectName.mathematics,
    "basic mathematics": SubjectName.mathematics,
    "add math": SubjectName.additional_mathematics,
    "add maths": SubjectName.additional_mathematics,
    "additional maths": SubjectName.additional_mathematics,
    "geo": SubjectName.geography,
    "bio": SubjectName.biology,
    "chem": SubjectName.chemistry,
    "physic": SubjectName.physics,
    "civic": SubjectName.civics,
    "english language": SubjectName.english,
    "literature": SubjectName.literature_in_english,
    "ics": SubjectName.information_and_computer_studies,
    "bookkeeping": SubjectName.book_keeping,
    "bible": SubjectName.bible_knowledge,
    # Swahili subject names
    "jiografia": SubjectName.geography,
    "historia": SubjectName.history,
    "biolojia": SubjectName.biology,
    "kiingereza": SubjectName.english,
    "uraia": SubjectName.civics,
    "hisabati": SubjectName.mathematics,
    "kemia": SubjectName.chemistry,
    "fizikia": SubjectName.physics,
    "kilimo": SubjectName.agriculture,
    "biashara": SubjectName.commerce,
}

_SWAHILI_ORDINALS = {
    1: "kwanza",
    2: "pili",
    3: "tatu",
    4: "nne",
    5: "tano",
    6: "sita",
}
_FORM_GRADES = {
    1: GradeLevel.os1,
    2: GradeLevel.os2,
    3: GradeLevel.os3,
    4: GradeLevel.os4,
    5: GradeLevel.as1,
    6: GradeLevel.as2,
}
_STANDARD_GRADES = {
    1: GradeLevel.p1,
    2: GradeLevel.p2,
    3: GradeLevel.p3,
    4: GradeLevel.p4,
    5: GradeLevel.p5,
    6: GradeLevel.p6,
}
_FORM_PREFIXES = ("form", "f", "kidato", "kidato cha")
_STANDARD_PREFIXES = ("standard", "std", "darasa", "darasa la")


def normalize_key(text: str) -> str:
    """Casefold, strip accents, punctuation and emoji, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = _NON_ALPHANUMERIC.sub(" ", ascii_text.replace("_", " "))
    return " ".join(cleaned.split())


def _build_subject_aliases() -> dict[str, SubjectName]:
    aliases: dict[str, SubjectName] = {}
    for subject in SubjectName:
        aliases[normalize_key(subject.value)] = subject
        aliases[normalize_key(subject.display_format)] = subject
    aliases.update(
        {normalize_key(key): subject for key, subject in _EXTRA_SUBJECT_ALIASES.items()}
    )
    return aliases


def _build_grade_aliases() -> dict[str, GradeLevel]:
    aliases: dict[str, GradeLevel] = {}
    for grades, prefixes in (
        (_FORM_GRADES, _FORM_PREFIXES),
        (_STANDARD_GRADES, _STANDARD_PREFIXES),
    ):
        for number, grade in grades.items():
            for prefix in prefixes:
                for token in (str(number), _SWAHILI_ORDINALS[number]):
                    aliases[f"{prefix} {token}"] = grade
                aliases[f"{prefix}{number}"] = grade
    for grade in GradeLevel:
        aliases[normalize_key(grade.value)] = grade
        aliases[normalize_key(grade.display_format)] = grade
    return aliases


SUBJECT_ALIASES = _build_subject_aliases()
GRADE_ALIASES = _build_grade_aliases()


def resolve_subject(text: str) -> SubjectName | None:
    return SUBJECT_ALIASES.get(normalize_key(text))


def resolve_form(text: str) -> GradeLevel | None:
    return GRADE_ALIASES.get(normalize_key(text))
