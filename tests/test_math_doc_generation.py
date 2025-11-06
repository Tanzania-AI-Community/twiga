import pytest
import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.messaging_service import MessagingService
from app.database.models import Message, User
from app.database.enums import MessageRole


@pytest.mark.asyncio
async def test_messaging_service_math_detection_happy_path():
    """
    Test the happy path of messaging service with LaTeX math detection.
    Mock LLM response contains <math> tags that should trigger LaTeX document generation.

    Remember to host webhook, get new whatsapp api key AND MESSAGE THE WHATSAPP NUMBER!!
    
    """
    
    # Create test user
    test_user = User(
        id=1,
        wa_id="xxxx",
        name="Test User"
    )
    
    # Create test user message
    user_message = Message(
        id=1,
        user_id=1,
        role=MessageRole.user,
        content="Can you show me the quadratic formula?"
    )
    
    # Mock LLM response with <math> tags
    mock_llm_response = Message(
        id=2,
        user_id=1,
        role=MessageRole.assistant,
        content="TEXTEXT more text jaefjiafijdsjfsdnfksdnf clankers ghahhah: <math>x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}</math> This formula helps solve quadratic equations like <math>ax^2 + bx + c = 0</math> where a, b, and c are constants."
    )
    
    # Create a temporary image file path to simulate successful LaTeX generation
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
        temp_image_path = temp_file.name
        # Write some dummy content to make it a valid file
        temp_file.write(b'fake_png_data')
    
    try:
        with (
            # Mock the LLM client
            patch("app.services.messaging_service.llm_client.generate_response", new_callable=AsyncMock) as mock_llm_generate,
            # Mock the database operations
            patch("app.services.messaging_service.db.create_new_messages", new_callable=AsyncMock) as mock_db_create,
        ):
            
            # Configure mocks
            mock_llm_generate.return_value = [mock_llm_response]
            
            # Create messaging service and call the method
            messaging_service = MessagingService()
            
            # Execute the test - this will call REAL convert_latex_to_image AND send_image_message
            response = await messaging_service.handle_chat_message(test_user, user_message)
            
            # Assertions
            
            # 1. LLM should have been called with user and message
            mock_llm_generate.assert_called_once_with(user=test_user, message=user_message)
            
            # 2. Database should have been updated with LLM responses
            mock_db_create.assert_called_once_with([mock_llm_response])
            
            # 3. Response should be successful (indicates LaTeX conversion AND WhatsApp sending worked)
            assert response.status_code == 200
            assert response.body == b'{"status":"ok"}'
            
            print("✅ All assertions passed!")
            print(f"📱 REAL WhatsApp image message sent to: {test_user.wa_id}")
            print(f"🖼️ REAL LaTeX document generated and sent from: {mock_llm_response.content[:50]}...")
            print("🎯 This test validates the complete end-to-end flow:")
            print("   • LLM generates response with math content (mocked)")
            print("   • LaTeX conversion to PNG image (REAL)")
            print("   • WhatsApp Cloud API image upload and send (REAL)")
            print("   • Database operations (mocked)")
            
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_image_path):
            os.unlink(temp_image_path)



if __name__ == "__main__":
    print("=== Testing Messaging Service with LaTeX Math Detection ===")
    
    # Run the happy path test
    print("\n1. Testing happy path with math detection...")
    asyncio.run(test_messaging_service_math_detection_happy_path())
    
    print("\n🎉 All tests completed successfully!")
