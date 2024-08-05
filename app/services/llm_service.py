import json
import logging
import os
from typing import Literal

import backoff
import openai
from openai.types.chat import ChatCompletion
import groq
from groq import AsyncGroq, Groq

from app.config import llm_settings
from app.utils.llm_utils import num_tokens_from_messages

# Set up basic logging configuration
logger = logging.getLogger(__name__)

groq_client = AsyncGroq(api_key=llm_settings.groq_api_key.get_secret_value())
openai_client = openai.AsyncOpenAI(
    api_key=llm_settings.openai_api_key.get_secret_value(),
    organization=llm_settings.openai_org,
)


@backoff.on_exception(backoff.expo, openai.RateLimitError, max_tries=10, max_time=300)
async def async_openai_request(verbose: bool = False, **params) -> ChatCompletion:
    try:
        # Print messages if the flag is True
        if verbose:
            messages = params.get("messages", None)
            logger.info(
                f"Messages sent to OpenAI API:\n{json.dumps(messages, indent=2)}"
            )
            logger.info(
                f"Number of OpenAI-equivalent tokens in the payload:\n{num_tokens_from_messages(messages)}"
            )

        completion = await openai_client.chat.completions.create(**params)

        return completion
    except openai.RateLimitError as e:
        raise
    except Exception as e:
        raise Exception(f"Failed to retrieve completion: {str(e)}")


@backoff.on_exception(backoff.expo, groq.RateLimitError, max_tries=10, max_time=300)
async def async_groq_request(
    llm: Literal[
        "llama3-8b-8192", "llama3-70b-8192", "mixtral-8x7b-32768", "gemma-7b-it"
    ],
    verbose: bool = False,
    **params,
):
    try:
        # Print messages if the flag is True
        if verbose:
            messages = params.get("messages", None)
            logger.info(f"Messages sent to Groq API:\n{json.dumps(messages, indent=2)}")
            logger.info(
                f"Number of OpenAI-equivalent tokens in the payload:\n{num_tokens_from_messages(messages)}"
            )

        full_params = {"model": llm, **params}

        completion = await groq_client.chat.completions.create(**full_params)

        return completion
    except groq.RateLimitError as e:
        # Log and re-raise rate limit errors
        logger.error(f"Rate limit error: {e}")
        raise
    except Exception as e:
        # Log and re-raise unexpected errors
        logger.error(f"Unexpected error: {e}")
        raise
