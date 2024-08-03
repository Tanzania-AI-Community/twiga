import json
import logging
import os
import time
from collections import deque
from typing import Any, Tuple

import openai
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
from openai.types.beta import Thread

# from app.tools.generate_exercise import exercise_generator
from db.utils import check_if_thread_exists, store_message, store_thread

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("TWIGA_OPENAI_ASSISTANT_ID")
OPENAI_ORG = os.getenv("OPENAI_ORG")
client = AsyncOpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORG)

logger = logging.getLogger(__name__)

message_queue = deque()


async def _handle_tool_call(tool: Any, run: str, func: callable, verbose: bool = False):
    # Arguments returned by llm
    raw_arguments = tool.function.arguments

    # response from function calling
    response_message = ""
    try:
        # Parse the raw arguments
        arguments = json.loads(raw_arguments)

        # Ensure arguments are in dictionary format
        if not isinstance(arguments, dict):
            raise ValueError("Parsed arguments are not in dictionary format.")

        # Call the function with the unpacked arguments
        response_message = await func(**arguments)
    except json.JSONDecodeError as e:
        response_message = "JSONDecodeError: " + str(e), 400
    except KeyError as e:
        response_message = "Missing required argument: {e}", 400
    except Exception as e:
        response_message = f"An unexpected error occurred: {str(e)}", 500
    finally:
        if verbose:
            logger.info(
                f"Tool call: {tool.function.name}({str(tool.function.arguments)})"
            )
            logger.info(f"Returned: {response_message}")

        # Send the response back to the function calling tool
        run = await client.beta.threads.runs.submit_tool_outputs(
            thread_id=run.thread_id,
            run_id=run.id,
            tool_outputs=[
                {
                    "tool_call_id": tool.id,
                    "output": response_message,  # pass the response from your function to openai, so it knows if everything worked fine, or happens with me a lot, some arguments was invalid or filled with a placeholder.
                }
            ],
        )


async def run_assistant(wa_id: str, thread: Thread, verbose: bool = False) -> str:

    # Retrieve the Assistant
    assistant = await client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)

    # Run the assistant
    run = await client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id,
    )

    # Wait for completion
    while run.status != "completed":
        time.sleep(0.5)  # Be nice to the API
        logger.info(f"🏃‍♂️ Run status: {run.status}")
        # Retrieve the latest run status
        run = await client.beta.threads.runs.retrieve(
            thread_id=thread.id, run_id=run.id
        )

        if run.status == "requires_action":
            logger.info("🔧 Action required")

            for tool in run.required_action.submit_tool_outputs.tool_calls:

                logger.info(f"🛠 Tool call: {tool.function.name}")

                if tool.function.name == "generate_exercise":
                    # # Send a message to the user that we're generating an exercise
                    # response = format_text_for_whatsapp("🔄 Generating exercise...")
                    # data = get_text_message_input(
                    #     current_app.config["RECIPIENT_WAID"], response
                    # )
                    # store_message(wa_id, "🔄 Generating exercise...", role="twiga")
                    # await send_message(data)

                    # await _handle_tool_call(
                    #     tool, run, exercise_generator, verbose=verbose
                    # )
                    pass

        # RUN STATUS: EXPIRED | FAILED | CANCELLED | INCOMPLETE
        if run.status in ["expired", "failed", "cancelled", "incomplete"]:
            return json.dumps(
                {
                    "error": f"OpenAI assistant ended the run {run.id} with the status {run.status}"
                }
            )

    logger.info(f"🏁 Run completed")

    messages = await client.beta.threads.messages.list(thread_id=thread.id)

    return (
        messages.data[0].content[0].text.value
    )  # Returns the most recent message generated by the assistant


async def generate_response(message_body: str, wa_id: str, name: str) -> str:
    # Check if there is already a thread_id for the wa_id
    thread_id = dict(check_if_thread_exists(wa_id)).get("thread", None)

    # If a thread doesn't exist, create one and store it
    if thread_id is None:
        thread = await client.beta.threads.create()
        logger.info(f"Creating new thread for {name} with id {thread.id}")
        store_thread(wa_id, thread.id)
    else:  # Otherwise, retrieve the existing thread
        logger.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")
        thread = await client.beta.threads.retrieve(str(thread_id))

    try:
        # Add message to the relevant assistant thread
        await client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message_body,
        )

        # Run the assistant and get the new message
        new_message = await run_assistant(wa_id, thread, verbose=True)

        return new_message

    except openai.BadRequestError as e:
        logger.error(f"Error sending message to OpenAI: {e}")
        return None
