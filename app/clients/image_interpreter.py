"""Image-to-text only; the existing agent still chooses and executes tools."""

import asyncio
import base64
import json
import logging
from time import monotonic

import httpx
from langsmith import tracing_context
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import ValidationError

from app.config import Prompt, image_input_settings
from app.models.image_models import (
    DownloadedImage,
    ImageInputError,
    ImageInterpretation,
)
from app.monitoring.metrics import record_llm_call
from app.utils.logging_utils import private_media_logging
from app.utils.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


class ImageInterpreter:
    async def interpret(
        self, image: DownloadedImage, caption: str
    ) -> ImageInterpretation:
        config = image_input_settings
        if not config.image_input_enabled:
            raise ImageInputError("image_disabled")

        started = monotonic()
        outcome = "failed"
        try:
            async with httpx.AsyncClient() as http_client:
                result = await self._extract(image, caption, http_client)
                outcome = result.readability
                return result
        finally:
            elapsed = monotonic() - started
            record_llm_call(
                "vision",
                config.vision_model,
                "error" if outcome == "failed" else "success",
                elapsed,
            )
            logger.info(
                "Image stage=vision result=%s model=%s elapsed_ms=%d",
                outcome,
                config.vision_model,
                elapsed * 1000,
            )

    async def _extract(
        self, image: DownloadedImage, caption: str, http_client: httpx.AsyncClient
    ) -> ImageInterpretation:
        config = image_input_settings
        # Explicit settings keep vision independent of the main chat provider.
        # Disable SDK retries: the loop below owns the single retry budget.
        # Use the SDK directly: LangChain callbacks/caches must not receive photos.
        client = AsyncOpenAI(
            base_url=config.vision_base_url,
            api_key=config.vision_api_key.get_secret_value(),
            timeout=config.vision_timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )
        encoded = base64.b64encode(image.data).decode("ascii")
        messages = [
            {
                "role": "system",
                "content": prompt_manager.get_active_prompt(
                    Prompt.IMAGE_INTERPRETER_SYSTEM
                )
                + "\nJSON schema:\n"
                + json.dumps(ImageInterpretation.model_json_schema()),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Teacher instruction (untrusted): "
                        + (caption or "none"),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image.mime_type};base64,{encoded}"
                        },
                    },
                ],
            },
        ]
        # Image payloads must not enter LangSmith or SDK diagnostic logs.
        with tracing_context(enabled=False, parent=False), private_media_logging():
            for attempt in range(2):
                try:
                    async with asyncio.timeout(config.vision_timeout_seconds):
                        response = await client.chat.completions.create(
                            model=config.vision_model,
                            messages=messages,
                            temperature=0,
                            max_tokens=8192,
                            response_format={"type": "json_object"},
                        )
                    if not response.choices:
                        raise ValueError("Expected a completion")
                    choice = response.choices[0]
                    if choice.finish_reason == "length":
                        raise ImageInputError("image_too_complex")
                    if not isinstance(choice.message.content, str):
                        raise ValueError("Expected JSON text")
                    result = ImageInterpretation.model_validate_json(
                        choice.message.content
                    )
                    return result
                except APIStatusError as exc:
                    if attempt == 0 and (
                        exc.status_code == 429 or exc.status_code >= 500
                    ):
                        continue
                    raise ImageInputError() from None
                except (APIConnectionError, TimeoutError, ValidationError, ValueError):
                    if attempt == 0:
                        continue
                    raise ImageInputError() from None
        raise ImageInputError()


image_interpreter = ImageInterpreter()
