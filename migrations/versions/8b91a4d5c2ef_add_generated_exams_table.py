"""add generated_exams table

Revision ID: 8b91a4d5c2ef
Revises: 6f8fd9bd57d1
Create Date: 2026-03-15 21:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b91a4d5c2ef"
down_revision: Union[str, None] = "6f8fd9bd57d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generated_exams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("json", sa.JSON(), nullable=False),
        sa.Column("generated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generated_exams_generated_at_utc"),
        "generated_exams",
        ["generated_at_utc"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_generated_exams_generated_at_utc"), table_name="generated_exams"
    )
    op.drop_table("generated_exams")
