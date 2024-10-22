# This is a revised version of the database connection with standard SQLModel and Alembic, following the Neon tutorial and using sync connections
from sqlmodel import SQLModel, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from urllib.parse import urlparse

from app.config import settings

# NOTE: this is used if we don't use alembic for migrations

# Load PostgreSQL database URL from environment variables
database_uri = urlparse(settings.database_url.get_secret_value())
postgres_url = (
    f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require",
)

engine = create_engine(postgres_url, echo=True)

SQLModel.metadata.create_all(engine)
