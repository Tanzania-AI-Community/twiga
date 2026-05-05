"""Add source_chunk_ids to messages

Revision ID: 9a7d3f1c2b44
Revises: 8b91a4d5c2f0
Create Date: 2026-04-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a7d3f1c2b44"
down_revision: Union[str, None] = "8b91a4d5c2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("source_chunk_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "source_chunk_ids")
