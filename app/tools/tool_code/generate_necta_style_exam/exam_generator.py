import copy
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from langchain_core.messages import HumanMessage, SystemMessage
from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager


logger = logging.getLogger(__name__)


class ExamGenerationError(Exception):
    """Raised when exam JSON generation fails."""


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
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "ExamSpecification":
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

    def __init__(self, template_dir: Optional[Path] = None) -> None:
        self.template_dir = template_dir or (Path(__file__).parent / "template")
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
        chunks_by_topic: Dict[str, List[Any]],
        exam_spec: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
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

        section_a_questions: List[Dict[str, Any]] = []
        section_b_questions: List[Dict[str, Any]] = []
        section_c_questions: List[Dict[str, Any]] = []

        # track already generated questions, modified in place during question generation
        previous_questions: List[str] = []

        if spec.num_section_a_mcq_items > 0:
            mcq_block = await self._build_mcq_block(
                subject=subject,
                topics=topics,
                chunks_by_topic=chunks_by_topic,
                num_items=spec.num_section_a_mcq_items,
                previous_questions=previous_questions,
                difficulty=spec.default_difficulty,
            )
            section_a_questions.append(mcq_block)

        for idx in range(max(0, spec.num_section_a_matching_questions)):
            topic = topics[
                idx % len(topics)
            ]  # maybe make this more randomized in the future
            matching_q = await self._generate_single_question(
                question_type="item_matching",
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.matching_template,
                question_id=f"A-Q{idx + 2}",
                num_marks=5,
                difficulty=spec.default_difficulty,
            )
            section_a_questions.append(matching_q)

        for idx in range(max(0, spec.num_section_b_short_answer_questions)):
            topic = topics[idx % len(topics)]
            short_q = await self._generate_single_question(
                question_type="short_answer",
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.short_answer_template,
                question_id=f"B-Q{idx + 3}",
                num_marks=14,
                difficulty=spec.default_difficulty,
            )
            section_b_questions.append(short_q)

        for idx in range(max(0, spec.num_section_c_long_answer_questions)):
            topic = topics[idx % len(topics)]
            long_q = await self._generate_single_question(
                question_type="long_answer",
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.long_answer_template,
                question_id=f"C-Q{idx + 13}",
                num_marks=15,
                difficulty="hard",
            )
            section_c_questions.append(long_q)

        section_a["question_list"] = section_a_questions
        section_b["question_list"] = section_b_questions
        section_c["question_list"] = section_c_questions
        section_a["total_num_questions"] = len(section_a_questions)
        section_b["total_num_questions"] = len(section_b_questions)
        section_c["total_num_questions"] = len(section_c_questions)

        self._apply_total_question_instruction(exam_json)
        self._fill_required_fallbacks(exam_json, subject=subject)
        self._set_generation_trace(exam_json, chunks_by_topic)
        return exam_json

    def _load_template_json(self, filename: str) -> Dict[str, Any]:
        path = self.template_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ExamGenerationError(f"Missing template file: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ExamGenerationError(f"Invalid JSON in template file: {path}") from exc

    def _fill_exam_metadata(
        self,
        exam_json: Dict[str, Any],
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
        chunks_by_topic: Dict[str, List[Any]],
        num_items: int,
        previous_questions: List[str],
        difficulty: str,
    ) -> Dict[str, Any]:
        """
        Builds a block of multiple choice questions for Section A.
        """
        items: List[Dict[str, Any]] = []

        for question_num in range(num_items):
            topic = topics[question_num % len(topics)]
            item = await self._generate_single_question(
                question_type="multiple_choice",
                subject=subject,
                topic=topic,
                chunk_list=chunks_by_topic.get(topic, []),
                previous_questions=previous_questions,
                template=self.mcq_template,
                question_id=f"A-Q1-{question_num + 1}",
                num_marks=1,
                difficulty=difficulty,
            )

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
            "type": "multiple_choice",
            "marks": num_items,
            "prompt": "For each of the following items, choose the correct answer among the given alternatives and write its letter beside the item number provided.",
            "items": items,
            "metadata": {
                "topic": ", ".join(topics),
                "difficulty": difficulty,
            },
        }

    async def _generate_single_question(
        self,
        question_type: str,
        subject: str,
        topic: str,
        chunk_list: Sequence[Any],
        previous_questions: List[str],
        template: Dict[str, Any],
        question_id: str,
        num_marks: int,
        difficulty: str,
    ) -> Dict[str, Any]:
        context_str = self._format_context(chunk_list)
        previous_questions_str = (
            "\n".join(previous_questions) if previous_questions else "None"
        )

        system_prompt = prompt_manager.format_prompt("exam_generator_system")
        user_prompt = prompt_manager.format_prompt(
            "exam_generator_user",
            question_type=question_type,
            topic=topic,
            previous_questions=previous_questions_str,
            context_str=context_str,
        )

        constraints = self._constraints_for(question_type)
        prompt_template = self._template_without_system_fields(template)
        template_json = json.dumps(prompt_template, indent=2, ensure_ascii=False)
        user_prompt_with_template = (
            f"{user_prompt}\n\n"
            f"Additional constraints:\n{constraints}\n\n"
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
                "question_type": question_type,
            },
        )

        logger.debug(
            f"Raw LLM response content for question generation (question_type={question_type}, topic={topic}): {response.content if response else 'No response'}"
        )

        parsed = self._parse_json_response(response.content if response else "")
        merged = self._merge_with_template(template=template, payload=parsed)

        # set the system fields
        merged["id"] = question_id
        merged["marks"] = num_marks
        metadata = merged.setdefault("metadata", {})
        metadata["topic"] = metadata.get("topic") or topic
        metadata["difficulty"] = metadata.get("difficulty") or difficulty
        merged["source_chunk_ids"] = self._extract_chunk_ids(chunk_list)

        # track previous questions by their signature to help the LLM avoid repetition and encourage diversity in question phrasing and focus
        signature = self._question_signature(
            question_type=question_type, payload=merged
        )
        if signature:
            previous_questions.append(signature)
        return merged

    def _constraints_for(self, question_type: str) -> str:
        constraints_list = self.question_constraints.get(question_type, [])
        constraints_str = ""
        if constraints_list:
            constraints_str += "\n".join(
                f"- {constraint}" for constraint in constraints_list
            )
        constraints_str += "\n- Keep output valid and concise."
        return constraints_str

    def _parse_json_response(self, raw_content: Any) -> Dict[str, Any]:
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
            merged: Dict[str, Any] = {}
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
        self, template: Dict[str, Any]
    ) -> Dict[str, Any]:
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

    def _normalize_mcq_options(self, options: Any) -> List[Dict[str, str]]:
        if isinstance(options, dict):
            return [
                {"label": label, "text": str(options.get(label, ""))}
                for label in self.MCQ_OPTION_LABELS
                if label in options
            ]

        if not isinstance(options, list):
            return []

        normalized: List[Dict[str, str]] = []
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

    def _normalize_mcq_answer(self, payload: Dict[str, Any]) -> Optional[str]:
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

    def _question_signature(self, question_type: str, payload: Dict[str, Any]) -> str:
        if question_type == "multiple_choice":
            return str(payload.get("question", "")).strip()
        if question_type == "item_matching":
            return str(payload.get("prompt", "")).strip()
        if question_type == "short_answer":
            return str(payload.get("question_description", "")).strip()
        if question_type == "long_answer":
            return str(payload.get("question", "")).strip()
        return ""

    def _format_context(self, chunks: Sequence[Any]) -> str:
        if not chunks:
            return "No context was provided for this topic."

        lines: List[str] = []
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

    def _extract_chunk_ids(self, chunks: Sequence[Any]) -> List[Any]:
        return [self._get_chunk_attr(chunk, "id", None) for chunk in chunks]

    def _get_chunk_attr(self, chunk: Any, attr: str, default: Any) -> Any:
        if isinstance(chunk, dict):
            return chunk.get(attr, default)
        return getattr(chunk, attr, default)

    def _apply_total_question_instruction(self, exam_json: Dict[str, Any]) -> None:
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

    def _fill_required_fallbacks(self, exam_json: Dict[str, Any], subject: str) -> None:
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
        exam_json: Dict[str, Any],
        chunks_by_topic: Dict[str, List[Any]],
    ) -> None:
        exam_json["generation_trace"] = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "topics": list(chunks_by_topic.keys()),
            "topic_chunk_ids": {
                topic: self._extract_chunk_ids(chunk_list)
                for topic, chunk_list in chunks_by_topic.items()
            },
        }
