"""add media columns to messages

Revision ID: eac51290b432
Revises: 63ac8f1e9b4c
Create Date: 2026-01-12 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "eac51290b432"  
down_revision: Union[str, None] = "63ac8f1e9b4c" 
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('messages', sa.Column('media_id', sa.String(), nullable=True))
    op.add_column('messages', sa.Column('mime_type', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('messages', 'mime_type')
    op.drop_column('messages', 'media_id')