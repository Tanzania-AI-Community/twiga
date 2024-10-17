"""Changed table names to snake_case and plural

Revision ID: 7efc09e425a2
Revises: 
Create Date: 2024-10-17 17:37:57.385626

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7efc09e425a2"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Rename tables
    op.rename_table("user", "users")
    op.rename_table("class", "classes")
    op.rename_table("teacherclass", "teachers_classes")
    op.rename_table("resource", "resources")
    op.rename_table("classresource", "classes_resources")
    op.rename_table("section", "sections")
    op.rename_table("chunk", "chunks")
    op.rename_table("message", "messages")

    # Update foreign key constraints
    op.execute(
        "ALTER TABLE teachers_classes RENAME CONSTRAINT teacherclass_teacher_id_fkey TO teachers_classes_teacher_id_fkey"
    )
    op.execute(
        "ALTER TABLE teachers_classes RENAME CONSTRAINT teacherclass_class_id_fkey TO teachers_classes_class_id_fkey"
    )
    op.execute(
        "ALTER TABLE classes_resources RENAME CONSTRAINT classresource_class_id_fkey TO classes_resources_class_id_fkey"
    )
    op.execute(
        "ALTER TABLE classes_resources RENAME CONSTRAINT classresource_resource_id_fkey TO classes_resources_resource_id_fkey"
    )
    op.execute(
        "ALTER TABLE sections RENAME CONSTRAINT section_resource_id_fkey TO sections_resource_id_fkey"
    )
    op.execute(
        "ALTER TABLE sections RENAME CONSTRAINT section_parent_section_id_fkey TO sections_parent_section_id_fkey"
    )
    op.execute(
        "ALTER TABLE chunks RENAME CONSTRAINT chunk_resource_id_fkey TO chunks_resource_id_fkey"
    )
    op.execute(
        "ALTER TABLE chunks RENAME CONSTRAINT chunk_section_id_fkey TO chunks_section_id_fkey"
    )
    op.execute(
        "ALTER TABLE messages RENAME CONSTRAINT message_user_id_fkey TO messages_user_id_fkey"
    )


def downgrade():
    # Rename tables back
    op.rename_table("users", "user")
    op.rename_table("classes", "class")
    op.rename_table("teachers_classes", "teacherclass")
    op.rename_table("resources", "resource")
    op.rename_table("classes_resources", "classresource")
    op.rename_table("sections", "section")
    op.rename_table("chunks", "chunk")
    op.rename_table("messages", "message")

    # Revert foreign key constraint names
    op.execute(
        "ALTER TABLE teacherclass RENAME CONSTRAINT teachers_classes_teacher_id_fkey TO teacherclass_teacher_id_fkey"
    )
    op.execute(
        "ALTER TABLE teacherclass RENAME CONSTRAINT teachers_classes_class_id_fkey TO teacherclass_class_id_fkey"
    )
    op.execute(
        "ALTER TABLE classresource RENAME CONSTRAINT classes_resources_class_id_fkey TO classresource_class_id_fkey"
    )
    op.execute(
        "ALTER TABLE classresource RENAME CONSTRAINT classes_resources_resource_id_fkey TO classresource_resource_id_fkey"
    )
    op.execute(
        "ALTER TABLE section RENAME CONSTRAINT sections_resource_id_fkey TO section_resource_id_fkey"
    )
    op.execute(
        "ALTER TABLE section RENAME CONSTRAINT sections_parent_section_id_fkey TO section_parent_section_id_fkey"
    )
    op.execute(
        "ALTER TABLE chunk RENAME CONSTRAINT chunks_resource_id_fkey TO chunk_resource_id_fkey"
    )
    op.execute(
        "ALTER TABLE chunk RENAME CONSTRAINT chunks_section_id_fkey TO chunk_section_id_fkey"
    )
    op.execute(
        "ALTER TABLE message RENAME CONSTRAINT messages_user_id_fkey TO message_user_id_fkey"
    )
