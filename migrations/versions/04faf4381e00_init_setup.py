"""init-setup

Revision ID: 04faf4381e00
Revises: 
Create Date: 2024-10-22 23:52:07.042951

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "04faf4381e00"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "subject", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False
        ),
        sa.Column(
            "grade_level", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject", "grade_level", name="unique_classes"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column("wa_id", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("class_info", sa.JSON(), nullable=True),
        sa.Column(
            "school_name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True
        ),
        sa.Column("birthday", sa.Date(), nullable=True),
        sa.Column("region", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_wa_id"), "users", ["wa_id"], unique=True)
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messages_created_at"), "messages", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_messages_user_id"), "messages", ["user_id"], unique=False)
    op.create_table(
        "teachers_classes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teacher_id", "class_id", name="unique_teacher_class"),
    )
    op.create_index(
        op.f("ix_teachers_classes_class_id"),
        "teachers_classes",
        ["class_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_teachers_classes_teacher_id"),
        "teachers_classes",
        ["teacher_id"],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_teachers_classes_teacher_id"), table_name="teachers_classes")
    op.drop_index(op.f("ix_teachers_classes_class_id"), table_name="teachers_classes")
    op.drop_table("teachers_classes")
    op.drop_index(op.f("ix_messages_user_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_created_at"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_users_wa_id"), table_name="users")
    op.drop_table("users")
    op.drop_table("classes")
    # ### end Alembic commands ###
