import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import logging
from typing import List, Dict, Any
import argparse

import yaml

# Import all your models
from scripts.database.utils import check_existing_chunks, extract_chapter_number
from app.database.models import (
    Class,
    Resource,
    ClassResource,
    Chunk,
    Subject,
)
from app.database.enums import ChunkType
from app.database.utils import get_database_url
from app.utils.embedder import get_embeddings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_db(drop_all: bool = False):
    try:
        """Initialize the database with tables."""
        engine = create_async_engine(get_database_url())

        async with engine.begin() as conn:
            if drop_all:
                logger.info("Dropping all existing tables...")
                await conn.run_sync(SQLModel.metadata.drop_all)

            logger.info("Creating tables and pgvector extension...")
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(SQLModel.metadata.create_all)
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise
    finally:
        await engine.dispose()


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
            subject = Subject(name=subject_data["name"])
            session.add(subject)
            await session.flush()  # Get ID without committing
            logger.info(f"Created subject: {subject.name} (ID: {subject.id})")

            # 2. Create the dummy class
            class_data = data["geography_class"]
            assert subject.id
            class_obj = Class(
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
            resource = Resource(
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
            class_resource = ClassResource(
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
                    chunk_type = ChunkType.exercise
                elif metadata.get("doc_type") == "Content":
                    chunk_type = ChunkType.text
                else:
                    logger.warning(
                        f"Unknown document type: {metadata.get('doc_type')}. Skipping chunk."
                    )
                    continue

                chunk = Chunk(
                    resource_id=resource_id,
                    content=item["chunk"],
                    chunk_type=ChunkType(chunk_type),
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


async def inject_vector_data():
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
            stmt = select(Resource).where(Resource.name == resource_name)
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                raise ValueError(
                    "Geography resource not found. Please run --sample-data first."
                )

            resource_id = resource.id

            # Check existing chunks
            processed_chunks = await check_existing_chunks(session, resource_id)

        # Load data files
        chunks_path = (
            Path(__file__).parent.parent / "assets" / "sample_data" / "chunks.json"
        )
        with open(chunks_path, "r") as f:
            chunks_data = json.load(f)

        remaining_chunks = chunks_data[processed_chunks:]

        if not remaining_chunks:
            logger.info("No new chunks to process.")
            return

        logger.info(f"Found {processed_chunks} existing chunks")
        logger.info(f"Processing {len(remaining_chunks)} remaining chunks...")

        # Process remaining chunks
        assert resource_id
        async with AsyncSession(engine) as session:
            await process_chunks(
                session=session,
                json_data=remaining_chunks,
                resource_id=resource_id,
            )

            # Get final count
            final_count = await check_existing_chunks(session, resource_id)
            logger.info(
                f"Vector data injection complete. Total chunks in database: {final_count}"
            )

    except Exception as e:
        logger.error(f"Error injecting vector data: {str(e)}")
        raise
    finally:
        await engine.dispose()


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="Initialize the database for Twiga development."
        )
        parser.add_argument(
            "--drop",
            action="store_true",
            help="Drop the existing tables before creation",
        )
        parser.add_argument(
            "--sample-data", action="store_true", help="Add sample data to the database"
        )
        parser.add_argument(
            "--vector-data",
            action="store_true",
            help="Populate the vector database (chunks table) with the sample data",
        )

        args = parser.parse_args()

        asyncio.run(init_db(drop_all=args.drop))

        if args.sample_data:
            logger.info("Starting data injection...")
            asyncio.run(inject_sample_data())

        if args.vector_data:
            logger.info("Starting vector data injection...")
            asyncio.run(inject_vector_data())

        logger.info("Complete.")
    except Exception as e:
        logger.error(f"Setup failed: {e}")


if __name__ == "__main__":
    main()
