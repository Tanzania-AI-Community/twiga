"""Add cron_name to messages

Revision ID: a1f4c7e2d3b9
Revises: 9a7d3f1c2b44
Create Date: 2026-04-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f4c7e2d3b9"
down_revision: Union[str, None] = "9a7d3f1c2b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MESSAGE_CRON_ENUM_NAME = "messagecronname"
MESSAGE_CRON_VALUES = ("send_reminder_messages_cron",)


def upgrade() -> None:
    message_cron_enum = sa.Enum(*MESSAGE_CRON_VALUES, name=MESSAGE_CRON_ENUM_NAME)
    message_cron_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "messages",
        sa.Column("cron_name", message_cron_enum, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "cron_name")

    message_cron_enum = sa.Enum(*MESSAGE_CRON_VALUES, name=MESSAGE_CRON_ENUM_NAME)
    message_cron_enum.drop(op.get_bind(), checkfirst=True)
