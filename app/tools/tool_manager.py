import re
import uuid
import json
import logging
from langchain_core.messages import AIMessage
from app.database.models import Message
from app.database.enums import MessageRole
from typing import Optional, Any
from dataclasses import dataclass
from app.database.models import User
from app.tools.registry import ToolName
from app.tools.tool_code.generate_exercise.main import generate_exercise
from app.tools.tool_code.search_knowledge.main import search_knowledge


# Simple Types replacements for OpenAI types
@dataclass
class Function:
    name: str
    arguments: str


@dataclass
class ChatCompletionMessageToolCall:
    id: str
    function: Function
    type: str = "function"

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "function": {
                "name": self.function.name,
                "arguments": self.function.arguments,
            },
            "type": self.type,
        }


class ToolManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def extract_tool_calls(self, llm_response: AIMessage) -> list[dict[str, Any]]:
        """
        This method extracts valid tool calls from the LLM response. If no valid tool calls are found,
        it attempts to recover malformed tool calls from the response content.

        Args:
            llm_response (AIMessage): The response from the LLM.

        Returns:
            list[dict[str, Any]]: A list of tool call dictionaries. If no tool calls are found, an empty list is returned.
        """
        tool_calls = []

        if hasattr(llm_response, "tool_calls") and llm_response.tool_calls:
            tool_calls = [
                {
                    "id": tool_call.get("id", f"call_{str(uuid.uuid4())}"),
                    "function": {
                        "name": tool_call["name"],
                        "arguments": json.dumps(tool_call.get("args", {})),
                    },
                    "type": "function",
                }
                for tool_call in llm_response.tool_calls
            ]
        else:
            self.logger.debug(
                "No valid tool calls found, attempting to recover malformed tool calls."
            )
            tool_call_data = self._catch_malformed_tool(str(llm_response.content))
            self.logger.debug(f"Recovered tool call data: {tool_call_data}")

            if tool_call_data:
                tool_calls = [tool_call_data.model_dump()]

        return tool_calls

    def _catch_malformed_tool(
        self, content_str: str
    ) -> Optional[ChatCompletionMessageToolCall]:
        """
        Parse response text to extract a tool call if present.
        """

        # Try XML format first
        xml_match = re.search(
            r"<function=([A-Za-z_]\w*)>(.*?)</function>", content_str, flags=re.DOTALL
        )
        if xml_match:
            self.logger.warning(
                "Malformed XML tool call detected, attempting recovery."
            )
            return ChatCompletionMessageToolCall(
                id=f"call_{str(uuid.uuid4())}",
                function=Function(
                    name=xml_match.group(1),
                    arguments=json.dumps(json.loads(xml_match.group(2).strip())),
                ),
                type="function",
            )

        # Try JSON format
        try:
            json_data = json.loads(content_str)
            if (
                isinstance(json_data, dict)
                and "name" in json_data
                and "parameters" in json_data
            ):
                self.logger.warning(
                    "Malformed JSON tool call detected, attempting recovery."
                )
                # Handle case where parameters is already a string
                params = json_data["parameters"]
                if isinstance(params, str):
                    try:
                        # Try parsing it in case it's a string-encoded JSON
                        params = json.loads(params)
                    except json.JSONDecodeError as e:
                        # If it fails to parse, use it as is
                        self.logger.warning(
                            "Failed to decode tool call parameters: %s", e
                        )
                return ChatCompletionMessageToolCall(
                    id=f"call_{str(uuid.uuid4())}",
                    function=Function(
                        name=json_data["name"],
                        arguments=(
                            json.dumps(params) if isinstance(params, dict) else params
                        ),
                    ),
                    type="function",
                )
        except json.JSONDecodeError as e:
            self.logger.warning("Failed to decode tool call JSON content: %s", e)

        return None

    async def process_tool_calls(
        self, tool_calls: list[dict[str, Any]], user: User
    ) -> list[Message]:
        """
        Process tool calls and return their responses as Message objects.
        """
        tool_calls = [
            ChatCompletionMessageToolCall(
                id=call.get("id", f"call_{str(uuid.uuid4())}"),
                function=Function(
                    name=call["function"]["name"],
                    arguments=call["function"]["arguments"],
                ),
                type="function",
            )
            for call in tool_calls
        ]

        tool_responses = []
        for tool_call in tool_calls:
            try:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                if function_name == ToolName.search_knowledge.value:
                    result = await search_knowledge(**function_args)
                elif function_name == ToolName.generate_exercise.value:
                    result = await generate_exercise(**function_args)

                tool_responses.append(
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content=result,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.function.name,
                    )
                )

            except Exception as e:
                self.logger.error(f"Error in {function_name}: {str(e)}")
                tool_responses.append(
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content=json.dumps({"error": str(e)}),
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.function.name,
                    )
                )
        return tool_responses
