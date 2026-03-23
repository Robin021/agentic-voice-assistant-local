import asyncio
import tiktoken
import threading
from typing import AsyncGenerator, Iterator
from litellm import CustomStreamWrapper

from server.router import router
from schemas import ChatMessageHistory, HumanMessage, MessageEvent
from prompts.template import apply_prompt_template
from constants import CONTEXT_RELEVANCE_MODEL_NAME, LEXICAL_PATTERN


def count_tokens(text: str) -> int:
    """Count the approximate number of tokens in a text string using GPT-4's tokenizer.

    Args:
        text: Input string to be tokenized

    Returns:
        Integer count of tokens in the text
    """
    enc = tiktoken.encoding_for_model("gpt-4")  # Get GPT-4's tokenizer
    return len(enc.encode(text))  # Encode text and count tokens


def count_lexical_chars(text: str) -> int:
    """Count the number of human-readable characters in the text.

    Args:
        text: Input text to analyze

    Returns:
        int: Count of lexical characters (non-whitespace, non-punctuation, non-symbols)
    """
    return count_tokens("".join(LEXICAL_PATTERN.findall(text)))


def split_at_punctuation(text: str) -> tuple[str, str | None]:
    """Split text at the first occurrence of any punctuation mark.

    Args:
        text: Input string to be split

    Returns:
        Tuple containing:
        - First part (including the punctuation)
        - Remaining text or None if no punctuation found
    """
    # Tuple of common punctuation marks including:
    # - ASCII punctuation (,.!? etc)
    # - Unicode full-width punctuation (，。；：！？)
    punctuation = (
        # ",",
        ".",
        ";",
        # ":",
        "!",
        "?",
        # chr(65292),  # Full-width comma (，)
        chr(12290),  # Full-width period (。)
        chr(65307),  # Full-width semicolon (；)
        # chr(65306),  # Full-width colon (：)
        chr(65281),  # Full-width exclamation (！)
        chr(65311),  # Full-width question mark (？)
    )

    # Iterate through text to find first punctuation
    for idx, char in enumerate(text):
        if char in punctuation:
            # Split at punctuation position
            return text[: idx + 1], text[idx + 1 :]

    # Return original text if no punctuation found
    return text, None


def split_sentences(
    response: CustomStreamWrapper, stop_event: threading.Event = threading.Event()
) -> Iterator[MessageEvent]:
    """Split text at the first occurrence of any punctuation mark.

    Args:
        text: Input string to be split

    Returns:
        Tuple containing:
        - First part (including the punctuation)
        - Remaining text or None if no punctuation found
    """
    chunk = ""
    for x in response:
        if stop_event.is_set():
            break

        text = x.choices[0].delta.content
        if not text:
            continue

        yield MessageEvent(is_partial=True, content=text)

        # Split content at punctuation boundaries
        a, b = split_at_punctuation(text=text)
        chunk += a

        # Yield complete message if buffer reaches token threshold
        if count_tokens(chunk) >= 20 and b is not None:
            yield MessageEvent(is_partial=False, content=chunk)
            chunk = b
        else:
            chunk += b or ""

    # Yield any remaining content in buffer
    if chunk:
        yield MessageEvent(
            is_partial=count_lexical_chars(text=chunk) == 0, content=chunk
        )


async def async_split_sentences(
    response: CustomStreamWrapper, stop_event: asyncio.Event = asyncio.Event()
) -> AsyncGenerator[MessageEvent, None]:
    """Split text at the first occurrence of any punctuation mark.

    Args:
        text: Input string to be split

    Returns:
        Tuple containing:
        - First part (including the punctuation)
        - Remaining text or None if no punctuation found
    """
    chunk = ""
    async for x in response:
        if stop_event.is_set():
            break

        text = x.choices[0].delta.content
        if not text:
            continue

        yield MessageEvent(is_partial=True, content=text)

        # Split content at punctuation boundaries
        a, b = split_at_punctuation(text=text)
        chunk += a

        # Yield complete message if buffer reaches token threshold
        if count_tokens(chunk) >= 20 and b is not None:
            yield MessageEvent(is_partial=False, content=chunk)
            chunk = b
        else:
            chunk += b or ""

    # Yield any remaining content in buffer
    if chunk:
        yield MessageEvent(
            is_partial=count_lexical_chars(text=chunk) == 0, content=chunk
        )


def context_relevance_classifier(
    query: str,
    conversation: ChatMessageHistory,
    history_num: int = 6,
) -> bool:
    user_template = """Here is the conversation context: 
{histories}

The new user query is `{query}`

Please evaluate according to the rules and respond directly with [yes/no]."""
    messages = [
        HumanMessage(
            content=user_template.format(
                histories="\n".join(
                    [
                        f"{msg.role}: {msg.content}"
                        for msg in conversation.messages[-history_num:]
                    ]
                ),
                query=query,
            )
        )
    ]
    response = router.completion(
        model=CONTEXT_RELEVANCE_MODEL_NAME,
        messages=apply_prompt_template(
            prompt_name="context_relevance_classifier",
            messages=messages,
        ),
        stream=False,
    )
    result: str = response.choices[0].message.content.strip().lower()  # type: ignore

    return "yes" in result
