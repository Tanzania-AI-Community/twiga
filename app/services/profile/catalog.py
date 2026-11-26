"""The subjects and forms a teacher can choose: active classes only."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field

import app.database.db as db
from app.database.enums import GradeLevel, SubjectClassStatus, SubjectName
from app.database.models import Subject
from app.services.profile.class_math import ClassKey

CATALOG_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class Catalog:
    classes: Mapping[SubjectName, Mapping[GradeLevel, int]]
    _keys_by_class_id: Mapping[int, ClassKey] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        keys = {
            class_id: (subject, grade)
            for subject, grades in self.classes.items()
            for grade, class_id in grades.items()
        }
        object.__setattr__(self, "_keys_by_class_id", keys)

    def class_id(self, subject: SubjectName, grade: GradeLevel) -> int | None:
        return self.classes.get(subject, {}).get(grade)

    def offers(self, subject: SubjectName) -> bool:
        return bool(self.classes.get(subject))

    def class_keys(self) -> Mapping[int, ClassKey]:
        return self._keys_by_class_id

    def subject_enum(self) -> list[str]:
        """Subject values for the tool schema, alphabetical."""
        return sorted(subject.value for subject in self.classes)

    def form_enum(self) -> list[str]:
        """Grade display names offered by any subject, in curriculum order."""
        offered = {grade for grades in self.classes.values() for grade in grades}
        return [grade.display_format for grade in GradeLevel if grade in offered]

    def readable_subjects(self) -> str:
        return ", ".join(
            subject.display_format
            for subject in sorted(self.classes, key=lambda s: s.value)
        )


def build_catalog(subjects: Iterable[Subject]) -> Catalog:
    classes: dict[SubjectName, dict[GradeLevel, int]] = {}
    for subject in subjects:
        for class_ in subject.subject_classes or []:
            if class_.id is None or class_.status != SubjectClassStatus.active:
                continue
            classes.setdefault(subject.name, {})[class_.grade_level] = class_.id
    return Catalog(classes=classes)


async def _load_catalog() -> Catalog:
    return build_catalog(await db.read_subjects() or [])


class CatalogCache:
    """In-process TTL cache; the catalog only changes when content is ingested."""

    def __init__(
        self,
        loader: Callable[[], Awaitable[Catalog]] = _load_catalog,
        ttl_seconds: float = CATALOG_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._loader = loader
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = asyncio.Lock()
        self._catalog: Catalog | None = None
        self._loaded_at = 0.0

    def _is_fresh(self) -> bool:
        return (
            self._catalog is not None
            and self._clock() - self._loaded_at < self._ttl_seconds
        )

    async def get(self) -> Catalog:
        if self._is_fresh():
            assert self._catalog is not None
            return self._catalog
        async with self._lock:
            # Another caller may have refreshed it while we waited
            if not self._is_fresh():
                self._catalog = await self._loader()
                self._loaded_at = self._clock()
            assert self._catalog is not None
            return self._catalog

    def invalidate(self) -> None:
        self._catalog = None


catalog_cache = CatalogCache()


async def available_catalog() -> Catalog:
    return await catalog_cache.get()
