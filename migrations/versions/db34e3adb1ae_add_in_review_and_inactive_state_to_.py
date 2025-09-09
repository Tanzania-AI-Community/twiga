"""Add in_review and inactive state to UserState enum

Revision ID: db34e3adb1ae
Revises: d05f01339caa
Create Date: 2025-09-08 19:54:28.566315

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "db34e3adb1ae"
down_revision: Union[str, None] = "c4a17d67d125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values to UserState
    op.execute("ALTER TYPE userstate ADD VALUE IF NOT EXISTS 'in_review'")
    # Note: 'inactive' might already exist, so using IF NOT EXISTS is safer
    op.execute("ALTER TYPE userstate ADD VALUE IF NOT EXISTS 'inactive'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily
    # You would need to recreate the enum type to remove values
    pass
