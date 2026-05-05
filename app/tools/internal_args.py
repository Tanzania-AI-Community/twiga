from app.database.models import User
from app.tools.registry import ToolName


def _build_generate_necta_style_exam_internal_args(user: User) -> dict[str, int]:
    if user.id is None:
        raise ValueError(
            "Cannot inject internal arg 'user_id' in _build_generate_necta_style_exam_internal_args:  user.id is None."
        )
    return {"user_id": user.id}


INTERNAL_TOOL_ARGS_MAPPING = {
    ToolName.generate_necta_style_exam: _build_generate_necta_style_exam_internal_args,
}


def get_internal_tool_args(function_name: str, user: User) -> dict:
    """
    Get internal tool arguments based on the function name and user context.
    Args:
        function_name: The name of the tool function being called.
        user: The User object for context.
    Returns:
        A dictionary of internal arguments to be passed to the tool function.
    """
    mapping_function = INTERNAL_TOOL_ARGS_MAPPING.get(function_name)
    if mapping_function is None:
        return {}

    internal_args = mapping_function(user)
    if not isinstance(internal_args, dict):
        raise ValueError(
            f"Internal args mapping for tool '{function_name}' must return a dict."
        )

    return internal_args
