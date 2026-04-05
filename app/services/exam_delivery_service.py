import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import app.database.db as db
from app.services.exam_pdf_generation_service import (
    render_exam_pdf,
    render_exam_solution_pdf,
)
from app.utils.paths import paths

EXAM_DELIVERY_MARKER_RE = re.compile(
    r"\{\{?TWIGA_EXAM_DELIVERY:\s*(\{.*?\})\}\}?",
    re.DOTALL,
)


@dataclass
class ExamDeliveryMarker:
    marker_found: bool
    marker_valid: bool
    exam_id: Optional[str]
    cleaned_content: str


@dataclass
class ExamPDFDeliveryDetails:
    exam_id: Optional[str]
    exam_pdf_path: Optional[Path]
    solution_pdf_path: Optional[Path]
    exam_pdf_ready: bool
    solution_pdf_ready: bool
    subject: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ExamDeliveryService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        paths.EXAM_PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def parse_delivery_marker(self, content: str | None) -> ExamDeliveryMarker:
        if content is None:
            self.logger.warning(
                "Skipping exam delivery marker parsing because content is None."
            )
            return ExamDeliveryMarker(
                marker_found=False,
                marker_valid=False,
                exam_id=None,
                cleaned_content="",
            )

        matches = list(EXAM_DELIVERY_MARKER_RE.finditer(content))
        if not matches:
            self.logger.warning(
                "No exam delivery marker found in assistant content. Returning original content."
            )
            return ExamDeliveryMarker(
                marker_found=False,
                marker_valid=False,
                exam_id=None,
                cleaned_content=content,
            )

        cleaned_content = EXAM_DELIVERY_MARKER_RE.sub("", content).strip()
        for match in matches:
            payload = self._parse_marker_payload(match.group(1))
            if payload is None:
                continue

            exam_id = self._get_exam_id_in_expected_format(payload.get("exam_id"))
            if exam_id is not None:
                return ExamDeliveryMarker(
                    marker_found=True,
                    marker_valid=True,
                    exam_id=exam_id,
                    cleaned_content=cleaned_content,
                )

        return ExamDeliveryMarker(
            marker_found=True,
            marker_valid=False,
            exam_id=None,
            cleaned_content=cleaned_content,
        )

    async def get_exam_delivery_details(self, exam_id: str) -> ExamPDFDeliveryDetails:
        exam_id = self._get_exam_id_in_expected_format(exam_id)
        if exam_id is None:
            return ExamPDFDeliveryDetails(
                exam_id=None,
                exam_pdf_path=None,
                solution_pdf_path=None,
                exam_pdf_ready=False,
                solution_pdf_ready=False,
                subject=None,
                topics=[],
                errors=[
                    f"Invalid exam_id format provided for exam delivery with exam_id: {exam_id}"
                ],
            )

        exam_pdf_path, solution_pdf_path = self._resolve_exam_pdf_paths(exam_id)
        exam_pdf_ready = exam_pdf_path.exists()
        solution_pdf_ready = solution_pdf_path.exists()
        errors: list[str] = []
        subject: Optional[str] = None
        topics: list[str] = []
        exam_json: Optional[dict] = None

        try:
            exam_record = await db.get_exam(exam_id)
        except Exception as exc:
            self.logger.error(
                f"Failed to load exam record for exam_id={exam_id}: {exc}",
                exc_info=True,
            )
            exam_record = None

        if exam_record is not None:
            exam_json = exam_record.exam_json
            subject = exam_record.subject
            topics = exam_record.topics

        if exam_pdf_ready and solution_pdf_ready:
            return ExamPDFDeliveryDetails(
                exam_id=exam_id,
                exam_pdf_path=exam_pdf_path,
                solution_pdf_path=solution_pdf_path,
                exam_pdf_ready=True,
                solution_pdf_ready=True,
                subject=subject,
                topics=topics,
                errors=[],
            )

        if exam_json is None:
            errors.append(f"Exam {exam_id} not found in generated_exams.")
            return ExamPDFDeliveryDetails(
                exam_id=exam_id,
                exam_pdf_path=exam_pdf_path,
                solution_pdf_path=solution_pdf_path,
                exam_pdf_ready=exam_pdf_ready,
                solution_pdf_ready=solution_pdf_ready,
                subject=subject,
                topics=topics,
                errors=errors,
            )

        if not exam_pdf_ready:
            try:
                render_exam_pdf(
                    exam_json=exam_json,
                    output_path=exam_pdf_path,
                )

                exam_pdf_ready = exam_pdf_path.exists()
                if not exam_pdf_ready:
                    errors.append(f"Exam PDF was not created for exam_id={exam_id}.")
            except Exception as exc:
                self.logger.error(
                    f"Failed to build exam PDF for exam_id={exam_id}: {exc}",
                    exc_info=True,
                )
                errors.append(f"Failed to render exam PDF for exam_id={exam_id}.")

        if not solution_pdf_ready:
            try:
                render_exam_solution_pdf(
                    exam_json=exam_json,
                    output_path=solution_pdf_path,
                )

                solution_pdf_ready = solution_pdf_path.exists()
                if not solution_pdf_ready:
                    errors.append(
                        f"Solution PDF was not created for exam_id={exam_id}."
                    )
            except Exception as exc:
                self.logger.error(
                    f"Failed to build solution PDF for exam_id={exam_id}: {exc}",
                    exc_info=True,
                )
                errors.append(f"Failed to render solution PDF for exam_id={exam_id}.")

        return ExamPDFDeliveryDetails(
            exam_id=exam_id,
            exam_pdf_path=exam_pdf_path,
            solution_pdf_path=solution_pdf_path,
            exam_pdf_ready=exam_pdf_ready,
            solution_pdf_ready=solution_pdf_ready,
            subject=subject,
            topics=topics,
            errors=errors,
        )

    @staticmethod
    def _resolve_exam_pdf_paths(exam_id: str) -> tuple[Path, Path]:
        return (
            paths.EXAM_PDF_OUTPUT_DIR / f"exam_{exam_id}.pdf",
            paths.EXAM_PDF_OUTPUT_DIR / f"exam_{exam_id}_solution.pdf",
        )

    @staticmethod
    def _parse_marker_payload(payload_str: str) -> Optional[dict]:
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        return payload

    @staticmethod
    def _get_exam_id_in_expected_format(raw_exam_id: object) -> Optional[str]:
        if not isinstance(raw_exam_id, str) or not raw_exam_id.strip():
            return None

        try:
            return str(uuid.UUID(raw_exam_id.strip()))
        except (ValueError, AttributeError, TypeError):
            return None


exam_delivery_service = ExamDeliveryService()
