from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.database import db


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _sql(statement) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def _executed_sql(session: MagicMock) -> list[str]:
    return [_sql(call.args[0]) for call in session.execute.await_args_list]


async def test_set_teacher_classes_replaces_rows_and_class_info_in_one_session() -> (
    None
):
    session = MagicMock()
    session.execute = AsyncMock()

    with patch(
        "app.database.db.get_session", MagicMock(return_value=_SessionContext(session))
    ) as get_session:
        await db.set_teacher_classes(7, [101, 201], {"geography": ["os1"]})

    get_session.assert_called_once()
    statements = _executed_sql(session)
    assert statements[0].startswith("DELETE FROM teachers_classes")
    assert statements[1].startswith("INSERT INTO teachers_classes")
    assert session.execute.await_args_list[1].args[1] == [
        {"teacher_id": 7, "class_id": 101},
        {"teacher_id": 7, "class_id": 201},
    ]
    assert statements[2].startswith("UPDATE users SET class_info")


async def test_set_teacher_classes_skips_insert_when_no_classes() -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    with patch(
        "app.database.db.get_session", MagicMock(return_value=_SessionContext(session))
    ):
        await db.set_teacher_classes(7, [], {})

    statements = _executed_sql(session)
    assert len(statements) == 2
    assert not any(s.startswith("INSERT") for s in statements)


async def test_set_teacher_classes_wraps_failures() -> None:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch(
            "app.database.db.get_session",
            MagicMock(return_value=_SessionContext(session)),
        ),
        pytest.raises(Exception, match="Failed to set teacher classes"),
    ):
        await db.set_teacher_classes(7, [101], {"geography": ["os1"]})
