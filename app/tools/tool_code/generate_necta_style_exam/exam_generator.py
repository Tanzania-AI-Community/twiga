import copy
import json
import logging
import random
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from app.utils.llm_utils import async_llm_request
from app.utils.paths import paths
from app.utils.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


class ExamGenerationError(Exception):
    """Raised when exam JSON generation fails."""


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    ITEM_MATCHING = "item_matching"
    SHORT_ANSWER = "short_answer"
    LONG_ANSWER = "long_answer"


@dataclass
class ExamSpecification:
    exam_title: str = "GENERATED PRACTICE EXAM"
    duration: str = "3:00 Hrs"
    year: int = datetime.now(timezone.utc).year

    section_a_multiple_choice_marks: int = 10
    section_a_matching_marks: int = 5
    section_b_marks: int = 70
    section_c_marks: int = 15

    num_section_a_mcq_items: int = 10
    num_section_a_matching_questions: int = 1
    num_section_b_short_answer_questions: int = 5
    num_section_c_long_answer_questions: int = 2
    default_difficulty: str = "medium"

    @classmethod
    def from_dict(cls, payload: Optional[dict[str, Any]]) -> "ExamSpecification":
        if payload is None:
            return cls()

        meta = payload.get("meta", {})
        sections = payload.get("sections", {})
        section_a = sections.get("A", {})
        section_b = sections.get("B", {})
        section_c = sections.get("C", {})

        return cls(
            exam_title=str(meta.get("exam_title", cls.exam_title)),
            duration=str(meta.get("duration", cls.duration)),
            year=int(meta.get("year", cls.year)),
            section_a_multiple_choice_marks=int(
                section_a.get("mcq_marks", cls.section_a_multiple_choice_marks)
            ),
            section_a_matching_marks=int(
                section_a.get("matching_marks", cls.section_a_matching_marks)
            ),
            section_b_marks=int(section_b.get("marks", cls.section_b_marks)),
            section_c_marks=int(section_c.get("marks", cls.section_c_marks)),
            num_section_a_mcq_items=int(
                section_a.get("num_mcq_items", cls.num_section_a_mcq_items)
            ),
            num_section_a_matching_questions=int(
                section_a.get(
                    "num_matching_questions",
                    cls.num_section_a_matching_questions,
                )
            ),
            num_section_b_short_answer_questions=int(
                section_b.get(
                    "num_short_answer_questions",
                    cls.num_section_b_short_answer_questions,
                )
            ),
            num_section_c_long_answer_questions=int(
                section_c.get(
                    "num_long_answer_questions",
                    cls.num_section_c_long_answer_questions,
                )
            ),
            default_difficulty=str(
                payload.get("default_difficulty", cls.default_difficulty)
            ),
        )


