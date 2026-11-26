import json

import pytest

from app.database.enums import GradeLevel, SubjectName
from app.services.profile import Catalog
from app.tools.registry import (
    CURRICULUM_TOOLS,
    PROFILE_TOOLS,
    TOOL_FUNCTION_MAP,
    TOOLS_METADATA,
    ToolName,
    get_tools_metadata,
)

CLASSES = json.dumps({"Geography Form 2": 102})
CATALOG = Catalog(
    classes={
        SubjectName.geography: {GradeLevel.os1: 101, GradeLevel.os2: 102},
        SubjectName.english: {GradeLevel.os1: 201},
    }
)


def _names(tools: list) -> set[str]:
    return {tool["function"]["name"] for tool in tools}


def _schema(tools: list, name: ToolName) -> dict:
    return next(t for t in tools if t["function"]["name"] == name.value)["function"]


def test_every_tool_has_metadata_and_a_function() -> None:
    names = {tool.value for tool in ToolName}

    assert _names(TOOLS_METADATA) == names
    assert set(TOOL_FUNCTION_MAP) == names
    assert PROFILE_TOOLS | CURRICULUM_TOOLS == frozenset(ToolName)
    assert not PROFILE_TOOLS & CURRICULUM_TOOLS


def test_defaults_to_all_tools_when_a_catalog_is_given() -> None:
    assert _names(get_tools_metadata(CLASSES, catalog=CATALOG)) == {
        tool.value for tool in ToolName
    }


def test_filters_to_allowed_tools() -> None:
    tools = get_tools_metadata(CLASSES, allowed=PROFILE_TOOLS, catalog=CATALOG)

    assert _names(tools) == {tool.value for tool in PROFILE_TOOLS}


@pytest.mark.parametrize("catalog", [None, Catalog(classes={})])
def test_profile_tools_are_left_out_without_a_catalog(catalog) -> None:
    tools = get_tools_metadata(CLASSES, catalog=catalog)

    assert _names(tools) == {tool.value for tool in CURRICULUM_TOOLS}


def test_profile_enums_come_from_the_catalog() -> None:
    tools = get_tools_metadata(CLASSES, allowed=PROFILE_TOOLS, catalog=CATALOG)
    item = _schema(tools, ToolName.update_my_classes)["parameters"]["properties"][
        "classes"
    ]["items"]["properties"]

    assert item["subject"]["enum"] == ["english", "geography"]
    assert item["forms"]["items"]["enum"] == ["Form 1", "Form 2"]


def test_class_id_enum_still_filled_for_curriculum_tools() -> None:
    tools = get_tools_metadata(CLASSES, allowed=CURRICULUM_TOOLS)
    class_id = _schema(tools, ToolName.search_knowledge)["parameters"]["properties"][
        "class_id"
    ]

    assert class_id["enum"] == [102]


def test_shared_definitions_are_not_mutated() -> None:
    get_tools_metadata(CLASSES, catalog=CATALOG)
    definition = next(
        t["function"]
        for t in TOOLS_METADATA
        if t["function"]["name"] == ToolName.update_my_classes.value
    )

    assert (
        "enum"
        not in definition["parameters"]["properties"]["classes"]["items"]["properties"][
            "subject"
        ]
    )


@pytest.mark.parametrize("tool", sorted(PROFILE_TOOLS))
def test_profile_tool_schemas_never_expose_who_is_changed(tool: ToolName) -> None:
    schema = json.dumps(_schema(TOOLS_METADATA, tool)["parameters"])

    for forbidden in ('"user"', '"user_id"', '"wa_id"', '"state"', '"role"'):
        assert forbidden not in schema
