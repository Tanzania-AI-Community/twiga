

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from app.services.llm_service import LLMClient
from app.database.models import Message, User
from app.database.enums import MessageRole
from app.utils.prompt_manager import prompt_manager


@pytest.mark.unittest
async def test_catch_malformed_tool_No_message() -> None:
    #test _catch_malformed_tool function
    llmclient = LLMClient()
    msg = Message()
    response = llmclient._catch_malformed_tool(msg)
    assert response is None

@pytest.mark.unittest
async def test_catch_malformed_tool_valid_XML() -> None:
    # test _catch_malformed_tool function
    llmclient = LLMClient()
    msg = Message()
    msg.tool_calls = None
    msg.content = '<function=clankerfunction>{"query": "Expected clanker answer"}</function>'
    response = llmclient._catch_malformed_tool(msg)
    assert response is not None
    assert response.function.name == "clankerfunction"
    assert response.function.arguments  == '{"query": "Expected clanker answer"}'
    assert response.type == "function"

@pytest.mark.unittest
async def test_catch_malformed_tool_valid_JSON_parameter_as_dict() -> None:
    llmclient = LLMClient()
    msg = Message()
    msg.tool_calls = None
    msg.content = '{"name": "search_knowledge", "parameters": {"query": "What is the capital of Tanzania?"}}'
    response = llmclient._catch_malformed_tool(msg)
    assert response is not None
    assert response.function.name == "search_knowledge"
    assert response.function.arguments == '{"query": "What is the capital of Tanzania?"}'
    assert response.type == "function"

@pytest.mark.unittest
async def test_catch_malformed_tool_valid_JSON_parameter_as_str() -> None:
    llmclient = LLMClient()
    msg = Message()
    msg.tool_calls = None
    msg.content = '{"name": "search_knowledge", "parameters": "{\\"query\\": \\"What is the capital of Tanzania?\\"}"}'
    response = llmclient._catch_malformed_tool(msg)
    assert response is not None
    assert response.function.name == "search_knowledge"
    assert response.function.arguments == '{"query": "What is the capital of Tanzania?"}'
    assert response.type == "function"

@pytest.mark.unittest
async def test_catch_malformed_tool_invalid_JSON() -> None:
    llmclient = LLMClient()
    msg = Message()
    msg.tool_calls = None
    msg.content = '{"name": "search_knowledge", "parameters": {"query": "What is the capital of Tanzania?"}'
    response = llmclient._catch_malformed_tool(msg)
    assert response is None

@pytest.mark.asyncio
async def test_format_messages_happy_path():
    llmclient = LLMClient()
    user = User(name="Test User")
    mock_history = [
        Message(role=MessageRole.user, content="Hello!"),
        Message(role=MessageRole.assistant, content="Hi, how can I help you?"),
    ]
    new_messages = [
        Message(role=MessageRole.user, content="What is the capital of Tanzania?"),
        Message(role=MessageRole.assistant, content="The capital is Dodoma."),
    ]
    response = llmclient._format_messages(new_messages=new_messages, database_messages=mock_history, user=user)
    # Only the system prompt and new messages will be included, since len(new_messages) == len(mock_history)
    assert [
        (msg["role"], msg["content"])
        for msg in response
    ] == [
        (MessageRole.system, response[0]["content"]),  # system prompt content may vary
        (MessageRole.user, "What is the capital of Tanzania?"),
        (MessageRole.assistant, "The capital is Dodoma."),
    ]

@pytest.mark.asyncio
async def test_format_messages_slice_logic():
    """Test the slicing logic for formatting messages."""
    llmclient = LLMClient()
    user = User(name="Test User")
    # 4 messages in history
    mock_history = [
        Message(role=MessageRole.user, content="msg1"),
        Message(role=MessageRole.assistant, content="msg2"),
        Message(role=MessageRole.user, content="msg3"),
        Message(role=MessageRole.assistant, content="msg4"),
    ]
    # 2 new messages
    new_messages = [
        Message(role=MessageRole.user, content="msg5"),
        Message(role=MessageRole.assistant, content="msg6"),
    ]
    response = llmclient._format_messages(new_messages=new_messages, database_messages=mock_history, user=user)
    # Should include: system prompt, first two history messages, then new messages
    expected_system_prompt = prompt_manager.format_prompt(
        "twiga_system",
        user_name=user.name,
        class_info=user.formatted_class_info,
    )
    assert [
        (msg["role"], msg["content"])
        for msg in response
    ] == [
        (MessageRole.system, expected_system_prompt),
        (MessageRole.user, "msg1"),
        (MessageRole.assistant, "msg2"),
        (MessageRole.user, "msg5"),
        (MessageRole.assistant, "msg6"),
    ]

