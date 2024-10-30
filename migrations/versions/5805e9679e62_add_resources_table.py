"""add resources table

Revision ID: 5805e9679e62
Revises: c04271064481
Create Date: 2024-10-29 20:18:59.702826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '5805e9679e62'
down_revision: Union[str, None] = 'c04271064481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('resources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=30), nullable=True),
    sa.Column('authors', sa.ARRAY(sa.String(length=50)), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('resources')
    # ### end Alembic commands ###
