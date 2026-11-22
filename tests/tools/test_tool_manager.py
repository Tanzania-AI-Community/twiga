import json

import pytest

from app.tools.tool_manager import ToolManager


@pytest.fixture
def tool_manager() -> ToolManager:
    return ToolManager()


def test_catch_malformed_tool_returns_none_for_empty_content(
    tool_manager: ToolManager,
) -> None:
    assert tool_manager._catch_malformed_tool("") is None


def test_catch_malformed_tool_recovers_xml_tool_call(
    tool_manager: ToolManager,
) -> None:
    content = '<function=search_knowledge>{"query": "photosynthesis"}</function>'
    recovered = tool_manager._catch_malformed_tool(content)

    assert recovered is not None
    assert recovered.function.name == "search_knowledge"
    assert json.loads(recovered.function.arguments) == {"query": "photosynthesis"}


def test_catch_malformed_tool_recovers_json_with_dict_parameters(
    tool_manager: ToolManager,
) -> None:
    content = json.dumps(
        {
            "name": "generate_exercise",
            "parameters": {"query": "algebra", "class_id": 1},
        }
    )
    recovered = tool_manager._catch_malformed_tool(content)

    assert recovered is not None
    assert recovered.function.name == "generate_exercise"
    assert json.loads(recovered.function.arguments) == {
        "query": "algebra",
        "class_id": 1,
    }


def test_catch_malformed_tool_recovers_json_with_string_parameters(
    tool_manager: ToolManager,
) -> None:
    parameters = json.dumps({"query": "algebra", "class_id": 1})
    content = json.dumps({"name": "generate_exercise", "parameters": parameters})
    recovered = tool_manager._catch_malformed_tool(content)

    assert recovered is not None
    assert json.loads(recovered.function.arguments) == {
        "query": "algebra",
        "class_id": 1,
    }


def test_catch_malformed_tool_returns_none_for_invalid_json(
    tool_manager: ToolManager,
) -> None:
    assert tool_manager._catch_malformed_tool("{not-valid-json") is None