@pytest.mark.asyncio
async def test_format_messages_missmatch():
    """check if a missmatch between histry and new messages raises an exception"""
    llmclient = LLMClient()
    user = User(name="Test User")
    # 2 messages in history
    mock_history = [
        Message(role=MessageRole.user, content="msg1"),
        Message(role=MessageRole.assistant, content="msg2"),
    ]
    # 3 new messages
    new_messages = [
        Message(role=MessageRole.user, content="msg3"),
        Message(role=MessageRole.assistant, content="msg4"),
        Message(role=MessageRole.user, content="msg5"),
    ]
    with pytest.raises(Exception) as excinfo:
            llmclient._format_messages(new_messages=new_messages, database_messages=mock_history, user=user)
    assert "Unusual message count scenario detected" in str(excinfo.value)    

@patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock)


@pytest.mark.asyncio
async def test_LLMClient_no_tool_calls(mock_get_history):
    """Test that LLMClient generates a response without tool calls."""
    
    with (
        patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
        patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")) as mock_format_prompt,
        patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
        patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock) as mock_send_message,

    ):
        # Set up mock return values
        mock_get_history.return_value = []
        mock_async_llm_request.return_value = MagicMock(
            content="Totally real robot response", tool_calls=None
        )
        llmclient = LLMClient()
        user = User(id=1, name="User")

        #Test with no history and no tool calls
        msg = Message(role=MessageRole.user, content="I have no tool calls", tool_calls=None)
        response = await llmclient.generate_response(user=user, message=msg)
        # Assert if msg went through generate_response and returned the mock response with no tool calls
        assert isinstance(response, list)
        assert len(response) == 1
        assert response[0].role == MessageRole.assistant
        assert response[0].content == "Totally real robot response"
        assert response[0].tool_calls is None

@pytest.mark.asyncio
async def test_LLMClient_single_assistant_message():
    """Test that LLMClient generates a response with a single assistant message."""
    with (
        patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
        patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")) as mock_format_prompt,
        patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
        patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock) as mock_send_message,
    ):
        # Set up mock return values
        mock_get_history.return_value = []
        mock_async_llm_request.return_value = MagicMock(
            content="Totally real robot response", tool_calls=None
        )
        #Test with no history and single assistant messages
        user = User(id=1, name="Assistant")
        llmclient = LLMClient()

        msg = Message(role=MessageRole.assistant, content="Beepbeppboopboop generic robot sounds", tool_calls=None)
        #the response will be entirely based on what the mock_async_llm_request.return_value, that we mock the row above
        response = await llmclient.generate_response(user=user, message=msg) 
        assert isinstance(response, list)
        assert len(response) == 1
        assert response[0].role == MessageRole.assistant
        assert response[0].content == "Totally real robot response"
        assert response[0].tool_calls is None 
        
@pytest.mark.asyncio
async def test_LLMClient_structured_tool_call():
    """Test that a structured tool call from the LLM is processed correctly by entering a msg with the mock LLM_request deciding it is a tool call"""
    with (
        patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
        patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")) as mock_format_prompt,
        patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
        patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock) as mock_send_message,
        patch("app.services.llm_service.search_knowledge", new_callable=AsyncMock) as mock_search_knowledge
    ):
        mock_get_history.return_value = []

        mock_search_knowledge.return_value = "The capital of Tanzania is Dodoma"  
        mock_async_llm_request.return_value = MagicMock(
            content="wow such tool calls should be made",
            tool_calls=[
                {
                    "id": "call_123",
                    "name": "search_knowledge",
                    "args": {
                        "search_phrase": "What is the capital of Tanzania?",
                        "class_id": 1
                    },
                    "type": "function",
                }
            ],
        )  # simulate that our llm_request returns a structured tool call

        user = User(id=1, name="User")
        llmclient = LLMClient()

        msg = Message(role=MessageRole.user, content="What is the capital of Tanzania?", tool_calls=None) #doesnt rly matter since we mock the llm response
        response = await llmclient.generate_response(user=user, message=msg)
        assert response[0].role == MessageRole.assistant
        assert response[1].tool_name == "search_knowledge" #assert if a tool call was made
        assert response[1].content =="The capital of Tanzania is Dodoma" #assert if the tool call response was added as a message


@pytest.mark.asyncio
async def test_LLMClient_malformed_tool_call_logs_warning(caplog):
    """Test that a malformed tool call from the LLM is caught and a warning is logged."""
    with (
        patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
        patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")),
        patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
        patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock),
        patch("app.services.llm_service.search_knowledge", new_callable=AsyncMock) as mock_search_knowledge
    ):
        mock_get_history.return_value = []
        malformed_content = '<function=search_knowledge>{"search_phrase": "What is the capital of Tanzania?", "class_id": 1}</function>'
        mock_async_llm_request.return_value = MagicMock(
            content=malformed_content,
            tool_calls=None
        )
        mock_search_knowledge.return_value = "Recovered: Dodoma is the capital of Tanzania." #mock what the search knowledge returns from db

        user = User(id=1, name="User")
        llmclient = LLMClient()
        msg = Message(role=MessageRole.user, content="What is the capital of Tanzania?", tool_calls=None)

        with caplog.at_level("WARNING", logger="app.services.llm_service"):
            await llmclient.generate_response(user=user, message=msg)

        # Assert that the warning about malformed XML tool call was logged
        assert any(
            "Malformed XML tool call detected, attempting recovery." in record.message
            for record in caplog.records
        )

