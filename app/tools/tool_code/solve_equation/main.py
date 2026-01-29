import logging
from langchain_core.messages import SystemMessage, HumanMessage
from app.utils.prompt_manager import prompt_manager
from app.utils.llm_utils import async_llm_request

logger = logging.getLogger(__name__)


async def solve_equation(equation: str, concise: bool = True) -> str:
    """
    Solve a mathematical equation and return step-by-step solution.

    Args:
        equation: A string containing the equation in LaTeX syntax
        concise: If True (default), returns only mathematical steps without explanations.
                 If False, returns detailed step-by-step explanations.

    Returns:
        A string containing the step-by-step solution to the equation in LaTeX syntax.
    """
    try:
        system_prompt_name = (
            "equation_solver_system_concise" if concise else "equation_solver_system"
        )
        user_prompt_name = (
            "equation_solver_user_concise" if concise else "equation_solver_user"
        )

        system_prompt = prompt_manager.format_prompt(system_prompt_name)
        user_prompt = prompt_manager.format_prompt(user_prompt_name, equation=equation)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # Use default LLM with math-specific parameters, this can be changed to custom math model later
        response = await async_llm_request(
            messages=messages,
            run_name="twiga_solve_equation",
            metadata={
                "tool": "solve_equation",
                "equation": equation,
            },
        )

        content = response.content
        if isinstance(content, list):
            content_str = ""
            for item in content:
                if isinstance(item, str):
                    content_str += item
                elif isinstance(item, dict) and "text" in item:
                    content_str += item["text"]
            return content_str
        elif isinstance(content, str):
            return content
        else:
            return str(content)

    except Exception as e:
        logger.error(f"Error solving equation '{equation}': {e}", exc_info=True)
        raise Exception(f"Failed to solve the equation. Error: {str(e)}")
