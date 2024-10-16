import asyncio
from typing import Optional
from urllib.parse import urlparse
from sqlmodel import SQLModel, Field, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import settings


# Load PostgreSQL database URL from environment variables
tmpPostgres = urlparse(settings.database_url.get_secret_value())


# Define a basic SQLModel model
class Hero(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: Optional[int] = None


# Define an async function to interact with the database
async def async_main() -> None:
    async_engine = create_async_engine(
        f"postgresql+asyncpg://{tmpPostgres.username}:{tmpPostgres.password}@{tmpPostgres.hostname}{tmpPostgres.path}?ssl=require",
        # echo=True,
    )
    async with async_engine.begin() as conn:
        # Create tables based on the models
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        # Add some example data
        hero_1 = Hero(name="Deadpond", secret_name="Dive Wilson")
        session.add(hero_1)
        await session.commit()

        # Run a sample query
        statement = select(Hero).where(Hero.name == "Deadpond")
        result = await session.execute(statement)
        hero = result.first()
        print(hero)

    # Dispose of the engine when done
    await async_engine.dispose()


# Run the async_main function with asyncio
if __name__ == "__main__":
    asyncio.run(async_main())
