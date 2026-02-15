import copy
import logging
import backoff
import os
import requests
from typing import List, Optional, Dict, cast, Union
from langchain_openai import ChatOpenAI
from langchain_together.chat_models import ChatTogether
from langchain_google_genai import ChatGoogleGenerativeAI
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


def _convert_tools_for_gemini(tools: List[Dict]) -> List[Dict]:
    """
    Convert tool schemas to be compatible with Gemini.
    Gemini only allows enum on STRING type properties, so we convert
    integer enums to string enums and change the type accordingly.
    """
    converted_tools = copy.deepcopy(tools)
    for tool in converted_tools:
        if "function" in tool and "parameters" in tool["function"]:
            properties = tool["function"]["parameters"].get("properties", {})
            for prop_name, prop_value in properties.items():
                if "enum" in prop_value:
                    # Gemini requires enum values to be strings and type to be STRING
                    prop_value["enum"] = [str(v) for v in prop_value["enum"]]
                    prop_value["type"] = "string"
    return converted_tools


def _create_llm_client(
    provider: LLMProvider,
    model_name: str,
    api_key: Optional[SecretStr],
    base_url: Optional[str] = None,
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
) -> Union[BaseChatModel, Runnable]:
    """
    Internal function to create an LLM client for a specific provider, optionally bound with tools.

    Args:
        provider: The LLM provider to use
        model_name: The model name to use
        api_key: API key as a SecretStr (can be None for OLLAMA/MODAL)
        base_url: Base URL for providers that support it (OLLAMA/MODAL)
        tools: Optional list of tools for function calling
        tool_choice: Optional tool choice strategy ("auto", "required", etc.)

    Returns:
        A configured LangChain LLM client, optionally bound with tools
    """
    if provider == LLMProvider.TOGETHER:
        if not api_key:
            raise ValueError("Together provider requires API_KEY.")
        llm = ChatTogether(
            api_key=api_key,
            model=model_name,
        )

    elif provider == LLMProvider.OPENAI:
        if not api_key:
            raise ValueError("OpenAI provider requires API_KEY.")
        llm = ChatOpenAI(
            api_key=api_key,
            model=model_name,
        )

    elif provider == LLMProvider.OLLAMA:
        if not model_name:
            raise ValueError("Ollama provider requires a model name.")
        llm = ChatOpenAI(
            api_key=api_key or SecretStr("ollama"),
            model=model_name,
            base_url=base_url,
        )

    elif provider == LLMProvider.MODAL:
        if not model_name:
            raise ValueError("Modal provider requires a model name.")
        llm = ChatOpenAI(
            api_key=api_key or SecretStr("modal"),
            model=model_name,
            base_url=base_url,
        )

    elif provider == LLMProvider.GOOGLE:
        if not api_key:
            raise ValueError("Google provider requires API_KEY.")
        llm = ChatGoogleGenerativeAI(
            api_key=api_key,
            model=model_name,
            convert_system_message_to_human=True,
        )

    else:
        raise ValueError(f"No valid LLM provider configured: {provider}")

    if tools:
        if provider == LLMProvider.GOOGLE:
            tools = _convert_tools_for_gemini(tools)
        llm = llm.bind_tools(tools, tool_choice=tool_choice)

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
    model_name: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    api_key: Optional[SecretStr] = None,
    verbose: bool = False,
    run_name: Optional[str] = None,
    metadata: Optional[Dict] = None,
    **kwargs,
) -> AIMessage:
    """
    Make a request to LLM using LangChain with exponential backoff retry logic.

    Args:
        messages: List of LangChain message objects
        tools: Optional list of tools for function calling
        tool_choice: Optional tool choice strategy ("auto", "required", etc.)
        model_name: Optional model name override (defaults to llm settings)
        provider: Optional provider override (defaults to llm settings)
        api_key: Optional API key override (defaults to llm settings)
        verbose: Whether to log debug information
        run_name: Optional name for LangSmith trace run
        metadata: Optional metadata for LangSmith tracing
        **kwargs: Additional keyword arguments for the LLM call

    Returns:
        AIMessage: The response from the LLM as a LangChain AIMessage

    Raises:
        Exception: If the LLM request fails after retries
    """
    try:
        # Validate: if overriding, must specify model_name, provider, AND api_key for custom model call
        has_model = model_name is not None
        has_provider = provider is not None
        has_api_key = api_key is not None
        if has_model or has_provider or has_api_key:
            # If any is specified, all must be specified
            if not (has_model and has_provider and has_api_key):
                raise ValueError(
                    "When overriding async_llm_request defaults, all three parameters must be specified together: "
                    "'model_name', 'provider', and 'api_key'. "
                    "Providing only some would lead to ambiguous behavior."
                )

        if model_name and provider and api_key:
            effective_provider = provider
            effective_model = model_name
            effective_api_key = api_key
        else:
            # Use default settings (provides backward compatibility for existing calls that don't specify these parameters)
            effective_provider = llm_settings.provider
            effective_model = _resolve_model_name()
            effective_api_key = llm_settings.api_key

        # Determine base_url for OLLAMA/MODAL providers
        if effective_provider == LLMProvider.OLLAMA:
            effective_base_url = llm_settings.ollama_base_url
        elif effective_provider == LLMProvider.MODAL:
            effective_base_url = llm_settings.modal_base_url.get_secret_value()
        else:
            effective_base_url = None

        llm = _create_llm_client(
            provider=effective_provider,
            model_name=effective_model,
            api_key=effective_api_key,
            base_url=effective_base_url,
            tools=tools,
            tool_choice=tool_choice,
        )

        if verbose:
            logger.debug(f"Messages sent to LLM API:\n{messages}")

        # Prepare kwargs for LangSmith tracing and additional parameters
        invoke_kwargs = {}
        if llm_settings.langsmith_tracing and (run_name or metadata):
            config = {}
            if run_name:
                config["run_name"] = run_name
            if metadata:
                config["metadata"] = metadata
            invoke_kwargs["config"] = config

        # Merge any additional kwargs (like temperature, max_tokens, etc.) otherwise they dont get passed to the LLM call
        invoke_kwargs.update(kwargs)

        # Make the async call while tracking metrics
        with LLMCallTracker(effective_provider.value, effective_model):
            response = await llm.ainvoke(messages, **invoke_kwargs)
            return cast(AIMessage, response)

    except Exception as e:
        logger.error(f"LLM request failed: {str(e)}")
        raise
