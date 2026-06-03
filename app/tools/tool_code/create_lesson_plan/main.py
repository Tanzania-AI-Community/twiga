import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.database import db
from app.database.db import vector_search
from app.database.enums import ChunkType
from app.database.models import Chunk, Resource
from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


async def create_lesson_plan(
    class_id: int,
    subject: str,
    topic: str,
    lesson_title: str,
    class_context: Optional[list[str]] = None,
) -> str:
    """
    Create a structured lesson plan and return a rendered string.
    """
    try:
        resource_ids = await db.get_class_resources(class_id)
        assert resource_ids

        retrieved_content = await vector_search(
            query=topic,
            n_results=10,
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resource_ids,
            },
        )

        context = _format_context(retrieved_content)
        normalized_class_context = _normalize_class_context(class_context)

        plan_details = {
            "subject": subject,
            "topic": topic,
            "lesson_title": lesson_title,
            "duration_minutes": 45,
        }

        system_prompt_name_objectives = "lesson_plan_objectives_system"
        user_prompt_name_objectives = "lesson_plan_objectives_user"

        objectives_payload = await _call_llm_json(
            system_prompt_name=system_prompt_name_objectives,
            user_prompt_name=user_prompt_name_objectives,
            prompt_vars={
                "class_id": class_id,
                "subject": subject,
                "topic": topic,
                "lesson_title": lesson_title,
                "class_context": normalized_class_context or "",
                "context_str": context,
            },
            run_name="twiga_lesson_plan_objectives",
            metadata={
                "tool": "create_lesson_plan",
                "step": "objectives",
                "class_id": str(class_id),
                "subject": subject,
                "topic": topic,
                **prompt_manager.build_trace_metadata(
                    system_prompt_name=system_prompt_name_objectives,
                    user_prompt_name=user_prompt_name_objectives,
                ),
            },
        )

        system_prompt_name_core = "lesson_plan_core_system"
        user_prompt_name_core = "lesson_plan_core_user"

        core_payload = await _call_llm_json(
            system_prompt_name=system_prompt_name_core,
            user_prompt_name=user_prompt_name_core,
            prompt_vars={
                "class_id": class_id,
                "subject": subject,
                "topic": topic,
                "lesson_title": lesson_title,
                "class_context": normalized_class_context or "",
                "context_str": context,
                "objectives_json": json.dumps(objectives_payload, ensure_ascii=False),
            },
            run_name="twiga_lesson_plan_core",
            metadata={
                "tool": "create_lesson_plan",
                "step": "core",
                "class_id": str(class_id),
                "subject": subject,
                "topic": topic,
                **prompt_manager.build_trace_metadata(
                    system_prompt_name=system_prompt_name_core,
                    user_prompt_name=user_prompt_name_core,
                ),
            },
        )

        system_prompt_name_homework = "lesson_plan_homework_system"
        user_prompt_name_homework = "lesson_plan_homework_user"

        homework_payload = await _call_llm_json(
            system_prompt_name=system_prompt_name_homework,
            user_prompt_name=user_prompt_name_homework,
            prompt_vars={
                "class_id": class_id,
                "subject": subject,
                "topic": topic,
                "lesson_title": lesson_title,
                "class_context": normalized_class_context or "",
                "objectives_json": json.dumps(objectives_payload, ensure_ascii=False),
                "lesson_flow_json": json.dumps(core_payload, ensure_ascii=False),
            },
            run_name="twiga_lesson_plan_homework",
            metadata={
                "tool": "create_lesson_plan",
                "step": "homework",
                "class_id": str(class_id),
                "subject": subject,
                "topic": topic,
                **prompt_manager.build_trace_metadata(
                    system_prompt_name=system_prompt_name_homework,
                    user_prompt_name=user_prompt_name_homework,
                ),
            },
        )

        lesson_plan = {
            **plan_details,
            **objectives_payload,
            **core_payload,
            **homework_payload,
        }

        logger.debug(
            f"Successfully created lesson plan for class_id={class_id}, subject={subject}, topic={topic}, lesson_plan={lesson_plan}"
        )

        return _lesson_plan_json_to_string(lesson_plan)
    except Exception as e:
        logger.error(
            f"Error creating lesson plan for class_id={class_id}, subject={subject}, topic={topic}: {e}",
            exc_info=True,
        )
        raise Exception("Failed to create lesson plan. Please try again.")


