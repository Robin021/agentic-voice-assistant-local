from pysrt import SubRipFile, SubRipItem
from enum import Enum
from typing import Literal, TypedDict
from pydantic import BaseModel, Field


class AudioChunk(TypedDict):
    start: int
    end: int


class Language(Enum):
    AUTO = "auto"
    CHINESE = "zh"
    ENGLISH = "en"
    CANTONESE = "yue"
    JAPANESE = "ja"
    KOREAN = "ko"


class ResponseFormat(Enum):
    JSON = "json"
    TEXT = "text"
    SRT = "srt"
    VERBOSE_JSON = "verbose_json"


class ChunkingStrategy(BaseModel):
    type: Literal["server_vad"] = "server_vad"
    prefix_padding_ms: int = Field(
        default=300,
        description="Amount of audio to include before the VAD detected speech (in milliseconds).",
    )
    silence_duration_ms: int = Field(
        default=200,
        description="Duration of silence to detect speech stop (in milliseconds). With shorter values the model will respond more quickly, but may jump in on short pauses from the user.",
    )

    threshold: float = Field(
        default=0.5,
        description="Sensitivity threshold (0.0 to 1.0) for voice activity detection. A higher threshold will require louder audio to activate the model, and thus might perform better in noisy environments.",
    )
    min_speech_duration_ms: int = Field(
        default=250,
        description="Final speech chunks shorter min_speech_duration_ms are thrown out.",
    )
    max_speech_duration_s: float = Field(
        default=float("inf"),
        description=(
            "Maximum duration of speech chunks in seconds. Chunks longer"
            "than max_speech_duration_s will be split at the timestamp of the last silence that"
            "lasts more than 100ms (if any), to prevent aggressive cutting. Otherwise, they will be"
            "split aggressively just before max_speech_duration_s."
        ),
    )


class TranscriptionSegment(BaseModel):
    id: int = Field(
        ...,
        description="Unique identifier of the segment.",
    )
    """The index of the segment in the transcription."""

    start: int = Field(
        ...,
        description="Start time of the segment in seconds.",
    )
    end: int = Field(
        ...,
        description="End time of the segment in seconds.",
    )
    text: str = Field(..., description="Text content of the segment.")


class BaseTranscription(BaseModel):
    segments: list[TranscriptionSegment] = Field(
        default=[],
        description="Segments of the transcribed text and their corresponding details.",
    )

    @property
    def json(self) -> str:
        """Convert the transcription to a JSON string."""
        return self.model_dump_json()

    @property
    def srt(self) -> str:
        """Convert the transcription to a SubRip Subtitle (SRT) format."""
        text = ""
        for segment in self.segments:
            text += f"{str(SubRipItem(index=segment.id, start=segment.start, end=segment.end, text=segment.text,))}\n"

        return text


class Transcription(BaseTranscription):
    text: str
    """The transcribed text."""


class TranscriptionTextDeltaEvent(BaseTranscription):
    delta: str
    """The text delta that was additionally transcribed."""

    type: Literal["transcript.text.delta"] = "transcript.text.delta"
    """The type of the event. Always `transcript.text.delta`."""

    @property
    def text(self) -> str:
        return self.delta

    @text.setter
    def text(self, value: str) -> None:
        self.delta = value


class TranscriptionTextDoneEvent(Transcription):

    type: Literal["transcript.text.done"] = "transcript.text.done"
    """The type of the event. Always `transcript.text.done`."""
