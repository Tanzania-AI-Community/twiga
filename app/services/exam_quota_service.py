import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.config import settings
from app.database import db
from app.database.enums import ExamReservationStatus

logger = logging.getLogger(__name__)


class QuotaOutcome(str, Enum):
    ALLOWED = "allowed"  # reservation created: generate the exam
    REUSE = "reuse"  # same exam finished recently: return it
    IN_PROGRESS = "in_progress"  # same exam is being generated right now
    DENIED = "denied"  # the user reached the limit


@dataclass(frozen=True)
class QuotaDecision:
    outcome: QuotaOutcome
    reservation_id: str | None = None  # for ALLOWED
    exam_id: str | None = None  # for REUSE
    next_available_at: datetime | None = None  # for DENIED


def exam_request_key(class_id: int, subject: str, topics: list[str]) -> str:
    """Identify "the same exam request", ignoring topic order, case and spacing."""

    def normalise(value: str) -> str:
        return " ".join(value.lower().split())

    normalised_topics = sorted({normalise(topic) for topic in topics} - {""})
    raw = json.dumps([class_id, normalise(subject), normalised_topics])
    return hashlib.sha256(raw.encode()).hexdigest()


class ExamQuotaService:
    async def reserve(self, user_id: int, request_key: str) -> QuotaDecision:
        """Atomically decide whether this request may generate an exam."""
        limits = self._limits()
        reservation, created = await db.reserve_exam_generation(
            user_id, request_key, **limits
        )
        if created:
            return QuotaDecision(QuotaOutcome.ALLOWED, reservation_id=reservation.id)
        return await self._decision_without_new_slot(user_id, reservation, limits)

    async def preview(self, user_id: int, request_key: str) -> QuotaDecision:
        """Read-only reserve(): what it would decide now. ALLOWED has no reservation."""
        limits = self._limits()
        existing, slot_free = await db.preview_exam_generation(
            user_id, request_key, **limits
        )
        if slot_free:
            return QuotaDecision(QuotaOutcome.ALLOWED)
        return await self._decision_without_new_slot(user_id, existing, limits)

    @staticmethod
    def _limits() -> dict:
        now = datetime.now(timezone.utc)
        return {
            "limit": settings.exam_generation_limit,
            "window_start": now - timedelta(days=settings.exam_generation_window_days),
            "pending_since": now
            - timedelta(minutes=settings.exam_reservation_timeout_minutes),
            "reuse_since": now - timedelta(minutes=settings.exam_reuse_window_minutes),
        }

    async def _decision_without_new_slot(
        self, user_id: int, existing, limits: dict
    ) -> QuotaDecision:
        if existing is None:
            return QuotaDecision(
                QuotaOutcome.DENIED,
                next_available_at=await self._next_available_at(user_id, limits),
            )
        if existing.status == ExamReservationStatus.completed:
            return QuotaDecision(QuotaOutcome.REUSE, exam_id=existing.exam_id)
        return QuotaDecision(QuotaOutcome.IN_PROGRESS)

    @staticmethod
    async def _next_available_at(user_id: int, limits: dict) -> datetime:
        """When the oldest counted slot leaves the window, freeing one."""
        oldest = await db.get_oldest_counted_exam_slot_at(
            user_id,
            window_start=limits["window_start"],
            pending_since=limits["pending_since"],
        )
        if oldest is None:  # slots were freed since the check: available now
            return datetime.now(timezone.utc)
        return oldest + timedelta(days=settings.exam_generation_window_days)

    # complete and release are best effort: the exam (or the error) matters more
    # to the teacher than the bookkeeping, and a reservation left pending stops
    # counting after EXAM_RESERVATION_TIMEOUT_MINUTES.

    async def complete(self, reservation_id: str, exam_id: str) -> None:
        try:
            await db.mark_exam_reservation_completed(reservation_id, exam_id)
        except Exception:
            logger.exception("Could not complete exam reservation %s", reservation_id)

    async def release(self, reservation_id: str) -> None:
        try:
            await db.mark_exam_reservation_failed(reservation_id)
        except Exception:
            logger.exception("Could not release exam reservation %s", reservation_id)


exam_quota_service = ExamQuotaService()
