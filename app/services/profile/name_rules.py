"""Pure rules for the name a teacher wants to be called.

The name is rendered into the system prompt on every turn, so only plain
names are accepted: anything that could read as an instruction is refused.
"""

import unicodedata

from app.services.profile.errors import ProfileErrorCode, ProfileUpdateError

MAX_NAME_LENGTH = 50  # users.name is VARCHAR(50)
MAX_NAME_WORDS = 5
RESERVED_NAMES = frozenset(
    {"twiga", "admin", "administrator", "system", "assistant", "bot"}
)
# Letters-only text can still read as an instruction; no real name uses these
INSTRUCTION_WORDS = frozenset(
    {
        "ignore",
        "disregard",
        "forget",
        "override",
        "instruction",
        "instructions",
        "prompt",
        "previous",
        "reveal",
        "pretend",
        "delete",
        "unblock",
        "block",
    }
)
_BLOCKED_WORDS = RESERVED_NAMES | INSTRUCTION_WORDS
# The model should pass only the name; these mean it passed the whole sentence
_LEAD_IN_PHRASES = (
    "my name",
    "call me",
    "i am",
    "i'm",
    "im",
    "it's",
    "its",
    "this is",
    "jina langu",
    "naitwa",
    "mimi ni",
)
_ALLOWED_PUNCTUATION = frozenset(" '-.")
_APOSTROPHE_VARIANTS = {"’": "'", "‘": "'", "ʼ": "'"}

INVALID_NAME_DETAIL = (
    "Please send just the name you want to be called, using letters only "
    f"and up to {MAX_NAME_LENGTH} characters."
)


def normalize_name(raw: str) -> str:
    """NFC-normalise, unify apostrophes and collapse whitespace."""
    name = unicodedata.normalize("NFC", raw)
    for variant, apostrophe in _APOSTROPHE_VARIANTS.items():
        name = name.replace(variant, apostrophe)
    return " ".join(name.split())


def _is_allowed_character(character: str) -> bool:
    # Letters in any script, plus combining marks some scripts need
    category = unicodedata.category(character)
    return (
        category.startswith("L")
        or category.startswith("M")
        or character in _ALLOWED_PUNCTUATION
    )


def _has_blocked_word(name: str) -> bool:
    words = (word.strip("'-.").casefold() for word in name.split())
    return any(word in _BLOCKED_WORDS for word in words)


def _starts_with_lead_in(name: str) -> bool:
    lowered = name.casefold()
    return any(
        lowered == phrase or lowered.startswith(f"{phrase} ")
        for phrase in _LEAD_IN_PHRASES
    )


def validate_name(raw: str) -> str:
    """Return the normalised name, or raise `ProfileUpdateError(invalid_name)`."""
    name = normalize_name(raw)
    is_valid = (
        0 < len(name) <= MAX_NAME_LENGTH
        and len(name.split()) <= MAX_NAME_WORDS
        and any(unicodedata.category(c).startswith("L") for c in name)
        and all(_is_allowed_character(c) for c in name)
        and not _has_blocked_word(name)
        and not _starts_with_lead_in(name)
    )
    if not is_valid:
        raise ProfileUpdateError(ProfileErrorCode.invalid_name, INVALID_NAME_DETAIL)
    return name
