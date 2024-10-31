from typing import List, Dict, Any
import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from app.database.models import Chunk, Resource
from app.database.engine import db_engine

logger = logging.getLogger(__name__)

# Create async session maker
AsyncSessionLocal = async_sessionmaker(
    bind=db_engine, class_=AsyncSession, expire_on_commit=False
)


async def save_chunks(chunks: List[Chunk]) -> None:
    """Save chunks to the database"""
    async with AsyncSessionLocal() as session:
        try:
            # Add all chunks to the session
            session.add_all(chunks)
            await session.commit()
            logger.info(f"Successfully saved {len(chunks)} chunks to the database")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to save chunks to database: {str(e)}")


async def get_or_create_resource(resource: Resource) -> Resource:
    """Get existing resource or create new one if it doesn't exist"""
    async with AsyncSessionLocal() as session:
        try:
            # First try to get existing resource by name
            statement = select(Resource).where(Resource.name == resource.name)
            result = await session.execute(statement)
            existing_resource = result.scalar_one_or_none()

            if existing_resource:
                logger.info(f"Found existing resource {existing_resource.id}")
                return existing_resource

            # Create new resource if it doesn't exist
            session.add(resource)
            await session.commit()
            await session.refresh(resource)
            logger.info(f"Successfully created new resource {resource.id}")
            return resource

        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to get or create resource: {str(e)}")
            raise