class ExamGenerator:
    """
    Template-driven exam generator.

    Inputs:
    - `chunks_by_topic`: topic -> list of chunk-like objects (dict or ORM object with `id` and `content`).
    - `exam_spec`: question/section configuration.

    Output:
    - Exam JSON dictionary in `exam_template.json` format with generated questions populated.
    """

    ROMAN_LABELS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    MCQ_OPTION_LABELS = ["A", "B", "C", "D", "E"]

    def __init__(self) -> None:
        self.template_dir = paths.EXAM_GENERATOR_TEMPLATE_DIR
        self.exam_template = self._load_template_json("exam_template.json")
        self.mcq_template = self._load_template_json(
            "multiple_choice_question_template.json"
        )
        self.matching_template = self._load_template_json(
            "item_matching_question_template.json"
        )
        self.short_answer_template = self._load_template_json(
            "short_answer_question_template.json"
        )
        self.long_answer_template = self._load_template_json(
            "long_answer_question_template.json"
        )
        self.question_constraints = self._load_template_json(
            "question_constraints.json"
        )

    async def generate_exam(
        self,
        subject: str,
        chunks_by_topic: dict[str, list[Any]],
        exam_spec: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        subject = subject.strip()
        if not subject:
            raise ExamGenerationError("subject is required to generate the exam.")

        if not chunks_by_topic:
            raise ExamGenerationError(
                "chunks_by_topic is empty. Provide grounded chunks per topic."
            )

        topics = [
            topic.strip() for topic in chunks_by_topic.keys() if topic and topic.strip()
        ]
        if not topics:
            raise ExamGenerationError("No valid topic names found in chunks_by_topic.")

        if not exam_spec:
            raise ExamGenerationError(
                "exam_spec is required to generate the exam. Provide configuration for exam sections and question counts."
            )

        spec = ExamSpecification.from_dict(exam_spec)
        exam_json = copy.deepcopy(self.exam_template)
        self._fill_exam_metadata(exam_json=exam_json, spec=spec, subject=subject)

        section_a = exam_json.setdefault("section_A", {})
        section_b = exam_json.setdefault("section_B", {})
        section_c = exam_json.setdefault("section_C", {})
        section_a["multiple_choice_marks"] = spec.section_a_multiple_choice_marks
        section_a["matching_marks"] = spec.section_a_matching_marks
        section_b["marks"] = spec.section_b_marks
        section_c["marks"] = spec.section_c_marks

        section_a_questions: list[dict[str, Any]] = []
        section_b_questions: list[dict[str, Any]] = []
        section_c_questions: list[dict[str, Any]] = []

        # track already generated questions, modified in place during question generation
        previous_questions: list[str] = []

        if spec.num_section_a_mcq_items > 0:
            mcq_block = await self._build_mcq_block(
                subject=subject,
                topics=topics,
                chunks_by_topic=chunks_by_topic,
                num_items=spec.num_section_a_mcq_items,
                previous_questions=previous_questions,
                difficulty=spec.default_difficulty,
            )
            if mcq_block.get("items"):
                section_a_questions.append(mcq_block)
            else:
                logger.warning(
                    "Skipping Section A MCQ block: no valid items were generated."
                )

        for idx in range(max(0, spec.num_section_a_matching_questions)):
            topic = topics[
                idx % len(topics)
            ]  # maybe make this more randomized in the future
            success, matching_q = await self._generate_single_question(
                question_type=QuestionType.ITEM_MATCHING,
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.matching_template,
                question_id=f"A-Q{idx + 2}",
                num_marks=5,
                difficulty=spec.default_difficulty,
            )
            if success:
                section_a_questions.append(matching_q)
            else:
                logger.warning(
                    "Skipping invalid item_matching question at index %s.", idx
                )

        for idx in range(max(0, spec.num_section_b_short_answer_questions)):
            topic = topics[idx % len(topics)]
            success, short_q = await self._generate_single_question(
                question_type=QuestionType.SHORT_ANSWER,
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.short_answer_template,
                question_id=f"B-Q{idx + 3}",
                num_marks=14,
                difficulty=spec.default_difficulty,
            )
            if success:
                section_b_questions.append(short_q)
            else:
                logger.warning(
                    "Skipping invalid short_answer question at index %s.", idx
                )

        for idx in range(max(0, spec.num_section_c_long_answer_questions)):
            topic = topics[idx % len(topics)]
            success, long_q = await self._generate_single_question(
                question_type=QuestionType.LONG_ANSWER,
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.long_answer_template,
                question_id=f"C-Q{idx + 13}",
                num_marks=15,
                difficulty="hard",
            )
            if success:
                section_c_questions.append(long_q)
            else:
                logger.warning(
                    "Skipping invalid long_answer question at index %s.", idx
                )

        section_a["question_list"] = section_a_questions
        section_b["question_list"] = section_b_questions
        section_c["question_list"] = section_c_questions

        num_section_a_questions = len(section_a_questions)
        if num_section_a_questions > 0 and section_a_questions[0].get("id") == "A-Q1":
            num_section_a_questions += len(section_a_questions[0].get("items", [])) - 1

        section_a["total_num_questions"] = num_section_a_questions
        section_b["total_num_questions"] = len(section_b_questions)
        section_c["total_num_questions"] = len(section_c_questions)

        self._apply_total_question_instruction(exam_json)
        self._fill_required_fallbacks(exam_json, subject=subject)
        self._set_generation_trace(exam_json, chunks_by_topic)
        return exam_json

    def _load_template_json(self, filename: str) -> dict[str, Any]:
        path = self.template_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ExamGenerationError(f"Missing template file: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ExamGenerationError(f"Invalid JSON in template file: {path}") from exc

    def _fill_exam_metadata(
        self,
        exam_json: dict[str, Any],
        spec: ExamSpecification,
        subject: str,
    ) -> None:
        """
        Fill in the exam metadata based on the specification and subject, in place dict operation
        """
        meta = exam_json.setdefault("meta", {})
        meta["subject"] = subject.upper()
        meta["exam_title"] = spec.exam_title
        meta["duration"] = spec.duration
        meta["year"] = spec.year

    async def _build_mcq_block(
        self,
        subject: str,
        topics: Sequence[str],
        chunks_by_topic: dict[str, list[Any]],
        num_items: int,
        previous_questions: list[str],
        difficulty: str,
    ) -> dict[str, Any]:
        """
        Builds a block of multiple choice questions for Section A.
        """
        items: list[dict[str, Any]] = []

        for question_num in range(num_items):
            topic = topics[question_num % len(topics)]
            success, item = await self._generate_single_question(
                question_type=QuestionType.MULTIPLE_CHOICE,
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.mcq_template,
                question_id=f"A-Q1-{question_num + 1}",
                num_marks=1,
                difficulty=difficulty,
            )
            if not success:
                logger.warning(
                    "Skipping invalid multiple_choice item at index %s.", question_num
                )
                continue

            item["label"] = (
                self.ROMAN_LABELS[question_num]
                if question_num < len(self.ROMAN_LABELS)
                else str(question_num + 1)
            )
            item["options"] = self._normalize_mcq_options(item.get("options", []))
            item["answer"] = self._normalize_mcq_answer(item)
            items.append(item)

        return {
            "id": "A-Q1",
            "type": QuestionType.MULTIPLE_CHOICE.value,
            "marks": len(items),
            "prompt": "For each of the following items, choose the correct answer among the given alternatives and write its letter beside the item number provided.",
            "items": items,
            "metadata": {
                "topic": ", ".join(topics),
                "difficulty": difficulty,
            },
        }

    async def _generate_single_question(
        self,
        question_type: QuestionType,
        subject: str,
        topic: str,
        chunk_list: Sequence[Any],
        previous_questions: list[str],
        template: dict[str, Any],
        question_id: str,
        num_marks: int,
        difficulty: str,
    ) -> tuple[bool, dict[str, Any]]:
        try:
            context_str = self._format_context(chunk_list)
            previous_questions_str = (
                "\n".join(previous_questions) if previous_questions else "None"
            )

            system_prompt = prompt_manager.format_prompt("exam_generator_system")
            user_prompt = prompt_manager.format_prompt(
                "exam_generator_user",
                question_type=question_type.value,
                topic=topic,
                previous_questions=previous_questions_str,
                context_str=context_str,
            )

            constraints = self._constraints_for(question_type, num_marks)
            prompt_template = self._template_without_system_fields(template)
            template_json = json.dumps(prompt_template, indent=2, ensure_ascii=False)
            user_prompt_with_template = (
                f"{user_prompt}\n\n"
                f"Additional constraints:\n{constraints}\n\n"
                "- CRITICAL: Ensure this question tests a DIFFERENT concept from the previous questions. Do not repeat topics.\n"
                "- CRITICAL: Ensure the answer to this question cannot be directly inferred from any of the previous questions.\n\n"
                "Output requirements (strict):\n"
                "- Return ONLY one valid JSON object.\n"
                "- Do NOT include explanations, reasoning, notes, or analysis.\n"
                "- Do NOT include markdown code fences.\n"
                "- Do NOT include any text before or after the JSON object.\n"
                "Use this template shape exactly:\n"
                f"{template_json}"
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt_with_template),
            ]

            response = await async_llm_request(
                messages=messages,
                tools=None,
                tool_choice=None,
                run_name="twiga_necta_exam_generator",
                metadata={
                    "tool": "generate_necta_style_exam",
                    "subject": subject,
                    "topic": topic,
                    "question_type": question_type.value,
                },
            )

            logger.debug(
                f"Raw LLM response content for question generation (question_type={question_type}, topic={topic}): {response.content if response else 'No response'}"
            )

            parsed = self._parse_json_response(response.content if response else "")

            if (
                question_type == QuestionType.SHORT_ANSWER
                or question_type == QuestionType.LONG_ANSWER
            ):
                # apply additional validation to ensure no solution leakage in question description or sub-questions
                logger.debug("Running additional QA check for text question type.")
                parsed = await self._apply_llm_validation_for_answer_leakage_and_format(
                    question_payload=parsed,
                    question_type=question_type,
                    topic=topic,
                    template=template,
                    expected_total_marks=num_marks,
                )

            logger.debug(
                f"Parsed LLM response for question generation (question_type={question_type}, topic={topic}): {json.dumps(parsed, indent=2, ensure_ascii=False)}"
            )

            parsed = self._normalize_question_payload(question_type, parsed)
            merged = self._merge_with_template(template=template, payload=parsed)

            # the llm generated matching question places the answer options in the listB in the same order as listA, so we shuffle
            # the answers are stored in a dict mapping, so the order of the lists does not matter
            if question_type == QuestionType.ITEM_MATCHING:
                random.shuffle(merged["listB"])

            # set and order system fields for readability in persisted JSON
            rest_fields = {
                key: value
                for key, value in merged.items()
                if key not in {"id", "type", "marks"}
            }
            merged = {
                "id": question_id,
                "type": question_type.value,
                "marks": num_marks,
                **rest_fields,
            }
            metadata = merged.setdefault("metadata", {})
            metadata["topic"] = metadata.get("topic") or topic
            metadata["difficulty"] = metadata.get("difficulty") or difficulty
            merged["source_chunk_ids"] = self._extract_chunk_ids(chunk_list)

            is_valid = self._validate_question_format(
                question_type=question_type,
                payload=merged,
            )
            if not is_valid:
                return False, {}

            # track previous questions by their signature to help the LLM avoid repetition and encourage diversity in question phrasing and focus
            signature = self._question_signature(
                question_type=question_type, payload=merged
            )
            if signature:
                previous_questions.append(signature)
            return True, merged
        except Exception as exc:
            logger.warning(
                "Failed generating question (question_type=%s, topic=%s): %s",
                question_type,
                topic,
                exc,
            )
            return False, {}

    async def _apply_llm_validation_for_answer_leakage_and_format(
        self,
        question_payload: dict[str, Any],
        question_type: QuestionType,
        topic: str,
        template: dict[str, Any],
        expected_total_marks: int,
    ) -> dict[str, Any]:
        system_prompt = prompt_manager.format_prompt("exam_generator_validator_system")
        constraints = self._constraints_for(question_type, expected_total_marks)
        prompt_template = self._template_without_system_fields(template)
        template_json = json.dumps(prompt_template, indent=2, ensure_ascii=False)
        candidate_json = json.dumps(question_payload, indent=2, ensure_ascii=False)

        user_prompt = prompt_manager.format_prompt(
            "exam_generator_validator_user",
            question_type=question_type.value,
            topic=topic,
            constraints=constraints,
            template_json=template_json,
            candidate_json=candidate_json,
        )

        response = await async_llm_request(
            messages=[
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ],
            tools=None,
            tool_choice=None,
            run_name="twiga_necta_exam_validator",
            metadata={
                "tool": "generate_necta_style_exam",
                "stage": "question_validator",
                "topic": topic,
                "question_type": question_type.value,
            },
        )

        logger.debug(
            "Raw LLM response content for question validator (question_type=%s, topic=%s): %s",
            question_type,
            topic,
            response.content if response else "No response",
        )

        return self._parse_json_response(response.content if response else "")

    def _constraints_for(
        self,
        question_type: QuestionType,
        expected_total_marks: Optional[int] = None,
    ) -> str:
        constraints_list = self.question_constraints.get(question_type.value, [])
        dynamic_constraints: list[str] = []

        if expected_total_marks is not None:
            if question_type == QuestionType.SHORT_ANSWER:
                dynamic_constraints.extend(
                    [
                        f"Total marks for this question should be {expected_total_marks}.",
                        "Set marks for part a and part b as positive integers.",
                        f"Ensure part a marks + part b marks = {expected_total_marks}.",
                        "For each part, ensure sub-question marks are positive integers and sum to the part marks.",
                    ]
                )
            elif question_type == QuestionType.LONG_ANSWER:
                dynamic_constraints.extend(
                    [
                        f"Total marks for this question should be {expected_total_marks}.",
                        f"If task.sub_questions are present, ensure their marks sum to {expected_total_marks}.",
                    ]
                )
        all_constraints = (
            constraints_list + dynamic_constraints + ["Keep output valid and concise."]
        )
        return "\n".join(f"- {constraint}" for constraint in all_constraints)

    def _normalize_question_payload(
        self, question_type: QuestionType, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Flatten occasional LLM wrappers such as {"short_answer": {...}, ...}
        into the expected top-level question shape.
        """
        if not isinstance(payload, dict):
            return payload

        wrapper = payload.get(question_type.value)
        if not isinstance(wrapper, dict):
            return payload

        normalized = dict(payload)
        normalized.pop(question_type.value, None)
        for key, value in wrapper.items():
            if key not in normalized or normalized.get(key) in (None, [], {}):
                normalized[key] = value
        return normalized

    def _parse_json_response(self, raw_content: Any) -> dict[str, Any]:
        if isinstance(raw_content, dict):
            return raw_content

        if isinstance(raw_content, list):
            content = "".join(
                part if isinstance(part, str) else str(part.get("text", ""))
                for part in raw_content
            )
        else:
            content = str(raw_content or "")

        content = content.strip()

        # 1) Fast path: whole response is JSON
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        # 2) Try fenced JSON blocks anywhere in the response
        fenced_matches = re.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL
        )
        for candidate in fenced_matches:
            try:
                payload = json.loads(candidate.strip())
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                continue

        # 3) Fallback: extract first balanced {...} JSON object from free text
        candidate = self._extract_first_json_object(content)
        if candidate:
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass

        raise ExamGenerationError(
            f"Failed to parse LLM JSON. Response starts with: {content[:200]}"
        )

    def _merge_with_template(self, template: Any, payload: Any) -> Any:
        if isinstance(template, dict):
            payload_dict = payload if isinstance(payload, dict) else {}
            merged: dict[str, Any] = {}
            for key, template_val in template.items():
                merged[key] = self._merge_with_template(
                    template_val,
                    payload_dict.get(key),
                )

            for key, value in payload_dict.items():
                if key not in merged:
                    merged[key] = value
            return merged

        if isinstance(template, list):
            if not isinstance(payload, list):
                return copy.deepcopy(template)
            if not template:
                return payload
            return [self._merge_with_template(template[0], item) for item in payload]

        return copy.deepcopy(template) if payload is None else payload

    def _template_without_system_fields(
        self, template: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Remove system-owned fields from the template shown to the LLM.
        We set these fields in code after parsing.
        """
        prompt_template = copy.deepcopy(template)
        prompt_template.pop("id", None)
        prompt_template.pop("marks", None)
        return prompt_template

    def _extract_first_json_object(self, text: str) -> Optional[str]:
        """
        Extract the first balanced JSON object from arbitrary text.
        Handles leading reasoning and trailing commentary.
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]

        return None

    def _normalize_mcq_options(self, options: Any) -> list[dict[str, str]]:
        if isinstance(options, dict):
            return [
                {"label": label, "text": str(options.get(label, ""))}
                for label in self.MCQ_OPTION_LABELS
                if label in options
            ]

        if not isinstance(options, list):
            return []

        normalized: list[dict[str, str]] = []
        for idx, option in enumerate(options):
            if isinstance(option, dict):
                label = str(
                    option.get("label")
                    or self.MCQ_OPTION_LABELS[idx % len(self.MCQ_OPTION_LABELS)]
                )
                text = str(option.get("text", "")).strip()
            else:
                label = self.MCQ_OPTION_LABELS[idx % len(self.MCQ_OPTION_LABELS)]
                text = str(option).strip()
            normalized.append({"label": label, "text": text})
        return normalized

    def _normalize_mcq_answer(self, payload: dict[str, Any]) -> Optional[str]:
        answer = payload.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip().upper()

        options = payload.get("options", [])
        for option in options:
            if isinstance(option, dict) and option.get("is_correct"):
                label = option.get("label")
                if label:
                    return str(label).upper()
        return None

    def _validate_question_format(
        self,
        question_type: QuestionType,
        payload: dict[str, Any],
    ) -> bool:
        try:
            if question_type == QuestionType.MULTIPLE_CHOICE:
                self._validate_multiple_choice(payload)
            elif question_type == QuestionType.ITEM_MATCHING:
                self._validate_item_matching(payload)
            elif question_type == QuestionType.SHORT_ANSWER:
                self._validate_short_answer(payload)
            elif question_type == QuestionType.LONG_ANSWER:
                self._validate_long_answer(payload)
            else:
                logger.warning(
                    "Unsupported question_type for validation: %s", question_type
                )
                return False
            return True
        except ExamGenerationError as exc:
            logger.warning(
                "Question format validation failed (question_type=%s): %s",
                question_type,
                exc,
            )
            return False

    def _validate_multiple_choice(self, payload: dict[str, Any]) -> None:
        question = str(payload.get("question", "")).strip()
        if not question:
            raise ExamGenerationError("multiple_choice.question is required.")

        options = payload.get("options")
        if not isinstance(options, (list, dict)):
            raise ExamGenerationError(
                "multiple_choice.options must be a list or object."
            )

        if isinstance(options, list) and len(options) != 5:
            raise ExamGenerationError(
                "multiple_choice.options must contain exactly 5 options."
            )

        if isinstance(options, dict):
            option_count = sum(
                1 for label in self.MCQ_OPTION_LABELS if label in options
            )
            if option_count != 5:
                raise ExamGenerationError(
                    "multiple_choice.options object must contain labels A-E."
                )

        answer = payload.get("answer")
        has_answer = isinstance(answer, str) and bool(answer.strip())
        if not has_answer and self._normalize_mcq_answer(payload) is None:
            raise ExamGenerationError("multiple_choice.answer is required.")

    def _validate_item_matching(self, payload: dict[str, Any]) -> None:
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            raise ExamGenerationError("item_matching.prompt is required.")

        list_a = payload.get("listA", [])
        list_b = payload.get("listB", [])
        if not isinstance(list_a, list) or not list_a:
            raise ExamGenerationError("item_matching.listA must be a non-empty list.")
        if not isinstance(list_b, list) or not list_b:
            raise ExamGenerationError("item_matching.listB must be a non-empty list.")

        answers_pairs = payload.get("answers_pairs", {})
        if not isinstance(answers_pairs, dict) or not answers_pairs:
            raise ExamGenerationError(
                "item_matching.answers_pairs must be a non-empty object."
            )

    def _validate_short_answer(self, payload: dict[str, Any]) -> None:
        try:
            total_marks = int(payload.get("marks", 0))
        except (TypeError, ValueError) as exc:
            raise ExamGenerationError(
                "short_answer.marks must be a valid integer."
            ) from exc

        if total_marks <= 0:
            raise ExamGenerationError("short_answer.marks must be > 0.")

        parts = payload.get("parts", [])
        if not isinstance(parts, list) or len(parts) != 2:
            raise ExamGenerationError(
                "short_answer.parts must be a list with exactly two items (a and b)."
            )

        expected_part_labels = ["a", "b"]
        part_marks_sum = 0

        for part_idx, expected_label in enumerate(expected_part_labels):
            part = parts[part_idx]
            if not isinstance(part, dict):
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}] must be an object."
                )

            part_label = str(part.get("label", "")).strip().lower()
            if part_label != expected_label:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].label must be '{expected_label}'."
                )

            part_prompt = str(part.get("prompt", "")).strip()
            if not part_prompt:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].prompt is required."
                )

            if "marks" not in part:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].marks is required."
                )

            part_marks_raw = part.get("marks")
            try:
                part_marks = int(part_marks_raw)
            except (TypeError, ValueError) as exc:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].marks must be an integer."
                ) from exc

            if part_marks <= 0:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].marks must be > 0."
                )

            part["marks"] = part_marks
            part_marks_sum += part_marks

            sub_questions = part.get("sub_questions", [])
            if not isinstance(sub_questions, list):
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].sub_questions must be a list."
                )

            if not sub_questions:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].sub_questions must be a non-empty list."
                )

            part_sub_marks_sum = 0

            for sub_idx, sub_question in enumerate(sub_questions):
                if not isinstance(sub_question, dict):
                    raise ExamGenerationError(
                        f"short_answer.parts[{part_idx}].sub_questions[{sub_idx}] must be an object."
                    )

                sub_label = str(sub_question.get("label", "")).strip().lower()
                expected_roman = (
                    self.ROMAN_LABELS[sub_idx]
                    if sub_idx < len(self.ROMAN_LABELS)
                    else None
                )
                if expected_roman is None or sub_label != expected_roman:
                    raise ExamGenerationError(
                        f"short_answer.parts[{part_idx}].sub_questions[{sub_idx}].label must be sequential roman numerals starting at i."
                    )

                sub_text = str(sub_question.get("text", "")).strip()
                if not sub_text:
                    raise ExamGenerationError(
                        f"short_answer.parts[{part_idx}].sub_questions[{sub_idx}].text is required."
                    )

                if "marks" not in sub_question:
                    raise ExamGenerationError(
                        f"short_answer.parts[{part_idx}].sub_questions[{sub_idx}].marks is required."
                    )

                marks_raw = sub_question.get("marks")
                try:
                    marks = int(marks_raw)
                except (TypeError, ValueError) as exc:
                    raise ExamGenerationError(
                        f"short_answer.parts[{part_idx}].sub_questions[{sub_idx}].marks must be an integer."
                    ) from exc
                if marks <= 0:
                    raise ExamGenerationError(
                        f"short_answer.parts[{part_idx}].sub_questions[{sub_idx}].marks must be > 0."
                    )
                sub_question["marks"] = marks
                part_sub_marks_sum += marks

            if part_sub_marks_sum != part_marks:
                raise ExamGenerationError(
                    f"short_answer.parts[{part_idx}].sub_questions marks ({part_sub_marks_sum}) must equal short_answer.parts[{part_idx}].marks ({part_marks})."
                )

        if part_marks_sum != total_marks:
            raise ExamGenerationError(
                f"short_answer.parts marks ({part_marks_sum}) must equal short_answer.marks ({total_marks})."
            )

        answer = payload.get("answer", {})
        if not isinstance(answer, dict):
            raise ExamGenerationError("short_answer.answer must be an object.")

        example_answer = str(answer.get("example_answer", "")).strip()
        marking_points = answer.get("marking_points", [])
        if not example_answer and not marking_points:
            raise ExamGenerationError(
                "short_answer.answer must include example_answer or marking_points."
            )

    def _validate_long_answer(self, payload: dict[str, Any]) -> None:
        description = str(payload.get("description", "")).strip()
        if not description:
            raise ExamGenerationError(
                "long_answer.description is required and must be non-empty."
            )

        task = payload.get("task")
        if not isinstance(task, dict):
            raise ExamGenerationError("long_answer.task must be an object.")

        task_prompt = str(task.get("prompt", "")).strip()
        if not task_prompt:
            raise ExamGenerationError(
                "long_answer.task.prompt is required and must be non-empty."
            )

        sub_questions = task.get("sub_questions", [])
        if not isinstance(sub_questions, list):
            raise ExamGenerationError("long_answer.task.sub_questions must be a list.")

        if not sub_questions:
            return

        try:
            total_marks = int(payload.get("marks", 0))
        except (TypeError, ValueError) as exc:
            raise ExamGenerationError(
                "long_answer.marks must be a valid integer."
            ) from exc

        if total_marks <= 0:
            raise ExamGenerationError(
                "long_answer.marks must be > 0 when sub_questions are used."
            )

        marks_sum = 0
        for idx, sub_question in enumerate(sub_questions):
            if not isinstance(sub_question, dict):
                raise ExamGenerationError(
                    f"long_answer.task.sub_questions[{idx}] must be an object."
                )

            sub_prompt = str(sub_question.get("prompt", "")).strip()
            if not sub_prompt:
                raise ExamGenerationError(
                    f"long_answer.task.sub_questions[{idx}].prompt must be non-empty."
                )

            if "marks" not in sub_question:
                raise ExamGenerationError(
                    f"long_answer.task.sub_questions[{idx}].marks is required."
                )

            marks_raw = sub_question.get("marks")
            try:
                marks = int(marks_raw)
            except (TypeError, ValueError) as exc:
                raise ExamGenerationError(
                    f"long_answer.task.sub_questions[{idx}].marks must be an integer."
                ) from exc

            if marks <= 0:
                raise ExamGenerationError(
                    f"long_answer.task.sub_questions[{idx}].marks must be > 0."
                )

            sub_question["marks"] = marks
            marks_sum += marks

        if marks_sum != total_marks:
            raise ExamGenerationError(
                f"long_answer.task.sub_questions marks ({marks_sum}) must equal long_answer.marks ({total_marks})."
            )

    def _question_signature(
        self, question_type: QuestionType, payload: dict[str, Any]
    ) -> str:
        if question_type == QuestionType.MULTIPLE_CHOICE:
            question = str(payload.get("question", "")).strip()
            answer = payload.get("answer")
            answer_text = ""
            options = payload.get("options", [])
            if isinstance(options, list):
                for opt in options:
                    if isinstance(opt, dict) and opt.get("label") == answer:
                        answer_text = str(opt.get("text", ""))
                        break
            return f"Question: {question} | Answer: {answer_text}"
        if question_type == QuestionType.ITEM_MATCHING:
            prompt = str(payload.get("prompt", "")).strip()
            answers_pairs = payload.get("answers_pairs", {})
            pairs_str = (
                ", ".join(f"{k}: {v}" for k, v in answers_pairs.items())
                if isinstance(answers_pairs, dict)
                else ""
            )
            return f"Prompt: {prompt} | Matches: {pairs_str}"
        if question_type == QuestionType.SHORT_ANSWER:
            parts = payload.get("parts", [])
            signature_parts: list[str] = []
            if isinstance(parts, list):
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    label = str(part.get("label", "")).strip().lower()
                    prompt = str(part.get("prompt", "")).strip()
                    sub_texts: list[str] = []
                    sub_questions = part.get("sub_questions", [])
                    if isinstance(sub_questions, list):
                        for sub_question in sub_questions:
                            if isinstance(sub_question, dict):
                                sub_text = str(sub_question.get("text", "")).strip()
                                if sub_text:
                                    sub_texts.append(sub_text)
                    part_signature = " ".join(
                        token
                        for token in [f"{label})" if label else "", prompt]
                        if token
                    )
                    if sub_texts:
                        part_signature = (
                            f"{part_signature} {' | '.join(sub_texts)}"
                            if part_signature
                            else " | ".join(sub_texts)
                        )
                    if part_signature:
                        signature_parts.append(part_signature)

            answer_data = payload.get("answer", {})
            if isinstance(answer_data, dict):
                example_answer = str(answer_data.get("example_answer", "")).strip()
                if example_answer:
                    signature_parts.append(f"Answer: {example_answer}")
                else:
                    marking_points = answer_data.get("marking_points", [])
                    if isinstance(marking_points, list):
                        signature_parts.append(
                            "Answer Points: "
                            + " | ".join(str(p) for p in marking_points)
                        )

            return " | ".join(signature_parts)
        if question_type == QuestionType.LONG_ANSWER:
            description = str(payload.get("description", "")).strip()
            task = payload.get("task", {})
            prompt = (
                str(task.get("prompt", "")).strip() if isinstance(task, dict) else ""
            )
            sub_prompts: list[str] = []
            if isinstance(task, dict):
                for sub_question in task.get("sub_questions", []):
                    if isinstance(sub_question, dict):
                        sub_prompt = str(sub_question.get("prompt", "")).strip()
                        if sub_prompt:
                            sub_prompts.append(sub_prompt)
            parts = [description, prompt] + sub_prompts

            answer_data = payload.get("answer", {})
            if isinstance(answer_data, dict):
                marking_points = answer_data.get("marking_points", [])
                if isinstance(marking_points, list):
                    parts.append(
                        "Expected Answer Points: "
                        + " | ".join(str(p) for p in marking_points)
                    )

            return " | ".join(part for part in parts if part)
        return ""

    def _format_context(self, chunks: Sequence[Any]) -> str:
        if not chunks:
            return "No context was provided for this topic."

        lines: list[str] = []
        seen_ids = set()
        for chunk in chunks:
            chunk_id = self._get_chunk_attr(chunk, "id", "unknown")
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)

            content = self._get_chunk_attr(chunk, "content", "")
            resource_id = self._get_chunk_attr(chunk, "resource_id", "")
            section = self._get_chunk_attr(chunk, "top_level_section_title", "")
            prefix = f"[Chunk {chunk_id}]"
            if resource_id != "":
                prefix += f" Resource {resource_id}"
            if section:
                prefix += f" | Section: {section}"

            lines.append(prefix)
            lines.append(str(content))
        return "\n".join(lines)

    def _extract_chunk_ids(self, chunks: Sequence[Any]) -> list[Any]:
        return [self._get_chunk_attr(chunk, "id", None) for chunk in chunks]

    def _get_chunk_attr(self, chunk: Any, attr: str, default: Any) -> Any:
        if isinstance(chunk, dict):
            return chunk.get(attr, default)
        return getattr(chunk, attr, default)

    def _apply_total_question_instruction(self, exam_json: dict[str, Any]) -> None:
        section_a_count = int(
            exam_json.get("section_A", {}).get("total_num_questions", 0)
        )
        section_b_count = int(
            exam_json.get("section_B", {}).get("total_num_questions", 0)
        )
        section_c_count = int(
            exam_json.get("section_C", {}).get("total_num_questions", 0)
        )
        total = section_a_count + section_b_count + section_c_count

        instructions = exam_json.get("instructions", [])
        exam_json["instructions"] = [
            str(line).replace("NUM_QUESTIONS_PLACEHOLDER", str(total))
            for line in instructions
        ]

    def _fill_required_fallbacks(self, exam_json: dict[str, Any], subject: str) -> None:
        meta = exam_json.setdefault("meta", {})
        meta.setdefault("country", "THE UNITED REPUBLIC OF TANZANIA")
        meta.setdefault(
            "office",
            "PRESIDENT'S OFFICE\nREGIONAL ADMINISTRATION AND LOCAL GOVERNMENT",
        )
        meta.setdefault("exam_title", "GENERATED PRACTICE EXAM")
        meta.setdefault("subject", subject.upper())
        meta.setdefault("duration", "3:00 Hrs")
        meta.setdefault("year", datetime.now(timezone.utc).year)

        exam_json.setdefault("instructions", [])
        exam_json.setdefault("constants", {})
        exam_json.setdefault("section_A", {})
        exam_json.setdefault("section_B", {})
        exam_json.setdefault("section_C", {})

    def _set_generation_trace(
        self,
        exam_json: dict[str, Any],
        chunks_by_topic: dict[str, list[Any]],
    ) -> None:
        exam_json["generation_trace"] = {
            "exam_id": str(uuid.uuid4()),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "topics": list(chunks_by_topic.keys()),
            "topic_chunk_ids": {
                topic: self._extract_chunk_ids(chunk_list)
                for topic, chunk_list in chunks_by_topic.items()
            },
        }


exam_generator = ExamGenerator()
