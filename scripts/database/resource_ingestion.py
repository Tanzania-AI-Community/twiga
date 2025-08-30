from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import json
from pathlib import Path
from sqlmodel import select
import logging
from pydantic import BaseModel
import argparse
import asyncio
import sys

# Import all your models
import app.database.models as models
import app.database.db as db
from app.database.enums import ChunkType
from app.database.utils import get_database_url


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ResourceConfig(BaseModel):
    name: str
    type: str
    authors: list[str]


class ClassConfig(BaseModel):
    grade_level: str
    name: str
    status: str


class SubjectConfig(BaseModel):
    name: str


class Chunk(BaseModel):
    content: str
    embedding: list[float]
    page_number: int
    chapter_number: int


class Chapter(BaseModel):
    name: str
    number: int
    start_page: int


class TableOfContents(BaseModel):
    chapters: list[Chapter]


class ParsedBook(BaseModel):
    resource: ResourceConfig
    class_: ClassConfig
    subject: SubjectConfig
    table_of_contents: TableOfContents
    chunks: list[Chunk]


def get_parsed_book(file_name: str) -> ParsedBook:
    file_path = Path(__file__).parent.parent / "assets" / "books" / f"{file_name}"

    with open(file_path, "r", encoding="utf-8") as f:
        book_content_raw = json.load(f)

    parsed_book = ParsedBook(
        resource=ResourceConfig(
            name=book_content_raw["resource"]["name"],
            type=book_content_raw["resource"]["type"],
            authors=book_content_raw["resource"]["authors"],
        ),
        class_=ClassConfig(
            grade_level=book_content_raw["class"]["grade_level"],
            name=book_content_raw["class"]["name"],
            status=book_content_raw["class"]["status"],
        ),
        subject=SubjectConfig(
            name=book_content_raw["subject"]["name"],
        ),
        table_of_contents=TableOfContents(
            chapters=[
                Chapter(
                    name=chapter["name"],
                    number=chapter["number"],
                    start_page=chapter["start_page"],
                )
                for chapter in book_content_raw["table_of_contents"]["chapters"]
            ]
        ),
        chunks=[
            Chunk(
                content=chunk_raw["content"],
                embedding=chunk_raw["embedding"],
                page_number=chunk_raw["page_number"],
                chapter_number=chunk_raw["chapter_number"],
            )
            for chunk_raw in book_content_raw["chunks"]
        ],
    )

    return parsed_book


async def inject_subject_class_and_resource_data(parsed_book: ParsedBook):
    try:
        engine = create_async_engine(get_database_url())

        async with AsyncSession(engine) as session:
            # 1. Create the dummy subject

            subject = await db.read_subject_by_name(
                subject_name=parsed_book.subject.name
            )

            if not subject:
                subject = models.Subject(name=parsed_book.subject.name)
                session.add(subject)
                await session.flush()  # Get ID without committing
                logger.info(f"Created subject: {subject.name} (ID: {subject.id})")

            # 2. Create the dummy class
            assert subject.id

            class_obj = await db.read_class_by_subject_id_grade_level_and_status(
                subject_id=subject.id,
                grade_level=parsed_book.class_.grade_level,
                status=parsed_book.class_.status,
            )

            if not class_obj:
                class_obj = models.Class(
                    subject_id=subject.id,  # Use the actual subject ID
                    grade_level=parsed_book.class_.grade_level,
                    status=parsed_book.class_.status,
                )
                session.add(class_obj)
                await session.flush()
                logger.info(
                    f"Created class: Grade level: {class_obj.grade_level}, Subject ID: {class_obj.subject_id}, ID: {class_obj.id})"
                )

            # 3. Create the dummy resource

            resource = await db.read_resource_by_name(
                resource_name=parsed_book.resource.name
            )

            if not resource:
                resource = models.Resource(
                    name=parsed_book.resource.name,
                    type=parsed_book.resource.type,
                    authors=parsed_book.resource.authors,
                )
                session.add(resource)
                await session.flush()
                logger.info(f"Created resource: {resource.name} (ID: {resource.id})")

            # 4. Create the dummy class-resource relationship (this connects the textbook to the class)
            assert class_obj.id
            assert resource.id

            does_class_resource_rel_exist = await db.does_class_resource_rel_exist(
                class_id=class_obj.id, resource_id=resource.id
            )
            if not does_class_resource_rel_exist:
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
        logger.error(f"Error injecting data: {str(e)}")
        raise
    finally:
        await engine.dispose()


async def process_chunks(
    session: AsyncSession,
    chunks: list[Chunk],
    table_of_contents: TableOfContents,
    resource_id: int,
    batch_size: int = 30,
) -> None:
    """Process pre-enhanced chunks to create Chunk models"""
    try:
        total_chunks = len(chunks)
        chapter_number_to_name_mapper = {
            chapter.number: chapter.name for chapter in table_of_contents.chapters
        }

        for start_idx in range(0, total_chunks, batch_size):
            end_idx = min(start_idx + batch_size, total_chunks)
            batch_items = chunks[start_idx:end_idx]

            for item in batch_items:
                chunk = models.Chunk(
                    resource_id=resource_id,
                    content=item.content,
                    chunk_type=ChunkType.text,  # TODO: include in json
                    top_level_section_index=str(item.chapter_number),
                    top_level_section_title=chapter_number_to_name_mapper.get(
                        item.chapter_number
                    ),
                    embedding=item.embedding,
                )
                session.add(chunk)

            await session.commit()
            logger.info(
                f"Processed and saved chunks {start_idx + 1} to {end_idx} of {total_chunks}"
            )

    except Exception as e:
        logger.error(f"Error processing chunks: {str(e)}")
        raise


async def inject_vector_data(parsed_book: ParsedBook):
    """Inject vector data into the database with existence checking and continuation."""
    try:
        engine = create_async_engine(get_database_url())

        resource_name = parsed_book.resource.name
        async with AsyncSession(engine) as session:
            stmt = select(models.Resource).where(models.Resource.name == resource_name)
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                raise ValueError(f"{resource_name} resource not found.")

            resource_id = resource.id
            assert resource_id

        async with AsyncSession(engine) as session:
            await process_chunks(
                session=session,
                chunks=parsed_book.chunks,
                resource_id=resource_id,
                table_of_contents=parsed_book.table_of_contents,
            )

            logger.info(
                f"Vector data injection complete. Total chunks in database: {len(parsed_book.chunks)}"
            )

    except Exception as e:
        logger.error(f"Error injecting vector data: {str(e)}")
        raise
    finally:
        await engine.dispose()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parsed_book_name",
        type=str,
        required=True,
        help="Path to the input book to be ingested into the DB.",
    )
    args = parser.parse_args()

    try:
        parsed_book = get_parsed_book(file_name=args.parsed_book_name)

        logger.info("Starting book data injection...")
        await inject_subject_class_and_resource_data(parsed_book)

        logger.info("Starting book chunks ingestion into vector DB...")
        await inject_vector_data(parsed_book)

    except Exception as e:
        print(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
