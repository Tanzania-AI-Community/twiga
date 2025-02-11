import copy
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class ToolName(str, Enum):
    search_knowledge = "search_knowledge"
    generate_exercise = "generate_exercise"


tools_metadata = [
    {
        "type": "function",
        "function": {
            "name": ToolName.search_knowledge.value,
            "description": "Get relevant information from the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_phrase": {
                        "type": "string",
                        "description": "A message describing the information you are looking for.",
                    },
                    "class_id": {
                        "type": "integer",
                        "description": "The class id of the course the question should be based on. Available class IDs: {available_class_ids}",
                    },
                },
                "required": ["query", "class_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ToolName.generate_exercise.value,
            "description": "Generate a single question for the students based on course literature",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A short message describing the desired question or exercise and the topic it should be about. Request just one question.",
                    },
                    "class_id": {
                        "type": "integer",
                        "description": "The class id of the course the question should be based on. Available class IDs: {available_class_ids}",
                    },
                    "subject": {
                        "type": "string",
                        "description": "The subject of the course the question should be based on.",
                    },
                },
                "required": ["query", "class_id", "subject"],
            },
        },
    },
]


def get_tools_metadata(available_classes: str) -> list:
    """
    Get tools metadata with formatted class IDs for all tools.

    Args:
        available_classes: JSON string mapping class names to their IDs
        e.g. '{"Geography Form 2": 1}'
    """
    try:
        # Make a deep copy to avoid modifying the original
        tools = copy.deepcopy(tools_metadata)

        # Format class_id description for all tools
        for tool in tools:
            if "class_id" in tool["function"]["parameters"]["properties"]:
                tool["function"]["parameters"]["properties"]["class_id"][
                    "description"
                ] = (
                    "The class ID for the course. Available classes: "
                    f"{available_classes}"
                )

                # Add enum of available values
                class_ids = json.loads(available_classes)
                tool["function"]["parameters"]["properties"]["class_id"]["enum"] = list(
                    class_ids.values()
                )

        return tools
    except Exception as e:
        logger.error(
            f"Error in get_tools_metadata:\n"
            f"Input available_classes: {available_classes}\n"
            f"Error: {str(e)}",
            exc_info=True,
        )
        raise
