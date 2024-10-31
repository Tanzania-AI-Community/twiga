import json
import asyncio
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging


from app.database.engine import init_db, db_engine
from app.database.models import (
    Chunk,
    ChunkType,
    GradeLevel,
    Resource,
    ResourceType,
    Subject,
)
from scripts.database.db import get_or_create_resource, save_chunks
from app.utils.embedder import get_embeddings

# Configure logging
logger = logging.getLogger(__name__)


class ChunkIngestionError(Exception):
    """Base exception for chunk ingestion operations"""


async def load_json_file(file_path: str) -> List[Dict[str, Any]]:
    """Load and parse a JSON file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON file {file_path}: {str(e)}")
        raise ChunkIngestionError(f"Failed to load JSON file: {str(e)}")


def extract_chapter_number(
    chapter_text: Optional[str],
) -> Optional[str]:
    """
    Extract chapter number from text like "Chapter One (Human Activities)"
    Returns tuple of (chapter_number, full_chapter_title)
    """
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

    # Extract the word between "Chapter" and the first parenthesis or end of string
    match = re.search(r"Chapter\s+(\w+)", chapter_text, re.IGNORECASE)
    if not match:
        return None

    word_num = match.group(1).lower()
    chapter_number = WORD_TO_NUM.get(word_num)

    return chapter_number


def get_section_info(metadata: Dict[str, Any]) -> tuple[str, str]:
    """Extract section and top-level section information from metadata"""
    # Dictionary to convert word numbers to string integers
    top_level_section_title = metadata.get("chapter", None)

    top_level_section_id = extract_chapter_number(top_level_section_title)

    return top_level_section_id, top_level_section_title


async def process_chunks(
    json_data: List[Dict[str, Any]],
    resource_id: int,
    batch_size: int = 30,
) -> List[Chunk]:
    """Process chunks and create Chunk models with embeddings"""
    chunks = []
    texts = [item["chunk"] for item in json_data]
    total_chunks = len(texts)

    # Process embeddings in batches
    for start_idx in range(0, total_chunks, batch_size):
        # Calculate the end index for this batch
        end_idx = min(start_idx + batch_size, total_chunks)
        batch_texts = texts[start_idx:end_idx]
        batch_items = json_data[start_idx:end_idx]

        try:
            # Get embeddings for the batch
            embedding_response = get_embeddings(batch_texts)
            embeddings = embedding_response.data

            # Create Chunk objects for the batch
            for item, embedding in zip(batch_items, embeddings):
                top_level_section_id, top_level_section_title = get_section_info(
                    item["metadata"]
                )
                if item["metadata"].get("doc_type") == "Exercise":
                    content_type = ChunkType.exercise
                elif item["metadata"].get("doc_type") == "Content":
                    content_type = ChunkType.content
                else:
                    content_type = ChunkType.other

                chunk = Chunk(
                    resource_id=resource_id,
                    section_id=None,  # TODO: set this later
                    content=item["chunk"],
                    content_type=content_type,
                    top_level_section_index=top_level_section_id,
                    top_level_section_title=top_level_section_title,
                    embedding=embedding.embedding,
                )
                chunks.append(chunk)

            logger.info(
                f"Processed chunks {start_idx + 1} to {end_idx} of {total_chunks}"
            )

        except Exception as e:
            logger.error(f"Failed to process batch {start_idx} to {end_idx}: {str(e)}")
            raise ChunkIngestionError(f"Failed to process chunks: {str(e)}")

    return chunks


async def main():
    """Main function to process and ingest chunks from JSON files"""
    await init_db(db_engine)

    try:
        # Step 1: Save Resource to the database
        resource = Resource(
            name="Geography for Secondary Schools Student's Book Form Two",
            type=ResourceType.textbook,
            authors=[
                "Thaudensia Ndeskoi",
                "Innocent Rugambuka",
                "Matilda Sabayi",
                "Laurence Musatta",
                "Ernest Simon",
                "Aristarick Lekule",
                "Musa Mwalutanile",
                "Dorothy Makunda",
            ],
            grade_levels=[GradeLevel.os2],
            subjects=[Subject.geography],
        )
        resource = await get_or_create_resource(resource)

        input("Press Enter to load the chunks to the database...")

        # Step 2: Convert JSON to Chunks
        content_path = Path("assets/tie-geography-f2-content.json")
        # exercises_path = Path("assets/tie-geography-f2-exercises.json")

        content_data = await load_json_file(str(content_path))
        # exercises_data = await load_json_file(str(exercises_path))

        logger.info("Processing content chunks...")
        content_chunks = await process_chunks(content_data, resource_id=resource.id)

        # logger.info("Processing exercise chunks...")
        # exercise_chunks = await process_chunks(exercises_data, resource_id=resource.id)

        # Step 3: Upload Chunks to the database
        all_chunks = content_chunks

        logger.info("Saving chunks to database...")
        await save_chunks(all_chunks)

        logger.info("Chunk ingestion completed successfully")

    except Exception as e:
        logger.error(f"Chunk ingestion failed: {str(e)}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Process failed: {str(e)}")
        raise
