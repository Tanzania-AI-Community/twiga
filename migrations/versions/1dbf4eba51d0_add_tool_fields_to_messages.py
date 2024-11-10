"""add tool fields to messages

Revision ID: 1dbf4eba51d0
Revises: d6b90f11242c
Create Date: 2024-11-09 10:38:33.201200

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "1dbf4eba51d0"
down_revision: Union[str, None] = "d6b90f11242c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("messages", sa.Column("tool_calls", sa.JSON(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("tool_call_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column(
            "tool_name", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
    )
    op.alter_column("messages", "content", existing_type=sa.VARCHAR(), nullable=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("messages", "content", existing_type=sa.VARCHAR(), nullable=False)
    op.drop_column("messages", "tool_name")
    op.drop_column("messages", "tool_call_id")
    op.drop_column("messages", "tool_calls")
    # ### end Alembic commands ###