@pytest.mark.asyncio
async def test_LLMClient_tool_function_raises_error_message():
    """Test the LLMClient handling when a tool function raises an exception"""
    with ( 
        #do not mock a db 
        patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
        patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")),
        patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
        patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock),
    ):
        mock_get_history.return_value = []
        # Simulate LLM returning a structured tool call for generate_exercise
        mock_async_llm_request.return_value = MagicMock(
            content=None,
            tool_calls=[
                {
                    "id": "call_456",
                    "name": "generate_exercise",
                    "args": {
                        "query": "Create an exercise about Tanzania.",
                        "class_id": 1,
                        "subject": "Geography"
                    },
                    "type": "function",
                }
            ],
        )
        # Make the tool function raise an exception

        user = User(id=1, name="User")
        llmclient = LLMClient()
        msg = Message(role=MessageRole.user, content="Create an exercise about Tanzania.", tool_calls=None)

        response = await llmclient.generate_response(user=user, message=msg)

        # Assert that the error in generate_exercise is made since we have no mock db
        assert any(
            m.role == MessageRole.tool and
            "failed to find content from the textbooks to generate this exercise. skipping." in m.content.lower()
            for m in response
        )


@pytest.mark.asyncio
async def test_LLMClient_character_limit_exceeded(monkeypatch):
    """Test that LLMClient handles messages exceeding character limit."""
    with ( 
    patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
    patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")),
    patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
    patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock),
    ):
        mock_get_history.return_value = []

        # Set the character limit to a low value for testing
        monkeypatch.setattr("app.config.settings.message_character_limit", 1)
        msg = Message(role=MessageRole.user, content="This message exceeds the limit 100%.", tool_calls=None)
        llmclient = LLMClient()
        user = User(id=1, name="User")
        response = await llmclient.generate_response(user=user, message=msg)
        # Assert that the response contains the error message about character limit
        assert any(
            m.role == MessageRole.system and
            'Sorry, the message you sent is too long. Please try again with a shorter message.' in m.content
            for m in response
        )

@pytest.mark.integration
async def test_LLMClient_two_concurrent_messages_behavior():
    user = User(id=1, name="User")
    llmclient = LLMClient()
    msg1 = Message(role=MessageRole.user, content="First message", tool_calls=None)
    msg2 = Message(role=MessageRole.user, content="Second message", tool_calls=None)
    with (
        patch("app.services.llm_service.get_user_message_history", new_callable=AsyncMock) as mock_get_history,
        patch("app.services.llm_service.prompt_manager.format_prompt", MagicMock(return_value="system prompt")),
        patch("app.services.llm_service.async_llm_request", new_callable=AsyncMock) as mock_async_llm_request,
        patch("app.services.llm_service.whatsapp_client.send_message", new_callable=AsyncMock),
        patch("app.services.llm_service.get_tools_metadata", MagicMock(return_value=[]))
    ):
        mock_get_history.return_value = []
        # Simulate LLM taking time to respond
        async def slow_llm_request(*args, **kwargs):
            await asyncio.sleep(0.5)
            return MagicMock(content="LLM response", tool_calls=None)
        mock_async_llm_request.side_effect = slow_llm_request

        # Start two concurrent generate_response calls
        task1 = asyncio.create_task(llmclient.generate_response(user=user, message=msg1))
        await asyncio.sleep(0.05)  # Ensure the first task acquires the lock
        task2 = asyncio.create_task(llmclient.generate_response(user=user, message=msg2))

        result1 = await task1
        result2 = await task2

        # The first call should get a response, the second should return None (buffered)
        assert result1 is not None
        assert result2 is None

        # simulate a follow-up call to process the buffered message
        result3 = await llmclient.generate_response(user=user, message=msg2)
        assert result3 is not None
        assert any("LLM response" in m.content for m in result3)


@pytest.mark.asyncio
async def test_catch_latex_math(caplog):
    """Test the _catch_latex_math function."""
    llmclient = LLMClient()
    msg = Message()
    msg.content = "Here is some math: $E=mc^2$ and also $$a^2 + b^2 = c^2$$."
    
    with caplog.at_level("WARNING", logger="app.services.llm_service"):
        response = llmclient._catch_latex_math(msg=msg)
    # Assert that the LaTeX math detection log message was captured
    assert any(
        "LaTeX math expression detected in final response, converting into image..." in record.message
        for record in caplog.records
    )