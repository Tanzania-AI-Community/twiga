"""Add expired value to feedback invite status enum

Revision ID: c1b84f2d9e11
Revises: 9f3c1a2b7d10
Create Date: 2026-03-16 13:10:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c1b84f2d9e11"
down_revision: Union[str, None] = "9f3c1a2b7d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE feedbackinvitestatus ADD VALUE IF NOT EXISTS 'expired'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without recreating the type.
    pass
