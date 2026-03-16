"""Add feedback invites and responses

Revision ID: 9f3c1a2b7d10
Revises: 40ef9772ad6c
Create Date: 2026-03-06 11:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "9f3c1a2b7d10"
down_revision: Union[str, None] = "40ef9772ad6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


feedback_invite_status_enum = sa.Enum(
    "pending", "sent", "expired", "responded", "failed", name="feedbackinvitestatus"
)
feedback_response_type_enum = sa.Enum(
    "positive", "neutral", "negative", "opt_out", name="feedbackresponsetype"
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "feedback_opted_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("feedback_opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )

    feedback_invite_status_enum.create(op.get_bind(), checkfirst=True)
    feedback_response_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "feedback_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", feedback_invite_status_enum, nullable=False),
        sa.Column(
            "last_message_at_snapshot", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),  # type: ignore
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "last_message_at_snapshot",
            name="unique_feedback_invite_for_idle_window",
        ),
    )
    op.create_index(
        op.f("ix_feedback_invites_user_id"),
        "feedback_invites",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_invites_status"),
        "feedback_invites",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_invites_last_message_at_snapshot"),
        "feedback_invites",
        ["last_message_at_snapshot"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_invites_scheduled_at"),
        "feedback_invites",
        ["scheduled_at"],
        unique=False,
    )

    op.create_table(
        "feedback_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invite_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("response_type", feedback_response_type_enum, nullable=False),
        sa.Column(
            "selected_option_id",
            sqlmodel.sql.sqltypes.AutoString(length=100),  # type: ignore
            nullable=False,
        ),
        sa.Column(
            "selected_option_title",
            sqlmodel.sql.sqltypes.AutoString(length=200),  # type: ignore
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invite_id"], ["feedback_invites.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_id"),
    )
    op.create_index(
        op.f("ix_feedback_responses_invite_id"),
        "feedback_responses",
        ["invite_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_feedback_responses_user_id"),
        "feedback_responses",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_responses_response_type"),
        "feedback_responses",
        ["response_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_feedback_responses_response_type"), table_name="feedback_responses"
    )
    op.drop_index(
        op.f("ix_feedback_responses_user_id"), table_name="feedback_responses"
    )
    op.drop_index(
        op.f("ix_feedback_responses_invite_id"), table_name="feedback_responses"
    )
    op.drop_table("feedback_responses")

    op.drop_index(
        op.f("ix_feedback_invites_scheduled_at"), table_name="feedback_invites"
    )
    op.drop_index(
        op.f("ix_feedback_invites_last_message_at_snapshot"),
        table_name="feedback_invites",
    )
    op.drop_index(op.f("ix_feedback_invites_status"), table_name="feedback_invites")
    op.drop_index(op.f("ix_feedback_invites_user_id"), table_name="feedback_invites")
    op.drop_table("feedback_invites")

    feedback_response_type_enum.drop(op.get_bind(), checkfirst=True)
    feedback_invite_status_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_column("users", "feedback_opted_out_at")
    op.drop_column("users", "feedback_opted_out")
