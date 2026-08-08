from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql
from sqlmodel.sql.expression import SelectOfScalar

from app.database import db, enums
from app.database.models import User

INACTIVE_BEFORE = datetime(2026, 1, 2, tzinfo=timezone.utc)
COOLDOWN_BEFORE = datetime(2026, 1, 5, tzinfo=timezone.utc)


def _compile_statement(
    statement: SelectOfScalar[User],
) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    normalized_sql = " ".join(str(compiled).split())
    return normalized_sql, compiled.params


def test_users_by_state_filters_for_requested_state() -> None:
    statement = db._build_users_by_state_statement(enums.UserState.approved)

    sql, parameters = _compile_statement(statement)

    assert (
        "WHERE users.state =" in sql
        and parameters["state_1"] is enums.UserState.approved
    )


def test_users_to_mark_inactive_only_selects_active_users() -> None:
    statement = db._build_users_to_mark_inactive_statement(INACTIVE_BEFORE)

    _, parameters = _compile_statement(statement)

    assert parameters["state_1"] is enums.UserState.active


def test_users_to_mark_inactive_includes_users_without_messages() -> None:
    statement = db._build_users_to_mark_inactive_statement(INACTIVE_BEFORE)

    sql, _ = _compile_statement(statement)

    assert "users.last_message_at IS NULL OR users.last_message_at <" in sql


def test_users_for_reminder_only_selects_eligible_states() -> None:
    statement = db._build_users_for_reminder_statement(
        INACTIVE_BEFORE,
        COOLDOWN_BEFORE,
    )

    _, parameters = _compile_statement(statement)

    assert parameters["state_1"] == [
        enums.UserState.active,
        enums.UserState.inactive,
        enums.UserState.onboarding,
    ]


def test_users_for_reminder_requires_previous_activity() -> None:
    statement = db._build_users_for_reminder_statement(
        INACTIVE_BEFORE,
        COOLDOWN_BEFORE,
    )

    sql, parameters = _compile_statement(statement)

    assert (
        "users.last_message_at IS NOT NULL" in sql
        and parameters["last_message_at_1"] == INACTIVE_BEFORE
    )


def test_users_for_reminder_scopes_history_to_reminder_cron() -> None:
    statement = db._build_users_for_reminder_statement(
        INACTIVE_BEFORE,
        COOLDOWN_BEFORE,
    )

    sql, parameters = _compile_statement(statement)

    assert (
        "messages.cron_name =" in sql
        and parameters["cron_name_1"]
        is enums.MessageCronName.send_reminder_messages_cron
    )


def test_users_for_reminder_accepts_users_outside_cooldown() -> None:
    statement = db._build_users_for_reminder_statement(
        INACTIVE_BEFORE,
        COOLDOWN_BEFORE,
    )

    sql, parameters = _compile_statement(statement)

    assert (
        "last_reminder_at IS NULL OR anon_1.last_reminder_at <" in sql
        and parameters["last_reminder_at_1"] == COOLDOWN_BEFORE
    )
