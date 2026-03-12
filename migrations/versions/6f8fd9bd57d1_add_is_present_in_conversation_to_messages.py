"""Add is_present_in_conversation to messages

Revision ID: 6f8fd9bd57d1
Revises: 40ef9772ad6c
Create Date: 2026-03-07 14:49:30.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f8fd9bd57d1"
down_revision: Union[str, None] = "40ef9772ad6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "is_present_in_conversation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("messages", "is_present_in_conversation", server_default=None)


def downgrade() -> None:
    op.drop_column("messages", "is_present_in_conversation")
