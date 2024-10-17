from typing import Any, List, Optional
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel
from pydantic import field_validator
from sqlalchemy import Column, DateTime, String, ARRAY, JSON, Integer, text
from urllib.parse import urlparse
from sqlmodel import SQLModel, Field, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import settings
import asyncio
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(max_length=50)
    wa_id: str = Field(max_length=15, unique=True)
    state: str = Field(max_length=15)
    role: str = Field(default="student", max_length=20)
    class_info: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    last_message_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(
        sa_column=DateTime(timezone=True),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=DateTime(timezone=True),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if v not in ["onboarding", "ai_lessons", "active", "settings"]:
            raise ValueError("Invalid state")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ["staff", "teacher", "admin", "student"]:
            raise ValueError("Invalid role")
        return v


class Class(SQLModel, table=True):
    __tablename__ = "classes"
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str = Field(max_length=30)
    grade_level: int = Field()

    @field_validator("grade_level")
    @classmethod
    def validate_grade_level(cls, v: int) -> int:
        if not 1 <= v <= 13:
            raise ValueError("Grade level must be between 1 and 13")
        return v


class TeacherClass(SQLModel, table=True):
    __tablename__ = "teachers_classes"
    id: Optional[int] = Field(default=None, primary_key=True)
    teacher_id: int = Field(foreign_key="user.id")
    class_id: int = Field(foreign_key="class.id")


class Resource(SQLModel, table=True):
    __tablename__ = "resources"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    type: Optional[str] = Field(max_length=30)
    authors: List[str] = Field(sa_column=Column(ARRAY(String(50))))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClassResource(SQLModel, table=True):
    __tablename__ = "classes_resources"
    id: Optional[int] = Field(default=None, primary_key=True)
    class_id: int = Field(foreign_key="class.id")
    resource_id: int = Field(foreign_key="resource.id")


class Section(SQLModel, table=True):
    __tablename__ = "sections"
    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id")
    parent_section_id: Optional[int] = Field(default=None, foreign_key="section.id")
    section_index: Optional[str] = Field(max_length=20)
    section_title: Optional[str] = Field(max_length=100)
    section_type: Optional[str] = Field(max_length=15)
    section_order: int
    page_range: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"
    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id")
    section_id: int = Field(foreign_key="section.id")
    content: Optional[str] = Field(default=None)
    page: Optional[int] = Field(default=None)
    content_type: Optional[str] = Field(max_length=30)
    embedding: Optional[Any] = Field(default=None, sa_column=Column(Vector(1536)))
    top_level_section_index: Optional[str] = Field(max_length=10)
    top_level_section_title: Optional[str] = Field(max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    role: str = Field(max_length=20)
    content: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ["user", "assistant", "system", "context", "tool"]:
            raise ValueError("Invalid role")
        return v


# Define an async function to interact with the database
async def async_main() -> None:
    # Load PostgreSQL database URL from environment variables
    tmpPostgres = urlparse(settings.database_url.get_secret_value())
    async_engine = create_async_engine(
        f"postgresql+asyncpg://{tmpPostgres.username}:{tmpPostgres.password}@{tmpPostgres.hostname}{tmpPostgres.path}?ssl=require",
        # echo=True,
    )
    # async with AsyncSession(async_engine) as session:
    #     await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    async with async_engine.begin() as conn:
        # Create tables based on the models
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        # Add some example data
        user_1 = User(
            name="Victor Oldensand",
            wa_id="123456789",
            state="onboarding",
            role="admin",
            class_info={"Geography": ["8", "9"]},
        )
        # session.add(hero_1)
        session.add(user_1)
        await session.commit()

        # Run a sample query
        statement = select(User).where(User.name == "Victor Oldensand")
        result = await session.execute(statement)
        user = result.first()
        print(user)

    # Dispose of the engine when done
    await async_engine.dispose()


# Run the async_main function with asyncio
if __name__ == "__main__":
    asyncio.run(async_main())
