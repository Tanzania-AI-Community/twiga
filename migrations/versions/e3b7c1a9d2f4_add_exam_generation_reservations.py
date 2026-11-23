"""add exam_generation_reservations table

Revision ID: e3b7c1a9d2f4
Revises: a1f4c7e2d3b9
Create Date: 2026-11-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b7c1a9d2f4"
down_revision: Union[str, None] = "a1f4c7e2d3b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STATUS_ENUM_NAME = "examreservationstatus"
STATUS_VALUES = ("pending", "completed", "failed")
TABLE_NAME = "exam_generation_reservations"
INDEX_NAME = "ix_exam_generation_reservations_user_id_created_at"


def upgrade() -> None:
    # create_table also creates the enum type
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*STATUS_VALUES, name=STATUS_ENUM_NAME),
            nullable=False,
        ),
        sa.Column("exam_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["generated_exams.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(INDEX_NAME, TABLE_NAME, ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)

    status_enum = sa.Enum(*STATUS_VALUES, name=STATUS_ENUM_NAME)
    status_enum.drop(op.get_bind(), checkfirst=True)
