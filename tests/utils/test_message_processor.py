from app.database.enums import MessageRole
from app.database.models import Message
from app.utils.message_processor import MessageProcessor


def test_remove_drops_only_the_given_objects() -> None:
    """Identical-looking messages are separate turns; only the given one goes."""
    processor = MessageProcessor(user_id=1)
    first, second = (
        Message(user_id=1, role=MessageRole.user, content="ok") for _ in range(2)
    )
    processor.add_message(first)
    processor.add_message(second)

    processor.remove([first])

    pending = processor.get_pending_messages()
    assert len(pending) == 1
    assert pending[0] is second
