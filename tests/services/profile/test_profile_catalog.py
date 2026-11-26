import asyncio
from unittest.mock import AsyncMock, patch

from app.database.enums import GradeLevel, SubjectName
from app.database.models import Subject
from app.services.profile.catalog import Catalog, CatalogCache, available_catalog


def test_build_catalog_keeps_only_active_classes(catalog: Catalog) -> None:
    assert catalog.class_id(SubjectName.geography, GradeLevel.os2) == 102
    assert catalog.class_id(SubjectName.geography, GradeLevel.as1) is None
    assert not catalog.offers(SubjectName.commerce)


def test_catalog_enums_for_tool_schema(catalog: Catalog) -> None:
    assert catalog.subject_enum() == [
        "chemistry",
        "english",
        "geography",
        "history",
        "physics",
    ]
    assert catalog.form_enum() == ["Form 1", "Form 2", "Form 3", "Form 4"]


def test_catalog_class_keys_reverse_lookup(catalog: Catalog) -> None:
    assert catalog.class_keys()[201] == (SubjectName.english, GradeLevel.os1)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_catalog_cache_reuses_until_ttl_expires() -> None:
    clock = _Clock()
    loader = AsyncMock(side_effect=lambda: Catalog(classes={}))
    cache = CatalogCache(loader=loader, ttl_seconds=10, clock=clock)

    await cache.get()
    clock.now = 9
    await cache.get()
    assert loader.await_count == 1

    clock.now = 10
    await cache.get()
    assert loader.await_count == 2


async def test_catalog_cache_invalidate_forces_reload() -> None:
    loader = AsyncMock(return_value=Catalog(classes={}))
    cache = CatalogCache(loader=loader, clock=_Clock())

    await cache.get()
    cache.invalidate()
    await cache.get()

    assert loader.await_count == 2


async def test_catalog_cache_loads_once_for_concurrent_callers() -> None:
    async def slow_loader() -> Catalog:
        await asyncio.sleep(0)
        return Catalog(classes={})

    loader = AsyncMock(side_effect=slow_loader)
    cache = CatalogCache(loader=loader, clock=_Clock())

    await asyncio.gather(*(cache.get() for _ in range(5)))

    assert loader.await_count == 1


async def test_available_catalog_reads_subjects_from_db(
    catalog_subjects: list[Subject],
) -> None:
    with (
        patch(
            "app.services.profile.catalog.db.read_subjects",
            AsyncMock(return_value=catalog_subjects),
        ),
        patch("app.services.profile.catalog.catalog_cache", CatalogCache()),
    ):
        catalog = await available_catalog()

    assert catalog.offers(SubjectName.history)
