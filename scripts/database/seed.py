from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import json
from pathlib import Path
from sqlalchemy import text
from sqlmodel import SQLModel, select
import logging
from typing import List, Dict, Any
import yaml
import argparse
import asyncio
import sys

# Import all your models
import app.database.models as models
from app.database.enums import ChunkType
from app.database.utils import get_database_url


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def reset_db():
    try:
        engine = create_async_engine(get_database_url())
        async with engine.begin() as conn:
            logger.info("Dropping all existing tables...")
            await conn.run_sync(SQLModel.metadata.drop_all)

            # Drop alembic_version table
            logger.info("Dropping alembic_version table...")
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))

            logger.info("Dropping existing enum types...")
            # TODO: Validate that this works
            enum_query = """
                SELECT t.typname FROM pg_type t
                JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typtype = 'e' AND n.nspname = 'public'
            """
            result = await conn.execute(text(enum_query))
            enum_types = result.scalars().all()

            for enum_name in enum_types:
                await conn.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))

            logger.info("Creating pgvector extension...")
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise
    finally:
        await engine.dispose()


def run_migrations():
    """Run alembic migrations"""
    from alembic.config import Config
    from alembic import command

    logger.info("Running migrations...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("Migrations complete")


async def inject_sample_data():
    try:
        """Load sample data into the database."""
        # Load sample data from YAML
        sample_data_path = (
            Path(__file__).parent.parent / "assets" / "sample_data" / "data.yaml"
        )
        with open(sample_data_path) as f:
            data = yaml.safe_load(f)

        engine = create_async_engine(get_database_url())

        async with AsyncSession(engine) as session:
            # 1. Create the dummy subject
            subject_data = data["geography_subject"]
            subject = models.Subject(name=subject_data["name"])
            session.add(subject)
            await session.flush()  # Get ID without committing
            logger.info(f"Created subject: {subject.name} (ID: {subject.id})")

            # 2. Create the dummy class
            class_data = data["geography_class"]
            assert subject.id
            class_obj = models.Class(
                subject_id=subject.id,  # Use the actual subject ID
                grade_level=class_data["grade_level"],
                status=class_data["status"],
            )
            session.add(class_obj)
            await session.flush()
            logger.info(
                f"Created class: Grade level: {class_obj.grade_level}, Subject ID: {class_obj.subject_id}, ID: {class_obj.id})"
            )

            # 3. Create the dummy resource
            resource_data = data["geography_resource"]
            resource = models.Resource(
                name=resource_data["name"],
                type=resource_data["type"],
                authors=resource_data["authors"],
            )
            session.add(resource)
            await session.flush()
            logger.info(f"Created resource: {resource.name} (ID: {resource.id})")

            # 4. Create the dummy class-resource relationship (this connects the textbook to the class)
            assert class_obj.id
            assert resource.id
            class_resource = models.ClassResource(
                class_id=class_obj.id, resource_id=resource.id
            )
            session.add(class_resource)
            await session.flush()
            logger.info(
                f"Created class-resource relationship (ID: {class_resource.id})"
            )

            await session.commit()
    except Exception as e:
        logger.error(f"Error injecting sample data: {str(e)}")
        raise
    finally:
        await engine.dispose()


async def process_chunks(
    session: AsyncSession,
    json_data: List[Dict[str, Any]],
    resource_id: int,
    batch_size: int = 30,
):
    """Process pre-enhanced chunks to create Chunk models"""
    try:
        total_chunks = len(json_data)
        for start_idx in range(0, total_chunks, batch_size):
            end_idx = min(start_idx + batch_size, total_chunks)
            batch_items = json_data[start_idx:end_idx]

            for item in batch_items:
                metadata = item["metadata"]
                chunk = models.Chunk(
                    resource_id=resource_id,
                    content=item["chunk"],
                    chunk_type=ChunkType(metadata["chunk_type"]),
                    top_level_section_index=metadata["chapter_number"],
                    top_level_section_title=metadata["chapter"],
                    embedding=item["embedding"],
                )
                session.add(chunk)

            await session.commit()
            logger.info(
                f"Processed and saved chunks {start_idx + 1} to {end_idx} of {total_chunks}"
            )

    except Exception as e:
        logger.error(f"Error processing chunks: {str(e)}")
        raise


async def inject_vector_data(file: str):
    """Inject vector data into the database with existence checking and continuation."""
    try:
        engine = create_async_engine(get_database_url())

        # Load sample data from YAML to get resource name
        sample_data_path = (
            Path(__file__).parent.parent / "assets" / "sample_data" / "data.yaml"
        )
        with open(sample_data_path) as f:
            yaml_data = yaml.safe_load(f)
            resource_name = yaml_data["geography_resource"]["name"]

        async with AsyncSession(engine) as session:
            # Get resource ID using name from YAML
            stmt = select(models.Resource).where(models.Resource.name == resource_name)
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                raise ValueError(
                    "Geography resource not found. Please run --sample-data first."
                )

            resource_id = resource.id
            assert resource_id

        # Load enhanced chunks data
        chunks_path = (
            Path(__file__).parent.parent / "assets" / "sample_data" / f"{file}"
        )
        with open(chunks_path, "r") as f:
            chunks_data = json.load(f)

        # Process remaining chunks
        async with AsyncSession(engine) as session:
            await process_chunks(
                session=session,
                json_data=chunks_data,
                resource_id=resource_id,
            )

            # Get final count
            logger.info(
                f"Vector data injection complete. Total chunks in database: {len(chunks_data)}"
            )

    except Exception as e:
        logger.error(f"Error injecting vector data: {str(e)}")
        raise
    finally:
        await engine.dispose()


async def main():
    """Initialize and setup the Twiga development database."""
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Initialize and setup the Twiga development database."
    )
    parser.add_argument(
        "--create", action="store_true", help="Reset and run alembic migrations"
    )
    parser.add_argument("--sample-data", action="store_true", help="Add sample data")
    parser.add_argument(
        "--vector-data",
        type=str,
        help="Vector database chunks file (chunks_OPENAI.json or chunks_BAAI.json)",
    )

    # Parse arguments
    args = parser.parse_args()

    try:

        if args.create:
            logger.info("Starting database setup...")
            await reset_db()
            run_migrations()

        if args.sample_data:
            logger.info("Starting sample data injection...")
            await inject_sample_data()

        if args.vector_data:
            logger.info("Starting vector data injection...")
            await inject_vector_data(args.vector_data)

        logger.info("Database setup complete")
    except Exception as e:
        print(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
