from typing import List

import tiktoken


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
