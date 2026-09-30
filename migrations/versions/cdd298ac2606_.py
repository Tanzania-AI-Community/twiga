"""

Revision ID: cdd298ac2606
Revises: a1f4c7e2d3b9
Create Date: 2026-06-03 17:25:20.071735

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'cdd298ac2606'
down_revision: Union[str, None] = 'a1f4c7e2d3b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chunks', sa.Column('chapter_number', sa.Integer(), nullable=True))
    op.add_column('chunks', sa.Column('subchapter_number', sa.Integer(), nullable=True))
    op.add_column('resources', sa.Column('table_of_contents', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('resources', 'table_of_contents')
    op.drop_column('chunks', 'subchapter_number')
    op.drop_column('chunks', 'chapter_number')
