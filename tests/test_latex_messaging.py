import asyncio
from app.services.messaging_service import MessagingService
from app.database.models import Message, User
from app.database.enums import MessageRole
from unittest.mock import AsyncMock, patch


async def main() -> None:
    """
    Test if latex in llm answers are detected correctly and formated and sent to user
    """
    your_number = "xxxx"  # Replace with your WhatsApp number (no + sign)
    
    # Create messaging service instance
    messaging_service = MessagingService()
    # Create mock user and message
    mock_user = User(
        id=1,
        wa_id=your_number,
        name="Test User"
    )
    mock_user_message = Message(
        id=1,
        user_id=1,
        role=MessageRole.user,
        content="Hello, can you solve this equation?"
    )  
    # Mock LLM response with mixed text and LaTeX formulas
    mock_llm_response = Message(
        id=2,
        user_id=1,
        role=MessageRole.assistant,
        content="Here's the solution: The quadratic formula is $$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$ and for simple cases like $x^2 = 4$, we get $x = \\pm 2$. Hope this helps!"
    )
    
    print(f"Testing LaTeX messaging to WhatsApp number: {your_number}")
    print(f"Mock LLM response: {mock_llm_response.content}")
    print("This will send real WhatsApp messages to your phone!")
    
    try:
        # Mock only the external dependencies, not the messaging service itself
        with (
            patch("app.services.messaging_service.llm_client.generate_response", new_callable=AsyncMock) as mock_llm_generate,
            patch("app.services.messaging_service.db.create_new_messages", new_callable=AsyncMock) as mock_db_create,
        ):
            # Configure mocks
            mock_llm_generate.return_value = [mock_llm_response]
            
            # Call the real messaging service
            response = await messaging_service.handle_chat_message(mock_user, mock_user_message)
            
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()


async def test_simple_latex() -> None:
    """
    Test with a simpler LaTeX formula in llm response
    """
    your_number = "xxxx"  # Replace with your WhatsApp number (no + sign)
    
    messaging_service = MessagingService()
    
    mock_user = User(
        id=1,
        wa_id=your_number,
        name="Test User"
    )
    
    mock_user_message = Message(
        id=1,
        user_id=1,
        role=MessageRole.user,
        content="Show me Einstein's equation"
    )
    
    # Simple LaTeX response
    mock_llm_response = Message(
        id=2,
        user_id=1,
        role=MessageRole.assistant,
        content="Einstein's famous equation is $E = mc^2$ where E is energy, m is mass, and c is the speed of light."
    )
    
    print(f"\nTesting simple LaTeX to WhatsApp number: {your_number}")
    print(f"Mock LLM response: {mock_llm_response.content}")
    
    try:
        with (
            patch("app.services.messaging_service.llm_client.generate_response", new_callable=AsyncMock) as mock_llm_generate,
            patch("app.services.messaging_service.db.create_new_messages", new_callable=AsyncMock) as mock_db_create,
        ):
            mock_llm_generate.return_value = [mock_llm_response]
            
            response = await messaging_service.handle_chat_message(mock_user, mock_user_message)
            
            print(f"Response status: {response.status_code}")
            print("You should receive:")
            print("1. Text: 'Einstein's famous equation is'")
            print("2. Image: LaTeX formula 'E = mc^2'")
            print("3. Text: 'where E is energy, m is mass, and c is the speed of light.'")
            
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()


async def test_no_latex() -> None:
    """
    Test with no LaTeX formulas (normal text message).
    """
    your_number = "xxx"  # Replace with your WhatsApp number (no + sign)
    
    messaging_service = MessagingService()
    
    mock_user = User(
        id=1,
        wa_id=your_number,
        name="Test User"
    )
    
    mock_user_message = Message(
        id=1,
        user_id=1,
        role=MessageRole.user,
        content="Hello, how are you?"
    )
    
    # Normal text response
    mock_llm_response = Message(
        id=2,
        user_id=1,
        role=MessageRole.assistant,
        content="I'm doing great! How can I help you with your studies today?"
    )
    
    print(f"\nTesting normal text message to WhatsApp number: {your_number}")
    print(f"Mock LLM response: {mock_llm_response.content}")
    
    try:
        with (
            patch("app.services.messaging_service.llm_client.generate_response", new_callable=AsyncMock) as mock_llm_generate,
            patch("app.services.messaging_service.db.create_new_messages", new_callable=AsyncMock) as mock_db_create,
        ):
            mock_llm_generate.return_value = [mock_llm_response]
            
            response = await messaging_service.handle_chat_message(mock_user, mock_user_message)
            
            print(f"Response status: {response.status_code}")
            print("You should receive:")
            print("1. Text: 'I'm doing great! How can I help you with your studies today?'")
            
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=== LaTeX Messaging Test ===")
    print("Make sure to replace 'xxx' with your WhatsApp number!")
    print("This will send REAL messages to your phone.\n")
    
    # Run all tests
    asyncio.run(main())
    #asyncio.run(test_simple_latex())
    #asyncio.run(test_no_latex())
    
    print("\n=== Test Complete ===")
    print("Check your WhatsApp messages!")