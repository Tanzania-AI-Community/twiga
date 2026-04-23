import re
from typing import Any, Iterable


def safe_text(value: Any) -> str:
    """Convert values to clean printable text."""
    if value is None:
        return ""

    text = str(value)
    replacements = {
        "\u2011": "-",
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€\u009d": '"',
        "â€“": "-",
        "â€”": "-",
    }
    for raw, fixed in replacements.items():
        text = text.replace(raw, fixed)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def marks_suffix(marks: Any) -> str:
    marks_text = safe_text(marks)
    return f" ({marks_text} marks)" if marks_text else ""


def extract_question_number(question: dict[str, Any], fallback: int) -> int:
    question_id = safe_text(question.get("id"))
    match = re.search(r"Q(\d+)", question_id)
    if match:
        return int(match.group(1))
    return fallback


def roman_like_label(index: int) -> str:
    labels = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    if 1 <= index <= len(labels):
        return labels[index - 1]
    return str(index)


def normalize_option_text(label: str, text: str) -> str:
    label_prefix = re.compile(
        rf"^{re.escape(label)}\s*[\.\):]\s*",
        flags=re.IGNORECASE,
    )
    return label_prefix.sub("", safe_text(text))


def _is_placeholder_option(label: str, text: str) -> bool:
    normalized = safe_text(text).strip().upper()
    return normalized == safe_text(label).strip().upper()


def normalize_mcq_options(
    raw_options: Any, raw_option_values: Any = None
) -> list[tuple[str, str]]:
    if isinstance(raw_options, dict):
        options: list[tuple[str, str]] = []
        for label in ["A", "B", "C", "D", "E"]:
            if label in raw_options:
                options.append(
                    (label, normalize_option_text(label, raw_options[label]))
                )
        option_values = (
            [safe_text(value) for value in raw_option_values]
            if isinstance(raw_option_values, list)
            else []
        )
        for idx, (label, text) in enumerate(options):
            if idx < len(option_values) and _is_placeholder_option(label, text):
                options[idx] = (label, option_values[idx])
        return options

    if not isinstance(raw_options, list):
        return []

    option_values = (
        [safe_text(value) for value in raw_option_values]
        if isinstance(raw_option_values, list)
        else []
    )
    options: list[tuple[str, str]] = []
    for idx, option in enumerate(raw_options):
        if isinstance(option, dict):
            label = safe_text(option.get("label")) or chr(ord("A") + idx)
            text = safe_text(option.get("text"))
        else:
            label = chr(ord("A") + idx)
            text = safe_text(option)
        normalized_label = label.upper()
        normalized_text = normalize_option_text(label, text)
        if idx < len(option_values) and _is_placeholder_option(
            normalized_label, normalized_text
        ):
            normalized_text = option_values[idx]
        options.append((normalized_label, normalized_text))
    return options


def sort_questions(questions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(list(questions)))
    indexed.sort(
        key=lambda pair: (extract_question_number(pair[1], pair[0] + 1), pair[0])
    )
    return [item for _, item in indexed]


def detect_section_a_question_type(question: dict[str, Any]) -> str:
    """Infer Section A question type when `type` is missing in JSON."""
    explicit_type = safe_text(question.get("type", "")).lower()
    if explicit_type:
        return explicit_type

    items = question.get("items")
    if isinstance(items, list) and items:
        return "multiple_choice"

    list_a = question.get("listA")
    list_b = question.get("listB")
    if isinstance(list_a, list) and isinstance(list_b, list):
        return "item_matching"

    return ""


def format_answer_lines(value: Any, prefix: str = "") -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        lines: list[str] = []
        for key, sub_value in value.items():
            key_text = safe_text(key)
            next_prefix = f"{prefix}{key_text}: " if prefix else f"{key_text}: "
            if isinstance(sub_value, (dict, list)):
                lines.append(next_prefix.rstrip())
                lines.extend(format_answer_lines(sub_value, prefix="  "))
            else:
                lines.append(f"{next_prefix}{safe_text(sub_value)}")
        return lines
    if isinstance(value, list):
        lines = []
        for idx, item in enumerate(value, start=1):
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{idx}.")
                lines.extend(format_answer_lines(item, prefix="  "))
            else:
                lines.append(f"{prefix}{idx}. {safe_text(item)}")
        return lines
    return [f"{prefix}{safe_text(value)}"]


def normalize_list_entries(raw_items: Any, label_style: str) -> list[tuple[str, str]]:
    if not isinstance(raw_items, list):
        return []

    normalized: list[tuple[str, str]] = []
    for idx, item in enumerate(raw_items, start=1):
        if isinstance(item, dict):
            label = safe_text(item.get("label"))
            text = safe_text(item.get("text"))
        else:
            label = ""
            text = safe_text(item)

        if not label:
            if label_style == "roman":
                label = roman_like_label(idx)
            else:
                label = chr(ord("A") + idx - 1)
        normalized.append((label, text))
    return normalized
