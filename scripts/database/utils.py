import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
import logging

from app.database.models import Chunk

logger = logging.getLogger(__name__)


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


async def check_existing_chunks(
    session: AsyncSession, resource_id: Optional[int] = None
) -> int:
    """Check how many chunks exist in the database."""
    try:
        stmt = select(Chunk)
        if resource_id:
            stmt = stmt.where(Chunk.resource_id == resource_id)
        result = await session.execute(stmt)
        return len(result.scalars().all())
    except Exception as e:
        logger.error(f"Error checking existing chunks: {str(e)}")
        raise
