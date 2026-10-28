"""Schema parity locally; PostgreSQL migration round trip is explicitly opt-in."""

from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Index,
    MetaData,
    Table,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import dialect

from app.database.models import ConversationSummaryBatch, ConversationSummaryState
from tests.database import conversation_summary_fixtures as summary_fixtures

summary_pg_schema = summary_fixtures.summary_pg_schema

ROOT = Path(__file__).resolve().parents[2]
REVISION = "b7e2c9a4f610"
PARENT = "a1f4c7e2d3b9"


def scripts():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_migration_matches_model_schema_and_source_parent(monkeypatch):
    source = scripts()
    revision = source.get_revision(REVISION)
    assert revision.down_revision == PARENT
    assert source.get_heads() == [REVISION]
    metadata = MetaData()

    class Recorder:
        @staticmethod
        def create_table(name, *args):
            return Table(name, metadata, *args)

        @staticmethod
        def create_index(name, table_name, columns):
            table = metadata.tables[table_name]
            Index(name, *(table.c[column] for column in columns))

    monkeypatch.setattr(revision.module, "op", Recorder)
    revision.module.upgrade()
    assert set(metadata.tables) == {
        "conversation_summary_state",
        "conversation_summary_batches",
    }
    for model in (ConversationSummaryState, ConversationSummaryBatch):
        actual = metadata.tables[model.__tablename__]
        expected = model.__table__
        assert set(actual.c.keys()) == set(expected.c.keys())
        for column in actual.c:
            other = expected.c[column.name]
            assert str(column.type.compile(dialect=dialect())) == str(
                other.type.compile(dialect=dialect())
            )
            assert (column.nullable, column.primary_key) == (
                other.nullable,
                other.primary_key,
            )
            actual_default = (
                str(column.server_default.arg) if column.server_default else None
            )
            expected_default = (
                str(other.server_default.arg) if other.server_default else None
            )
            assert actual_default == expected_default
        for cls in (CheckConstraint, UniqueConstraint):

            def signature(table):
                return {
                    (
                        c.name,
                        str(c.sqltext)
                        if isinstance(c, CheckConstraint)
                        else tuple(c.columns.keys()),
                    )
                    for c in table.constraints
                    if isinstance(c, cls)
                }

            assert signature(actual) == signature(expected)
        assert {
            (fk.parent.name, fk.target_fullname, fk.ondelete)
            for fk in actual.foreign_keys
        } == {
            (fk.parent.name, fk.target_fullname, fk.ondelete)
            for fk in expected.foreign_keys
        }
        assert {
            (i.name, tuple(i.columns.keys()), i.unique) for i in actual.indexes
        } == {(i.name, tuple(i.columns.keys()), i.unique) for i in expected.indexes}


def test_migration_offline_upgrade_and_downgrade_are_feature_scoped():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    migration = scripts().get_revision(REVISION).module
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE conversation_summary_state" in sql
    assert "CREATE TABLE conversation_summary_batches" in sql
    assert "UNIQUE (user_id, sequence_number)" in sql
    assert "ON DELETE CASCADE" in sql
    assert "DROP TABLE conversation_summary_batches" in sql
    assert "DROP TABLE conversation_summary_state" in sql
    assert "ALTER TABLE messages" not in sql and "DELETE FROM messages" not in sql
    assert "ALTER TYPE" not in sql


@pytest.mark.integration
def test_postgres_parent_upgrade_downgrade_upgrade_preserves_originals(
    summary_pg_schema,
):
    _, schema, engine = summary_pg_schema
    source = scripts()
    with engine.connect() as connection:
        # Full parent schema requires pgvector, as does the application itself.
        if not connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ):
            pytest.skip(
                "Migration chain requires pgvector installed in the explicit disposable database"
            )
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        for migration in reversed(list(source.iterate_revisions(PARENT, "base"))):
            context = MigrationContext.configure(connection)
            with context.begin_transaction(), Operations.context(context):
                migration.module.upgrade()
            connection.commit()
        connection.execute(
            text(
                "INSERT INTO users (id, name, wa_id, state, role, updated_at) VALUES (1, 'One', 'migration-one', 'active', 'teacher', now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO messages (id, user_id, role, content, is_present_in_conversation) VALUES (1, 1, 'user', 'Original Unicode: habari 🌍', true), (2, 1, 'assistant', 'Hidden raw response', false)"
            )
        )
        connection.commit()
        baseline = connection.execute(
            text(
                "SELECT id, user_id, role, content, is_present_in_conversation, created_at FROM messages ORDER BY id"
            )
        ).all()
        users_before = connection.execute(text("SELECT * FROM users ORDER BY id")).all()
        connection.commit()
        migration = source.get_revision(REVISION).module
        for operation in (migration.upgrade, migration.downgrade, migration.upgrade):
            with connection.begin():
                with Operations.context(MigrationContext.configure(connection)):
                    operation()
            assert (
                connection.execute(
                    text(
                        "SELECT id, user_id, role, content, is_present_in_conversation, created_at FROM messages ORDER BY id"
                    )
                ).all()
                == baseline
            )
            assert (
                connection.execute(text("SELECT * FROM users ORDER BY id")).all()
                == users_before
            )
            connection.commit()
        inspector = inspect(connection)
        assert "conversation_summary_state" in inspector.get_table_names(schema=schema)
        assert "conversation_summary_batches" in inspector.get_table_names(
            schema=schema
        )
        assert any(
            c["column_names"] == ["user_id", "sequence_number"]
            for c in inspector.get_unique_constraints(
                "conversation_summary_batches", schema=schema
            )
        )
