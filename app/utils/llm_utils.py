import logging
import backoff
from typing import List, Optional, Dict, cast
from langchain_openai import ChatOpenAI
from langchain_together.chat_models import ChatTogether
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from app.config import llm_settings

# Set up basic logging configuration
logger = logging.getLogger(__name__)


def get_llm_client() -> BaseChatModel:
    """Get the appropriate LangChain LLM client based on configuration."""
    if llm_settings.ai_provider == "together" and llm_settings.llm_api_key:
        return ChatTogether(
            api_key=SecretStr(llm_settings.llm_api_key.get_secret_value()),
            model=llm_settings.llm_model_name,
        )
    elif llm_settings.ai_provider == "openai" and llm_settings.llm_api_key:
        return ChatOpenAI(
            api_key=SecretStr(llm_settings.llm_api_key.get_secret_value()),
            model=llm_settings.llm_model_name,
        )
    else:
        raise ValueError("No valid LLM provider configured")


@backoff.on_exception(backoff.expo, Exception, max_tries=7, max_time=45)
async def async_llm_request(
    messages: List[BaseMessage],
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
    verbose: bool = False,
    **kwargs,
) -> AIMessage:
    """
    Make a request to LLM using LangChain with exponential backoff retry logic.

    Args:
        messages (List[BaseMessage]): List of LangChain message objects.
        tools (Optional[List[Dict]], optional): List of tools to use with the LLM. Defaults to None.
        tool_choice (Optional[str], optional): Tool choice for the LLM. Defaults to None.
        verbose (bool, optional): Whether to log debug information. Defaults to False.
        **kwargs: Additional keyword arguments for the LLM call.
    Returns:
        AIMessage: The response from the LLM as a LangChain AIMessage.
    Raises:
        Exception: If the LLM request fails after retries.
    """
    try:
        llm = get_llm_client()

        if verbose:
            logger.debug(f"Messages sent to LLM API:\n{messages}")

        # Handle tools if provided
        if tools:
            llm = llm.bind_tools(tools, tool_choice=tool_choice)

        # Make the async call
        response = await llm.ainvoke(messages, **kwargs)
        return cast(AIMessage, response)

    except Exception as e:
        logger.error(f"LLM request failed: {str(e)}")
        raise


# Removed conversion functions - now using native LangChain types
