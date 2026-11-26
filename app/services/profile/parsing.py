"""Pure parsing of the model's class-update arguments into typed requests."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.profile.aliases import resolve_form, resolve_subject
from app.services.profile.models import SubjectForms

_MAX_LABEL_LENGTH = 40


@dataclass(frozen=True)
class ParsedClassRequest:
    requested: tuple[SubjectForms, ...]
    # Subjects or forms that could not be mapped, reported back to the teacher
    unrecognized: tuple[str, ...]


def _label(value: Any) -> str:
    return " ".join(str(value).split())[:_MAX_LABEL_LENGTH]


def parse_class_requests(
    classes: Iterable[Mapping[str, Any]] | None,
    unavailable_subjects: Iterable[Any] | None = None,
) -> ParsedClassRequest:
    """Map `[{"subject": ..., "forms": [...]}]` to `SubjectForms`.

    An item whose forms were all unrecognised is dropped rather than turned
    into "no forms", because for `remove` no forms means the whole subject.
    """
    requested: list[SubjectForms] = []
    unrecognized = [_label(subject) for subject in unavailable_subjects or []]

    for item in classes or []:
        raw_subject = item.get("subject", "")
        subject = resolve_subject(str(raw_subject))
        if subject is None:
            unrecognized.append(_label(raw_subject))
            continue

        raw_forms = [str(form) for form in item.get("forms") or []]
        grades = {grade for form in raw_forms if (grade := resolve_form(form))}
        if raw_forms and not grades:
            unrecognized.append(_label(f"{raw_subject} {', '.join(raw_forms)}"))
            continue

        requested.append(SubjectForms(subject=subject, grades=frozenset(grades)))

    return ParsedClassRequest(
        requested=tuple(requested),
        unrecognized=tuple(label for label in unrecognized if label),
    )