def _normalize_class_context(class_context: Optional[list[str]]) -> list[str]:
    if not class_context:
        return []
    return [item.strip() for item in class_context if isinstance(item, str) and item]


def _format_context(
    retrieved_content: list[Chunk],
    resources: Optional[list[Resource]] = None,
) -> str:
    context_parts: list[str] = []
    if resources:
        if len(resources) == 1:
            context_parts.append(
                f"### Context from the resource ({resources[0].name})\n"
            )
        else:
            resource_titles = ", ".join(
                [f"{resource.id}. {resource.name}" for resource in resources]
            )
            context_parts.append(
                f"### Context from the resources ({resource_titles})\n"
            )

    for chunk in retrieved_content:
        if chunk.top_level_section_title and chunk.top_level_section_index:
            heading = f"-text from chapter {chunk.top_level_section_index}. {chunk.top_level_section_title} in resource {chunk.resource_id}"
        elif chunk.top_level_section_title:
            heading = f"-text from section {chunk.top_level_section_title} in resource {chunk.resource_id}"
        else:
            heading = f"-text from resource {chunk.resource_id}"

        context_parts.append(heading)
        context_parts.append(f"{chunk.content}")

    return "\n".join(context_parts)


async def _call_llm_json(
    system_prompt_name: str,
    user_prompt_name: str,
    prompt_vars: dict[str, Any],
    run_name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    system_prompt = prompt_manager.format_prompt(
        system_prompt_name, class_info=prompt_vars.get("subject", "")
    )
    user_prompt = prompt_manager.format_prompt(user_prompt_name, **prompt_vars)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    response = await async_llm_request(
        messages=messages,
        run_name=run_name,
        metadata=metadata,
    )

    return _parse_json_response(response.content)


def _parse_json_response(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise


def _lesson_plan_json_to_string(lesson_plan: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append(f"Lesson Plan: {lesson_plan.get('lesson_title', '')}")
    lines.append(f"Subject: {lesson_plan.get('subject', '')}")
    lines.append(f"Topic: {lesson_plan.get('topic', '')}")
    lines.append(f"Duration: {lesson_plan.get('duration_minutes', 45)} minutes")

    objectives = lesson_plan.get("learning_objectives", [])
    if isinstance(objectives, list) and objectives:
        lines.append("")
        lines.append("Learning Objectives:")
        lines.append("Students will be able to:")
        for idx, objective in enumerate(objectives, start=1):
            lines.append(f"{idx}. {objective}")

    key_concepts = lesson_plan.get("key_concepts", [])
    if isinstance(key_concepts, list) and key_concepts:
        lines.append("")
        lines.append("Key Concepts:")
        lines.extend([f"- {concept}" for concept in key_concepts])

    materials = lesson_plan.get("materials_preparation", {})
    if isinstance(materials, dict):
        materials_needed = materials.get("materials_needed", [])
        teacher_prep = materials.get("teacher_preparation", [])
        if materials_needed or teacher_prep:
            lines.append("")
            lines.append("Materials & Preparation:")
            if materials_needed:
                lines.append("Materials needed:")
                lines.extend([f"- {item}" for item in materials_needed])
            if teacher_prep:
                lines.append("Teacher preparation:")
                lines.extend([f"- {item}" for item in teacher_prep])

    lesson_flow = lesson_plan.get("lesson_flow", [])
    if isinstance(lesson_flow, list) and lesson_flow:
        lines.append("")
        lines.append("Lesson Flow (Time-Structured Activities):")
        for section in lesson_flow:
            if not isinstance(section, dict):
                continue
            title = section.get("title", "")
            duration = section.get("duration_minutes", "")
            lines.append("")
            lines.append(f"{title} ({duration} min)")
            activities = section.get("activities", [])
            for activity in activities:
                if isinstance(activity, str):
                    lines.append(f"- {activity}")
                    continue
                if not isinstance(activity, dict):
                    continue
                activity_type = activity.get("type")
                if activity_type == "exercise":
                    prompt = activity.get("prompt", "")
                    answer = activity.get("answer", "")
                    lines.append(f"- Exercise: {prompt}")
                    if answer:
                        lines.append(f"  Answer: {answer}")
                else:
                    content = activity.get("content") or activity.get("prompt")
                    if content:
                        lines.append(f"- {content}")

    homework = lesson_plan.get("homework", [])
    if isinstance(homework, list) and homework:
        lines.append("")
        lines.append("Homework:")
        lines.extend([f"- {item}" for item in homework])

    return "\n".join([line for line in lines if line is not None])
