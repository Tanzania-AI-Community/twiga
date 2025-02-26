from typing import List
import json
import logging

import tiktoken
import backoff
import openai
from openai.types.chat import ChatCompletion

from app.config import llm_settings

# Set up basic logging configuration
logger = logging.getLogger(__name__)

if llm_settings.ai_provider == "together" and llm_settings.llm_api_key:
    llm_client = openai.AsyncOpenAI(
        base_url="https://api.together.xyz/v1",
        api_key=llm_settings.llm_api_key.get_secret_value(),
    )
elif llm_settings.ai_provider == "openai" and llm_settings.llm_api_key:
    llm_client = openai.AsyncOpenAI(api_key=llm_settings.llm_api_key.get_secret_value())


@backoff.on_exception(backoff.expo, openai.RateLimitError, max_tries=7, max_time=45)
async def async_llm_request(
    verbose: bool = False,
    **params,
) -> ChatCompletion:
    """
    Make a request to Together AI's API with exponential backoff retry logic.

    Args:
        llm: Model identifier to use
        api_key: Together AI API key
        verbose: Whether to log detailed request information
        **params: Additional parameters to pass to the API

    Returns:
        ChatCompletion: Response from the API

    Raises:
        TogetherRateLimitError: When rate limit is exceeded
        TogetherAPIError: For other API-related errors
    """
    try:
        assert llm_client is not None, "LLM client is not initialized"
        # Print messages if the flag is True
        
        if verbose:
            messages = params.get("messages", None)
            logger.info(f"Messages sent to LLM API:\n{json.dumps(messages, indent=2)}")  

        completion = await llm_client.chat.completions.create(**params)

        return completion
    except openai.RateLimitError:
        raise
    except Exception as e:
        raise Exception(f"Failed to retrieve completion: {str(e)}")
