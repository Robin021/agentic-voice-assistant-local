import re
import regex
import numpy as np
import asyncio
from fastrtc.utils import audio_to_bytes

from constants import AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME
from .router import router


def normalize_text(text: str) -> str:
    """
    Normalize and clean text for use in Text-to-Speech (TTS) synthesis.

    This function removes characters that are unsuitable for speech,
    such as emojis, decorative symbols, and control characters.

    Characters retained:
    - Letters from all languages (Unicode category: L)
    - Numbers (N)
    - Punctuation marks (P)
    - Math symbols (Sm), e.g., + = ≈ × ÷
    - Currency symbols (Sc), e.g., $ ¥ € ₩
    - Whitespace (spaces, tabs, newlines, etc.)

    Steps:
    1. Remove all characters not in the allowed categories.
    2. Replace newlines and tabs with a single space.
    3. Collapse consecutive whitespace characters into a single space.
    4. Trim leading and trailing whitespace.

    Args:
        text (str): Input text string from LLM or other sources.

    Returns:
        str: Cleaned and normalized text suitable for TTS.
    """
    # Step 1: remove all html tags.
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-z]+;", "", text)

    allowed_punctuation = "。，！？：.,!?:/@()[]+-*/%"
    # Step 2: Remove all non-speakable characters
    text = regex.sub(
        rf"[^\p{{L}}\p{{N}}\p{{Sm}}\p{{Sc}}\s{regex.escape(allowed_punctuation)}]",
        "",
        text,
    )

    # Step 3: Normalize all whitespace (including \n, \t) to a single space
    text = regex.sub(r"\s+", " ", text).strip()

    return text


async def atranscription(audio: tuple[int, np.ndarray]) -> str:
    transcription = await router.atranscription(
        model=AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
        file=audio_to_bytes(audio),
        stream=False,
    )
    return transcription.text.strip()


async def wait_for_event(event: asyncio.Event, timeout: float):
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        pass
