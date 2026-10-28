"""Add durable conversation summary batches and per-user rollup.

Revision ID: b7e2c9a4f610
Revises: a1f4c7e2d3b9
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e2c9a4f610"
down_revision = "a1f4c7e2d3b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_summary_state",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "older_history_summary", sa.Text(), server_default="", nullable=False
        ),
        sa.Column("token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "compacted_through_batch", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "token_count >= 0 AND token_count <= 25000", name="ck_summary_state_tokens"
        ),
        sa.CheckConstraint(
            "compacted_through_batch >= 0", name="ck_summary_state_boundary"
        ),
        sa.CheckConstraint("version >= 0", name="ck_summary_state_version"),
    )
    op.create_table(
        "conversation_summary_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("first_message_id", sa.Integer(), nullable=False),
        sa.Column("last_message_id", sa.Integer(), nullable=False),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("covered_message_ids", sa.JSON(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "is_compacted", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "sequence_number", name="uq_summary_batch_sequence"
        ),
        sa.CheckConstraint("sequence_number > 0", name="ck_summary_batch_sequence"),
        sa.CheckConstraint("token_count >= 0", name="ck_summary_batch_tokens"),
        sa.CheckConstraint(
            "first_message_id > 0 AND last_message_id > 0",
            name="ck_summary_batch_endpoints",
        ),
        sa.CheckConstraint(
            "first_message_at <= last_message_at", name="ck_summary_batch_times"
        ),
        sa.CheckConstraint(
            "json_array_length(covered_message_ids) > 0",
            name="ck_summary_batch_coverage",
        ),
        sa.CheckConstraint(
            "NOT is_compacted OR (summary_text = '' AND token_count = 0)",
            name="ck_summary_batch_archived",
        ),
    )
    op.create_index(
        "ix_summary_batch_active_order",
        "conversation_summary_batches",
        ["user_id", "is_compacted", "sequence_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_summary_batch_active_order", table_name="conversation_summary_batches"
    )
    op.drop_table("conversation_summary_batches")
    op.drop_table("conversation_summary_state")
