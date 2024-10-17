import asyncio
from typing import Optional
from urllib.parse import urlparse
from sqlmodel import SQLModel, Field, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import settings
from app.database.models import *

# Load PostgreSQL database URL from environment variables
database_uri = urlparse(settings.database_url.get_secret_value())
postgres_url = (
    f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require",
)

async_engine = create_async_engine(
    postgres_url,
    echo=True,
    future=True,
)


# Define an async function to interact with the database
async def create_db_and_tables() -> None:
    async with async_engine.begin() as conn:
        # Create tables based on the models
        await conn.run_sync(SQLModel.metadata.create_all)

    # Dispose of the engine when done
    await async_engine.dispose()


async def add_user() -> User:
    async with AsyncSession(async_engine) as session:
        # Add some example data
        user_1 = User(
            name="Victor Oldensand",
            wa_id="123456789",
            state="onboarding",
            role="admin",
            class_info={"Geography": ["8", "9"]},
        )
        session.add(user_1)
        session.commit()
        # refresh the user_1 data with the updated data from the database
        session.refresh(user_1)

    return user_1


async def get_user() -> None:
    async with AsyncSession(async_engine) as session:
        # Run a sample query
        statement = select(User).where(User.name == "Victor Oldensand")
        result = await session.execute(
            statement
        )  # We use SQLAlchemy's execute method instead of exec from SQLModel (since we use the AsyncSession)
        user = result.first()
        print(user)
        session.close()


async def update_user(
    user_id: int, name: str
) -> User:  # Currently just updating the name
    async with AsyncSession(async_engine) as session:
        statement = select(User).where(User.id == user_id)
        results = session.execute(statement)
        user = results.one()

        user.name = name
        session.add(user)
        session.commit()
        session.refresh(user)

    return user


async def delete_user(user_id: int) -> None:
    with AsyncSession(async_engine) as session:
        statement = select(User).where(User.id == user_id)
        results = session.exec(statement)
        user = results.one()
        session.delete(user)
        session.commit()


# Run the async_main function with asyncio
if __name__ == "__main__":
    asyncio.run(create_db_and_tables())
