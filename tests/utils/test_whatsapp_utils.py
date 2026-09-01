"""Tests for splitting outbound text to fit WhatsApp's message length limit."""

from app.utils.whatsapp_utils import split_text_for_whatsapp

# Meta's documented limit for a text message body.
WHATSAPP_TEXT_LIMIT = 4096

# Small limit keeps the fixtures readable; the logic is independent of scale.
LIMIT = 100


def _visible(text: str) -> str:
    """Text with all whitespace removed, for comparing content across chunks."""
    return "".join(text.split())


def test_short_message_is_returned_unchanged() -> None:
    message = "Here is your lesson plan."

    assert split_text_for_whatsapp(message, LIMIT) == [message]


def test_message_exactly_at_limit_is_not_split() -> None:
    message = "a" * LIMIT

    assert split_text_for_whatsapp(message, LIMIT) == [message]


def test_message_one_char_over_limit_is_split() -> None:
    chunks = split_text_for_whatsapp("a" * (LIMIT + 1), LIMIT)

    assert len(chunks) == 2
    assert [len(chunk) for chunk in chunks] == [LIMIT, 1]


def test_empty_message_produces_no_chunks() -> None:
    assert split_text_for_whatsapp("", LIMIT) == []


def test_whitespace_only_message_produces_no_chunks() -> None:
    """Empty bodies are rejected by WhatsApp, so they must never be sent."""
    assert split_text_for_whatsapp("   \n\n  \t ", LIMIT) == []


def test_no_chunk_ever_exceeds_the_limit() -> None:
    """The invariant the whole function exists to guarantee."""
    messages = [
        "a" * 10_000,  # one long word, no separator anywhere
        ("word " * 2_000),
        ("Paragraph body here.\n\n" * 200),
        "\n".join("Line number %d" % i for i in range(500)),
        "Sentence one. Sentence two. " * 300,
    ]

    for message in messages:
        for chunk in split_text_for_whatsapp(message, LIMIT):
            assert len(chunk) <= LIMIT


def test_splitting_preserves_all_content() -> None:
    """Splitting may drop separator whitespace, but never visible characters."""
    message = (
        "Lesson Plan: Solving Linear Equations\n\n"
        + "Learning objectives. " * 50
        + "\n\n"
        + "Homework. " * 80
    )

    chunks = split_text_for_whatsapp(message, LIMIT)

    assert _visible("".join(chunks)) == _visible(message)


def test_prefers_paragraph_boundary() -> None:
    message = "A" * 70 + "\n\n" + "B" * 70

    assert split_text_for_whatsapp(message, LIMIT) == ["A" * 70, "B" * 70]


def test_falls_back_to_line_boundary_when_no_paragraph_break() -> None:
    message = "A" * 70 + "\n" + "B" * 70

    assert split_text_for_whatsapp(message, LIMIT) == ["A" * 70, "B" * 70]


def test_falls_back_to_sentence_boundary_and_keeps_the_period() -> None:
    message = "A" * 68 + ". " + "B" * 70

    assert split_text_for_whatsapp(message, LIMIT) == ["A" * 68 + ".", "B" * 70]


def test_hard_cuts_when_no_separator_exists() -> None:
    chunks = split_text_for_whatsapp("a" * 250, LIMIT)

    assert chunks == ["a" * 100, "a" * 100, "a" * 50]


def test_ignores_boundary_that_would_leave_a_tiny_chunk() -> None:
    """
    A paragraph break near the start is below the minimum-fill floor. Using it
    would emit a 5-character message and waste a chunk, so the split falls
    through to a fuller cut instead.
    """
    message = "A" * 5 + "\n\n" + "B" * 300

    chunks = split_text_for_whatsapp(message, LIMIT)

    assert len(chunks[0]) > LIMIT // 2


def test_leading_whitespace_does_not_produce_an_empty_first_chunk() -> None:
    chunks = split_text_for_whatsapp("   \n\n" + "B" * 300, LIMIT)

    assert all(chunk.strip() for chunk in chunks)


def test_trailing_newlines_do_not_produce_an_empty_last_chunk() -> None:
    chunks = split_text_for_whatsapp("a" * 150 + "\n\n\n\n", LIMIT)

    assert all(chunk.strip() for chunk in chunks)


def test_lesson_plan_sized_message_fits_whatsapp_limit() -> None:
    """
    Regression test for the production bug: an ~8000 character lesson plan was
    posted as a single body and rejected by Meta with
    "(#100) Param text['body'] must be at most 4096 characters long."
    """
    lesson_plan = (
        "Here is your lesson plan! \U0001f4d8\n\n"
        "*Lesson Plan: Solving Linear Equations*\n"
        "*Subject:* Mathematics\n\n"
        + "*Learning Objectives:*\n"
        + "".join(
            f"{i}. Solve linear equations by applying inverse operations "
            f"while maintaining balance on both sides.\n"
            for i in range(1, 40)
        )
        + "\n*Homework:*\n"
        + "".join(
            f"- Exercise {i}: solve and verify by substitution.\n" for i in range(1, 40)
        )
    )
    assert len(lesson_plan) > WHATSAPP_TEXT_LIMIT

    chunks = split_text_for_whatsapp(lesson_plan, WHATSAPP_TEXT_LIMIT)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= WHATSAPP_TEXT_LIMIT
    assert _visible("".join(chunks)) == _visible(lesson_plan)
