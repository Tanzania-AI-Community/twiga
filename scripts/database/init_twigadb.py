import asyncio
import json
from pathlib import Path
import re
from sqlalchemy import text
from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import logging
from typing import List, Dict, Any, Optional

# Import all your models
from app.database.models import (
    Class,
    Resource,
    ClassResource,
    Chunk,
    ResourceType,
    Subject,
    GradeLevel,
    ChunkType,
)
from app.config import settings
from app.utils.embedder import get_embeddings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get database URL from environment
database_url = settings.database_url.get_secret_value()
if not database_url:
    raise ValueError("DATABASE_URL environment variable is not set")

# Create async engine
engine = create_async_engine(database_url, echo=False)


def extract_chapter_number(chapter_text: Optional[str]) -> Optional[str]:
    """Extract chapter number from text like "Chapter One (Human Activities)" """
    WORD_TO_NUM = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    if not chapter_text:
        return None

    match = re.search(r"Chapter\s+(\w+)", chapter_text, re.IGNORECASE)
    if not match:
        return None

    word_num = match.group(1).lower()
    return WORD_TO_NUM.get(word_num)


async def load_json_file(file_path: str) -> List[Dict[str, Any]]:
    """Load and parse a JSON file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON file {file_path}: {str(e)}")
        raise


async def process_chunks(
    session: AsyncSession,
    json_data: List[Dict[str, Any]],
    resource_id: int,
    default_type: ChunkType,
    batch_size: int = 30,
):
    """Process chunks in batches to create Chunk models with embeddings"""
    try:
        total_chunks = len(json_data)

        for start_idx in range(0, total_chunks, batch_size):
            end_idx = min(start_idx + batch_size, total_chunks)
            batch_items = json_data[start_idx:end_idx]
            batch_texts = [item["chunk"] for item in batch_items]

            # Get embeddings for the batch
            embeddings = get_embeddings(batch_texts)

            # Create chunks
            for item, embedding in zip(batch_items, embeddings):
                # Get section info
                metadata = item["metadata"]
                top_level_section_title = metadata.get("chapter")
                top_level_section_id = extract_chapter_number(top_level_section_title)

                # Determine content type
                if metadata.get("doc_type") == "Exercise":
                    content_type = ChunkType.exercise
                elif metadata.get("doc_type") == "Content":
                    content_type = ChunkType.text
                else:
                    content_type = default_type

                chunk = Chunk(
                    resource_id=resource_id,
                    content=item["chunk"],
                    content_type=content_type,
                    top_level_section_index=top_level_section_id,
                    top_level_section_title=top_level_section_title,
                    embedding=embedding,
                )
                session.add(chunk)

            await session.commit()
            logger.info(
                f"Processed and saved chunks {start_idx + 1} to {end_idx} of {total_chunks}"
            )

    except Exception as e:
        logger.error(f"Error processing chunks: {str(e)}")
        raise


async def create_dummy_classes():
    """Create dummy classes and link them to resources"""
    try:
        logger.info("Creating dummy classes...")
        async with AsyncSession(engine) as session:
            # Create class for Form 2 Geography
            geography_class = Class(
                subject=Subject.geography,
                grade_level=GradeLevel.os2,
            )

            session.add(geography_class)
            await session.commit()
            await session.refresh(geography_class)

            # Get the resource we created
            stmt = select(Resource).where(
                Resource.subjects.contains([Subject.geography]),
                Resource.grade_levels.contains([GradeLevel.os2]),
            )
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if resource:
                class_resource = ClassResource(
                    class_id=geography_class.id, resource_id=resource.id
                )
                session.add(class_resource)
                await session.commit()

                logger.info("Created class-resource relationship for Form 2 Geography")

            return geography_class

    except Exception as e:
        logger.error(f"Error creating dummy classes: {str(e)}")
        raise


async def create_tables():
    """Create all tables in the database"""
    try:
        logger.info("Creating tables...")

        # Create pgvector extension
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        logger.info("Tables created successfully!")

    except Exception as e:
        logger.error(f"Error creating tables: {str(e)}")
        raise
    finally:
        await engine.dispose()


async def drop_tables():
    """Drop all tables in the database"""
    try:
        logger.info("Dropping tables...")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        logger.info("Tables dropped successfully!")
    except Exception as e:
        logger.error(f"Error dropping tables: {str(e)}")
        raise
    finally:
        await engine.dispose()


async def get_or_create_resource() -> int:
    """Get existing resource or create if it doesn't exist"""
    try:
        logger.info("Checking for existing geography resource...")
        async with AsyncSession(engine) as session:
            # Try to find existing resource
            stmt = select(Resource).where(
                Resource.name
                == "Geography for Secondary Schools Student's Book Form Two"
            )
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if resource:
                logger.info(f"Found existing resource: {resource.name}")
                return resource.id

            # Create new resource if it doesn't exist
            logger.info("Resource not found, creating new one...")
            geography_resource = Resource(
                name="Geography for Secondary Schools Student's Book Form Two",
                type=ResourceType.textbook,
                authors=[
                    "Thaudensia Ndeskoi",
                    "Innocent Rugambuka",
                    "Matilda Sabayi",
                    "Laurence Musatta",
                    "Ernest Simon",
                ],
                grade_levels=[GradeLevel.os2],
                subjects=[Subject.geography],
            )

            session.add(geography_resource)
            await session.commit()
            await session.refresh(geography_resource)
            logger.info(f"Created new resource: {geography_resource.name}")
            return geography_resource.id

    except Exception as e:
        logger.error(f"Error getting or creating resource: {str(e)}")
        raise


