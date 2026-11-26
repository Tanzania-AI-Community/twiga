import copy
import json
import logging
from enum import Enum
from typing import Any

from app.services.profile import Catalog
from app.tools.tool_code.create_lesson_plan.main import create_lesson_plan
from app.tools.tool_code.generate_exercise.main import generate_exercise
from app.tools.tool_code.generate_necta_style_exam.main import generate_necta_style_exam
from app.tools.tool_code.search_knowledge.main import search_knowledge
from app.tools.tool_code.solve_equation.main import solve_equation
from app.tools.tool_code.update_my_classes.main import update_my_classes
from app.tools.tool_code.update_my_name.main import update_my_name

logger = logging.getLogger(__name__)


class ToolName(str, Enum):
    create_lesson_plan = "create_lesson_plan"
    search_knowledge = "search_knowledge"
    generate_exercise = "generate_exercise"
    solve_equation = "solve_equation"
    generate_necta_style_exam = "generate_necta_style_exam"
    update_my_name = "update_my_name"
    update_my_classes = "update_my_classes"


# Tools that change the teacher's own profile; they need the subject catalog
PROFILE_TOOLS = frozenset({ToolName.update_my_name, ToolName.update_my_classes})
CURRICULUM_TOOLS = frozenset(ToolName) - PROFILE_TOOLS


TOOL_FUNCTION_MAP = {
    ToolName.create_lesson_plan.value: create_lesson_plan,
    ToolName.search_knowledge.value: search_knowledge,
    ToolName.generate_exercise.value: generate_exercise,
    ToolName.solve_equation.value: solve_equation,
    ToolName.generate_necta_style_exam.value: generate_necta_style_exam,
    ToolName.update_my_name.value: update_my_name,
    ToolName.update_my_classes.value: update_my_classes,
}


TOOLS_METADATA = [
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
                        "description": "A short, topic-focused search query (concept keywords only).",
                    },
                    "class_id": {
                        "type": "integer",
                        "description": "The class id of the course the question should be based on. Available class IDs: {available_class_ids}",
                    },
                },
                "required": ["search_phrase", "class_id"],
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
    {
        "type": "function",
        "function": {
            "name": ToolName.solve_equation.value,
            "description": "Solve a mathematical equation and return step-by-step solution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "equation": {
                        "type": "string",
                        "description": "A string containing the equation in LaTeX syntax.",
                    },
                    "concise": {
                        "type": "boolean",
                        "description": "If true (default), returns only mathematical steps. If false, returns detailed explanations with reasoning for each step.",
                    },
                },
                "required": ["equation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ToolName.generate_necta_style_exam.value,
            "description": "Generate a full NECTA-style exam paper and marking scheme for selected topics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "integer",
                        "description": "The class id of the course the exam should be based on. Available class IDs: {available_class_ids}",
                    },
                    "subject": {
                        "type": "string",
                        "description": "The subject name for the exam.",
                    },
                    "topics": {
                        "type": "array",
                        "description": "List of all topics to cover in the generated exam. (e.g. ['climate', 'weather'])",
                        "items": {"type": "string"},
                    },
                },
                "required": ["class_id", "subject", "topics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ToolName.create_lesson_plan.value,
            "description": "Create a lesson plan for a specific class, subject, and topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "integer",
                        "description": "The class id for the lesson plan. Available class IDs: {available_class_ids}",
                    },
                    "subject": {
                        "type": "string",
                        "description": "The subject the lesson plan should cover.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "The topic the lesson plan should cover.",
                    },
                    "lesson_title": {
                        "type": "string",
                        "description": "The title of the lesson plan.",
                    },
                    "class_context": {
                        "type": "array",
                        "description": "Optional list of class context notes (prior knowledge, struggles, or relevant notes provided by the teacher).",
                        "items": {"type": "string"},
                    },
                },
                "required": ["class_id", "subject", "topic", "lesson_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ToolName.update_my_name.value,
            "description": (
                "Save the name the teacher wants to be called. Call it only when "
                "the teacher clearly states their name or asks to change it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "maxLength": 50,
                        "description": (
                            "Only the name itself, e.g. 'Luke Nuru' from 'my name "
                            "is Luke Nuru'. Never the whole sentence."
                        ),
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ToolName.update_my_classes.value,
            "description": (
                "Change the subjects and forms the teacher teaches. Use 'add' for "
                "classes they also teach, 'remove' for classes they no longer teach, "
                "and 'replace' when they list everything they teach now."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "replace"],
                    },
                    "classes": {
                        "type": "array",
                        "description": (
                            "Subjects with the forms they are taught in. For 'remove', "
                            "an empty forms list removes the whole subject."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "subject": {"type": "string"},
                                "forms": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["subject", "forms"],
                        },
                    },
                    "unavailable_subjects": {
                        "type": "array",
                        "description": (
                            "Subjects the teacher mentioned that are not in the "
                            "subject list, e.g. ['Kiswahili']."
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": ["action", "classes"],
            },
        },
    },
]


def _fill_class_id_enum(tool: dict[str, Any], available_classes: str) -> None:
    properties = tool["function"]["parameters"]["properties"]
    if "class_id" not in properties:
        return
    properties["class_id"][
        "description"
    ] = f"The class ID for the course. Available classes: {available_classes}"
    properties["class_id"]["enum"] = list(json.loads(available_classes).values())


def _fill_profile_enums(tool: dict[str, Any], catalog: Catalog) -> None:
    if tool["function"]["name"] != ToolName.update_my_classes.value:
        return
    class_item = tool["function"]["parameters"]["properties"]["classes"]["items"]
    class_item["properties"]["subject"]["enum"] = catalog.subject_enum()
    class_item["properties"]["forms"]["items"]["enum"] = catalog.form_enum()


def get_tools_metadata(
    available_classes: str,
    allowed: frozenset[ToolName] | None = None,
    catalog: Catalog | None = None,
) -> list:
    """
    Get tools metadata for the allowed tools, with their enums filled in.

    Args:
        available_classes: JSON string mapping class names to their IDs
            e.g. '{"Geography Form 2": 1}'
        allowed: The tools the current agent mode may use (default: all)
        catalog: Subjects and forms for the profile tools. Without a catalog
            (or with an empty one) the profile tools are left out.
    """
    try:
        allowed_names = {tool.value for tool in (allowed or frozenset(ToolName))}
        if catalog is None or not catalog.classes:
            allowed_names -= {tool.value for tool in PROFILE_TOOLS}

        # Deep copy so the enums never leak into the shared definitions
        tools = [
            copy.deepcopy(tool)
            for tool in TOOLS_METADATA
            if tool["function"]["name"] in allowed_names
        ]
        for tool in tools:
            _fill_class_id_enum(tool, available_classes)
            if catalog is not None:
                _fill_profile_enums(tool, catalog)

        return tools
    except Exception as e:
        logger.error(
            f"Error in get_tools_metadata:\n"
            f"Input available_classes: {available_classes}\n"
            f"Error: {str(e)}",
            exc_info=True,
        )
        raise
