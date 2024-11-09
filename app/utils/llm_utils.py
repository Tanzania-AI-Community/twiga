from typing import List, Literal
import json
import logging

import tiktoken
import backoff
import openai
from openai.types.chat import ChatCompletion

from app.config import llm_settings

# Set up basic logging configuration
logger = logging.getLogger(__name__)

llm_client = openai.AsyncOpenAI(
    base_url="https://api.together.xyz/v1",
    api_key=llm_settings.llm_api_key.get_secret_value(),
)


def num_tokens_from_string(string: str, encoding_name: str = "cl100k_base") -> int:
    """This returns the number of OpenAI-equivalent tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def num_tokens_from_messages(
    messages: List[dict], encoding_name: str = "cl100k_base"
) -> int:
    """Return the number of tokens used by a list of messages in the format sent to the OpenAI or Groq API."""
    tokens_per_message = 3
    tokens_per_name = 1

    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += num_tokens_from_string(value, encoding_name)
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens


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
        # Print messages if the flag is True
        if verbose:
            messages = params.get("messages", None)
            logger.info(f"Messages sent to LLM API:\n{json.dumps(messages, indent=2)}")
            logger.info(
                f"Number of OpenAI-equivalent tokens in the payload:\n{num_tokens_from_messages(messages)}"
            )

        completion = await llm_client.chat.completions.create(**params)

        return completion
    except openai.RateLimitError as e:
        raise
    except Exception as e:
        raise Exception(f"Failed to retrieve completion: {str(e)}")