async def create_dummy_resources():
    """Load content into existing or new resource"""
    try:
        # Get or create resource
        resource_id = await get_or_create_resource()

        # Process JSON files
        # content_path = Path("assets/sample_resource/tie-geography-f2-content.json")
        exercises_path = Path("assets/sample_resource/tie-geography-f2-exercises.json")

        # Load and process content if no chunks exist
        logger.info("No existing chunks found. Processing content...")
        # content_data = await load_json_file(str(content_path))
        exercises_data = await load_json_file(str(exercises_path))

        # Create a new session for processing chunks
        async with AsyncSession(engine) as session:
            # Process exercise chunks
            logger.info("Processing exercise chunks...")
            await process_chunks(
                session=session,
                json_data=exercises_data,
                resource_id=resource_id,
                default_type=ChunkType.exercise,
            )

        return resource_id

    except Exception as e:
        logger.error(f"Error creating dummy resources: {str(e)}")
        raise


async def create_or_get_class(resource_id: int):
    """Create class if it doesn't exist and link to resource"""
    try:
        logger.info("Checking for existing Form 2 Geography class...")
        async with AsyncSession(engine) as session:
            # Check for existing class
            stmt = select(Class).where(
                Class.subject == Subject.geography,
                Class.grade_level == GradeLevel.os2,
            )
            result = await session.execute(stmt)
            existing_class = result.scalar_one_or_none()

            if existing_class:
                logger.info("Found existing class")
                # Check if class-resource relationship exists
                stmt = select(ClassResource).where(
                    ClassResource.class_id == existing_class.id,
                    ClassResource.resource_id == resource_id,
                )
                result = await session.execute(stmt)
                existing_relation = result.scalar_one_or_none()

                if not existing_relation:
                    logger.info("Creating class-resource relationship...")
                    class_resource = ClassResource(
                        class_id=existing_class.id, resource_id=resource_id
                    )
                    session.add(class_resource)
                    await session.commit()

                return existing_class

            # Create new class if it doesn't exist
            logger.info("Creating new Form 2 Geography class...")
            geography_class = Class(
                subject=Subject.geography,
                grade_level=GradeLevel.os2,
            )

            session.add(geography_class)
            await session.commit()
            await session.refresh(geography_class)

            # Create class-resource relationship
            class_resource = ClassResource(
                class_id=geography_class.id, resource_id=resource_id
            )
            session.add(class_resource)
            await session.commit()

            logger.info("Created new class and class-resource relationship")
            return geography_class

    except Exception as e:
        logger.error(f"Error creating or getting class: {str(e)}")
        raise


if __name__ == "__main__":
    import sys

    async def main():
        try:
            # Parse command line arguments
            args = sys.argv[1:]

            if "--drop" in args:
                logger.info("Dropping existing tables...")
                await drop_tables()
                logger.info("Creating new tables...")
                await create_tables()

            if "--tables" in args:
                logger.info("Creating tables...")
                await create_tables()

            if "--data" in args:
                logger.info("Setting up data...")
                resource_id = await create_dummy_resources()
                await create_or_get_class(resource_id)

            # If no args provided, show usage
            if not args:
                print(
                    """
Usage:
  python setup_db.py [options]

Options:
  --drop     Drop existing tables and create new ones
  --tables   Just create tables if they don't exist
  --data     Add dummy data (can be used with existing tables)

Examples:
  python setup_db.py --drop --data    # Reset everything and add new data
  python setup_db.py --tables         # Just create tables
  python setup_db.py --data           # Just add data to existing tables
"""
                )

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            sys.exit(1)

    asyncio.run(main())
