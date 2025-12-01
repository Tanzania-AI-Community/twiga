import logging
import backoff
import os
import requests
from typing import List, Optional, Dict, cast, Union
from langchain_openai import ChatOpenAI
from langchain_together.chat_models import ChatTogether
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import SecretStr

from app.config import llm_settings, LLMProvider
from app.monitoring.metrics import LLMCallTracker


# Resolve model names per provider, honoring provider-specific overrides.
def _resolve_model_name() -> str:
    name = llm_settings.llm_name
    if llm_settings.provider == LLMProvider.OLLAMA and llm_settings.ollama_model_name:
        name = llm_settings.ollama_model_name
    elif llm_settings.provider == LLMProvider.MODAL and llm_settings.modal_model_name:
        name = llm_settings.modal_model_name
    return name


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


def get_llm_client(
    tools: Optional[List[Dict]] = None, tool_choice: Optional[str] = None
) -> Union[BaseChatModel, Runnable]:
    """Get the appropriate LangChain LLM client based on configuration."""
    llm: BaseChatModel

    if llm_settings.provider == LLMProvider.TOGETHER:
        if not llm_settings.api_key:
            raise ValueError("Together provider requires LLM_API_KEY to be set.")

        llm = ChatTogether(
            api_key=SecretStr(llm_settings.api_key.get_secret_value()),
            model=llm_settings.llm_name,
        )
    elif llm_settings.provider == LLMProvider.OPENAI:
        if not llm_settings.api_key:
            raise ValueError("OpenAI provider requires LLM_API_KEY to be set.")

        llm = ChatOpenAI(
            api_key=SecretStr(llm_settings.api_key.get_secret_value()),
            model=llm_settings.llm_name,
        )
    elif llm_settings.provider == LLMProvider.OLLAMA:
        model_name = _resolve_model_name()
        if not model_name:
            raise ValueError(
                "Ollama provider requires a model name. Set LLM__OLLAMA_MODEL_NAME or LLM__LLM_MODEL_NAME."
            )

        api_key = (
            llm_settings.api_key.get_secret_value()
            if llm_settings.api_key
            else "ollama"
        )
        llm = ChatOpenAI(
            api_key=SecretStr(api_key),
            model=model_name,
            base_url=llm_settings.ollama_base_url,
        )

    elif llm_settings.provider == LLMProvider.MODAL:
        model_name = _resolve_model_name()
        if not model_name:
            raise ValueError(
                "Modal provider requires a model name. Set LLMProvider.MODAL_MODEL_NAME or LLMProvider.LLM_MODEL_NAME."
            )

        api_key = (
            llm_settings.api_key.get_secret_value() if llm_settings.api_key else "modal"
        )
        llm = ChatOpenAI(
            api_key=SecretStr(api_key),
            model=model_name,
            base_url=llm_settings.modal_base_url.get_secret_value(),
        )

    else:
        raise ValueError("No valid LLM provider configured")

    if tools:
        return llm.bind_tools(tools, tool_choice=tool_choice)

    return llm


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
    run_name: Optional[str] = None,
    metadata: Optional[Dict] = None,
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
        llm = get_llm_client(tools=tools, tool_choice=tool_choice)

        if verbose:
            logger.debug(f"Messages sent to LLM API:\n{messages}")

        # Prepare kwargs for LangSmith tracing
        invoke_kwargs = {}
        if llm_settings.langsmith_tracing:
            # Add tracing configuration
            config = {}
            if run_name:
                config["run_name"] = run_name
            if metadata:
                config["metadata"] = metadata
            if config:
                invoke_kwargs["config"] = config

        # Merge any additional kwargs
        invoke_kwargs.update(kwargs)

        model_name = _resolve_model_name()

        # Make the async call while tracking metrics
        with LLMCallTracker(llm_settings.provider.value, model_name):
            response = await llm.ainvoke(messages, **invoke_kwargs)
            return cast(AIMessage, response)

    except Exception as e:
        logger.error(f"LLM request failed: {str(e)}")
        raise


# Removed conversion functions - now using native LangChain types
