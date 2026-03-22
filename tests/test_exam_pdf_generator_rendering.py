from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table

from app.services.exam_pdf_generation_service import (
    build_styles,
    normalize_option_text,
    question_heading_markup,
    render_multiple_choice_question,
    render_section_b,
    render_short_answer_question,
)


def test_question_heading_markup_bolds_number_and_marks() -> None:
    heading = question_heading_markup(2, 5, "Select the correct option.")
    assert heading == "<b>2.</b><b> (5 marks)</b> Select the correct option."


def test_render_short_answer_hides_part_marks_when_subquestions_exist() -> None:
    st = build_styles()
    story = []
    question = {
        "id": "B-Q3",
        "marks": 14,
        "parts": [
            {
                "label": "a",
                "marks": 6,
                "prompt": "Define the following terms.",
                "sub_questions": [
                    {"label": "i", "text": "Ionic bond", "marks": 2},
                    {"label": "ii", "text": "Covalent bond", "marks": 4},
                ],
            }
        ],
    }

    render_short_answer_question(
        story, question, st, is_solution=False, fallback_number=1
    )

    paragraphs = [
        flowable.getPlainText() for flowable in story if isinstance(flowable, Paragraph)
    ]
    assert "3. (14 marks)" in paragraphs
    assert "(a) Define the following terms." in paragraphs
    assert "(a) Define the following terms. (6 marks)" not in paragraphs
    assert "(i) Ionic bond (2 marks)" in paragraphs
    assert "(ii) Covalent bond (4 marks)" in paragraphs

    spacers = [flowable for flowable in story if isinstance(flowable, Spacer)]
    assert len(spacers) == 2


def test_render_short_answer_shows_part_marks_when_no_subquestions() -> None:
    st = build_styles()
    story = []
    question = {
        "id": "B-Q3",
        "marks": 14,
        "parts": [
            {
                "label": "a",
                "marks": 6,
                "prompt": "Describe atomic structure components and their arrangement.",
                "sub_questions": [],
            }
        ],
    }

    render_short_answer_question(
        story, question, st, is_solution=False, fallback_number=1
    )

    paragraphs = [
        flowable.getPlainText() for flowable in story if isinstance(flowable, Paragraph)
    ]
    assert (
        "(a) Describe atomic structure components and their arrangement. (6 marks)"
        in paragraphs
    )


def test_render_multiple_choice_heading_and_option_indent() -> None:
    st = build_styles()
    story = []
    question = {
        "id": "A-Q1",
        "marks": 10,
        "prompt": "Choose the correct answer.",
        "items": [
            {
                "label": "i",
                "question": "Which particle has a positive charge?",
                "options": [
                    {"label": "A", "text": "A. Electron"},
                    {"label": "B", "text": "B. Proton"},
                ],
                "answer": "B",
            }
        ],
    }

    render_multiple_choice_question(
        story, question, st, is_solution=False, fallback_number=1
    )

    first_paragraph = next(
        flowable for flowable in story if isinstance(flowable, Paragraph)
    )
    assert first_paragraph.getPlainText() == "1. Choose the correct answer. (10 marks)"

    keep_block = next(
        flowable for flowable in story if isinstance(flowable, KeepTogether)
    )
    option_table = next(item for item in keep_block._content if isinstance(item, Table))
    assert option_table._cellStyles[0][0].leftPadding == 8


def test_normalize_option_text_strips_colon_prefix() -> None:
    assert normalize_option_text("A", "A: Example option text") == "Example option text"
    assert normalize_option_text("B", "B. Example option text") == "Example option text"
    assert normalize_option_text("C", "C) Example option text") == "Example option text"


def test_render_section_b_wraps_each_question_in_keep_together() -> None:
    st = build_styles()
    story = []
    exam = {
        "section_B": {
            "section_instructions": "Answer all questions.",
            "marks": 70,
            "question_list": [
                {
                    "id": "B-Q3",
                    "marks": 14,
                    "parts": [
                        {
                            "label": "a",
                            "marks": 14,
                            "prompt": "Describe atomic structure.",
                            "sub_questions": [
                                {"label": "i", "text": "Name particles.", "marks": 14}
                            ],
                        }
                    ],
                },
                {
                    "id": "B-Q4",
                    "marks": 14,
                    "parts": [
                        {
                            "label": "a",
                            "marks": 14,
                            "prompt": "Describe periodic trends.",
                            "sub_questions": [
                                {"label": "i", "text": "State one trend.", "marks": 14}
                            ],
                        }
                    ],
                },
            ],
        }
    }

    render_section_b(story, exam, st, is_solution=False)

    keep_blocks = [flowable for flowable in story if isinstance(flowable, KeepTogether)]
    assert len(keep_blocks) == 2
