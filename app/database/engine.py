import asyncio
from urllib.parse import urlparse
from sqlmodel import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import settings
from app.database.models import *

# Load PostgreSQL database URL from environment variables
database_uri = urlparse(settings.database_url.get_secret_value())
postgres_url = f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require"
# Initiate the async engine to be used in the rest of the app
engine = create_async_engine(
    postgres_url,
    echo=True,  # TODO: Set this to eg. settings.debug to only print when the debugging flag is set
)
# TODO: Make sure to dispose of the engine when the app is done using it (eg. with FastAPI lifetime handlers)

# async def async_main() -> None:
#     async_engine = create_async_engine(
#         postgres_url,
#         echo=True,
#     )

#     async with async_engine.connect() as conn:
#         result = await conn.execute(text("select 'hello world"))
#         print(result.fetchall())

#     await async_engine.dispose()


# asyncio.run(async_main())
