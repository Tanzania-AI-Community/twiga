import logging
import backoff
import os
import requests
from typing import List, Optional, Dict, Any, cast
from typing import List, Optional, Dict, Any, cast
from langchain_openai import ChatOpenAI
from langchain_together.chat_models import ChatTogether
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr
from langsmith.run_helpers import trace as ls_trace

from app.config import llm_settings

# Set up basic logging configuration
logger = logging.getLogger(__name__)


# Configure LangSmith tracing if enabled
def _log_langsmith_status():
    """Log detailed LangSmith availability status based on environment variables."""
    langsmith_api_key_available = llm_settings.langsmith_api_key is not None
    langsmith_tracing_enabled = llm_settings.langsmith_tracing

    logger.info("🔍 LangSmith Configuration Status:")
    logger.info(
        f"  ├── LANGSMITH_API_KEY: {'✅ Available' if langsmith_api_key_available else '❌ Not set'}"
    )
    logger.info(
        f"  ├── LANGSMITH_TRACING: {'✅ Enabled' if langsmith_tracing_enabled else '❌ Disabled'}"
    )
    logger.info(
        f"  ├── LANGSMITH_PROJECT: {llm_settings.langsmith_project or '❌ Not set'}"
    )
    logger.info(
        f"  └── LANGSMITH_ENDPOINT: {llm_settings.langsmith_endpoint or '❌ Not set'}"
    )

    if langsmith_tracing_enabled and langsmith_api_key_available:
        logger.info(
            "🚀 LangSmith tracing is ACTIVE - All LLM interactions will be tracked"
        )
        return True
    elif langsmith_tracing_enabled and not langsmith_api_key_available:
        logger.warning(
            "⚠️  LangSmith tracing is ENABLED but API_KEY is missing - Tracing will not work"
        )
        return False
    elif not langsmith_tracing_enabled and langsmith_api_key_available:
        logger.info(
            "💤 LangSmith tracing is DISABLED (API key available but tracing off)"
        )
        return False
    else:
        logger.info("💤 LangSmith tracing is DISABLED (no API key and tracing off)")
        return False


# Check and configure LangSmith
langsmith_active = _log_langsmith_status()

if langsmith_active:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    if llm_settings.langsmith_api_key:
        os.environ["LANGCHAIN_API_KEY"] = (
            llm_settings.langsmith_api_key.get_secret_value()
        )
    if llm_settings.langsmith_project:
        os.environ["LANGCHAIN_PROJECT"] = llm_settings.langsmith_project
    if llm_settings.langsmith_endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = llm_settings.langsmith_endpoint
    logger.info(
        f"🎯 LangSmith initialized for project: {llm_settings.langsmith_project}"
    )


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


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, Exception),
    max_tries=7,
    max_time=45,
)
async def async_llm_request(
    messages: List[BaseMessage],
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
    verbose: bool = False,
    config: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    run_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parent: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parent: Optional[Any] = None,
    **kwargs,
) -> AIMessage:
    """
    Make a request to LLM using LangChain with exponential backoff retry logic.

    Args:
        messages (List[BaseMessage]): List of LangChain message objects.
        tools (Optional[List[Dict]], optional): List of tools to use with the LLM. Defaults to None.
        tool_choice (Optional[str], optional): Tool choice for the LLM. Defaults to None.
        verbose (bool, optional): Whether to log debug information. Defaults to False.
        run_name (Optional[str], optional): Name for the LangSmith trace run. Defaults to None.
        metadata (Optional[Dict], optional): Additional metadata for LangSmith tracing. Defaults to None.
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

        # Prepare kwargs; pass through provided config (if any) and other kwargs
        # Prepare kwargs; pass through provided config (if any) and other kwargs
        invoke_kwargs = {}
        if config:
            invoke_kwargs["config"] = config
        if config:
            invoke_kwargs["config"] = config
        invoke_kwargs.update(kwargs)

        # Make the async call, wrapped in an explicit LLM child trace when tracing is enabled
        if llm_settings.langsmith_tracing: # Check if true or false
            async with ls_trace(
                name=run_name or "llm_call",
                run_type="llm",
                parent=parent,
                inputs={"messages_count": len(messages)},
                metadata=metadata or {},
            ) as llm_run:
                response = await llm.ainvoke(messages, **invoke_kwargs)
                try:
                    content_preview = None
                    if getattr(response, "content", None):
                        if isinstance(response.content, str):
                            content_preview = response.content[:500]
                        elif isinstance(response.content, list):
                            content_preview = str(response.content)[:500]
                    await llm_run.end(outputs={"output_preview": content_preview})
                except Exception:
                    pass
                return cast(AIMessage, response)
        else:
            response = await llm.ainvoke(messages, **invoke_kwargs)
            return cast(AIMessage, response)

    except Exception as e:
        logger.error(f"LLM request failed: {str(e)}")
        raise


# Removed conversion functions - now using native LangChain types
