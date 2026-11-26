"""The only writer of a teacher's name and classes."""

import logging
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager

import app.database.db as db
from app.database.enums import GradeLevel, SubjectName
from app.database.models import User
from app.services.profile.catalog import Catalog, available_catalog
from app.services.profile.class_math import (
    ClassKey,
    build_class_info,
    check_limits,
    compute_target_class_ids,
)
from app.services.profile.errors import ProfileErrorCode, ProfileUpdateError
from app.services.profile.models import (
    ClassUpdateAction,
    ProfileSnapshot,
    SubjectForms,
)
from app.services.profile.name_rules import validate_name

logger = logging.getLogger(__name__)

_MAX_REJECTED_LABEL_LENGTH = 40
_GRADE_ORDER = list(GradeLevel)


def _subject_label(subject: SubjectName) -> str:
    return subject.value.replace("_", " ").title()


def _current_class_keys(user: User) -> dict[int, ClassKey]:
    return {
        taught_class.class_id: (
            taught_class.class_.subject_.name,
            taught_class.class_.grade_level,
        )
        for taught_class in user.taught_classes or []
        if taught_class.class_ is not None
    }


class ProfileService:
    def __init__(
        self,
        catalog_provider: Callable[[], Awaitable[Catalog]] = available_catalog,
    ):
        self._catalog_provider = catalog_provider

    async def set_name(self, user: User, raw_name: str) -> ProfileSnapshot:
        with self._logged_update(user, field="name", action="set"):
            user.name = validate_name(raw_name)
            await db.update_user(user)
        return await self.snapshot(user)

    async def update_classes(
        self,
        user: User,
        action: ClassUpdateAction,
        requested: Sequence[SubjectForms],
        unrecognized: Sequence[str] = (),
    ) -> ProfileSnapshot:
        """Apply `action` to the teacher's classes and return the new profile.

        `unrecognized` holds subject names the caller could not map to a
        `SubjectName` (e.g. "Kiswahili"); they are reported back as rejected.
        """
        with self._logged_update(user, field="classes", action=action.value):
            catalog = await self._catalog_provider()
            fresh_user = await self._reload(user)
            current_keys = _current_class_keys(fresh_user)
            current = frozenset(current_keys)

            rejected_subjects = [
                label[:_MAX_REJECTED_LABEL_LENGTH] for label in unrecognized
            ]
            rejected_classes: list[str] = []
            if action is ClassUpdateAction.remove:
                requested_ids = self._ids_to_remove(current_keys, requested)
            else:
                requested_ids = self._ids_to_save(
                    catalog, requested, rejected_subjects, rejected_classes
                )
                if not requested_ids:
                    raise self._nothing_to_save_error(
                        catalog, rejected_subjects, rejected_classes
                    )

            target = compute_target_class_ids(current, action, requested_ids)
            class_keys = {**current_keys, **catalog.class_keys()}
            check_limits(target, class_keys)

            if target != current:
                assert fresh_user.id is not None
                await db.set_teacher_classes(
                    fresh_user.id,
                    sorted(target),
                    build_class_info(target, class_keys),
                )

        rejected = tuple(rejected_subjects + rejected_classes)
        return ProfileSnapshot.from_user(await self._reload(user), rejected=rejected)

    async def snapshot(self, user: User) -> ProfileSnapshot:
        return ProfileSnapshot.from_user(await self._reload(user))

    @staticmethod
    def _ids_to_remove(
        current_keys: dict[int, ClassKey], requested: Sequence[SubjectForms]
    ) -> frozenset[int]:
        """Current classes matching the request; no grades means the whole subject."""
        return frozenset(
            class_id
            for class_id, (subject, grade) in current_keys.items()
            for item in requested
            if item.subject == subject and (not item.grades or grade in item.grades)
        )

    @staticmethod
    def _ids_to_save(
        catalog: Catalog,
        requested: Sequence[SubjectForms],
        rejected_subjects: list[str],
        rejected_classes: list[str],
    ) -> frozenset[int]:
        class_ids: set[int] = set()
        for item in requested:
            label = _subject_label(item.subject)
            if not item.grades:
                raise ProfileUpdateError(
                    ProfileErrorCode.missing_forms,
                    f"Which forms do you teach {label} in?",
                )
            if not catalog.offers(item.subject):
                rejected_subjects.append(label)
                continue
            for grade in sorted(item.grades, key=_GRADE_ORDER.index):
                class_id = catalog.class_id(item.subject, grade)
                if class_id is None:
                    rejected_classes.append(f"{label} {grade.display_format}")
                else:
                    class_ids.add(class_id)
        return frozenset(class_ids)

    @staticmethod
    def _nothing_to_save_error(
        catalog: Catalog, rejected_subjects: list[str], rejected_classes: list[str]
    ) -> ProfileUpdateError:
        if rejected_classes:
            return ProfileUpdateError(
                ProfileErrorCode.class_unavailable,
                f"Not available yet: {', '.join(rejected_classes)}.",
            )
        if rejected_subjects:
            return ProfileUpdateError(
                ProfileErrorCode.unknown_subject,
                f"Not available yet: {', '.join(rejected_subjects)}. "
                f"Available subjects: {catalog.readable_subjects()}.",
            )
        return ProfileUpdateError(
            ProfileErrorCode.missing_forms,
            "Tell me which subjects you teach and in which forms.",
        )

    @staticmethod
    async def _reload(user: User) -> User:
        """Fetch the user with `taught_classes -> class_ -> subject_` loaded."""
        fresh_user = await db.get_user_by_waid(user.wa_id)
        if fresh_user is None:
            raise ValueError("User not found while updating the profile.")
        return fresh_user

    @staticmethod
    @contextmanager
    def _logged_update(user: User, field: str, action: str) -> Iterator[None]:
        # Values (e.g. the name) are never logged, only what changed and the outcome
        try:
            yield
        except ProfileUpdateError as error:
            logger.info(
                "profile.update user_id=%s field=%s action=%s result=%s",
                user.id,
                field,
                action,
                error.code.value,
            )
            raise
        logger.info(
            "profile.update user_id=%s field=%s action=%s result=ok",
            user.id,
            field,
            action,
        )


profile_service = ProfileService()
