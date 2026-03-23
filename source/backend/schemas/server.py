import os
import time
import datetime
from uuid import uuid4
from enum import Enum
from numpy import ndarray
from pydantic import BaseModel, UUID4, ConfigDict, Field
from pynamodb.models import Model
from pynamodb.attributes import (
    UnicodeAttribute,
    MapAttribute,
    ListAttribute,
)
from pynamodb_attributes import TimestampAttribute, UnicodeEnumAttribute
from opentelemetry.sdk.trace import Event as OTelEvent
from opentelemetry.trace import Span
from opentelemetry.util.types import Attributes

from logger import logger
from constants import DEFAULT_AWS_REGION_NAME, DEFAULT_TABLE_NAME


class EventName(Enum):
    USER_STARTED_TALKING = "user_started_talking"
    USER_STOPPED_TALKING = "user_stopped_talking"
    USER_INTERRUPTED = "user_interrupted"
    PIPELINE_ACTIVATED = "pipeline_activated"
    TRANSCRIPTION_COMPLETED = "transcription_completed"
    FIRST_LLM_TOKEN_GENERATED = "first_llm_token_generated"
    FIRST_LLM_SENTENCE_GENERATED = "first_llm_sentence_generated"
    FIRST_AUDIO_CHUNK_SENT = "first_audio_chunk_sent"


class Opcode(Enum):
    """Opcode types indicating the kind of event payload.

    - TEXT: Represents a text-based message (e.g., user query or LLM output).
    - AUDIO: Represents an audio chunk (e.g., microphone input or TTS output).
    - CONTINUATION: Indicates this event continues a previously started message.
    """

    TEXT = "Text"
    AUDIO = "Audio"
    CLOSE = "Close"


class Event(BaseModel):
    """Base structure for a single event in a stream (audio/text/etc)."""

    event_id: UUID4 = Field(
        default_factory=uuid4,
        description="Unique identifier for the event instance.",
    )
    span: Span | None = Field(
        default=None,
        description="OpenTelemetry span for this event. Used for tracing and debugging.",
    )
    opcode: Opcode = Field(
        ...,
        description="Operation code indicating the type of data this event carries.",
    )
    transcript: str = Field(
        default="",
        description="Transcript of the event.",
    )
    data: ndarray | str | None = Field(
        default=None,
        description="Payload of the event. Can be audio array or a text string depending on opcode.",
    )
    fin: bool = Field(
        default=False,
        description="Final flag. If True, indicates this is the last chunk of the message.",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def end(self):
        if self.span:
            self.span.end()

    def add_event(
        self, name: str, timestamp: int | None = None, attributes: Attributes = None
    ) -> None:
        if self.span:
            self.span.add_event(
                name=name, timestamp=timestamp or time.time_ns(), attributes=attributes
            )

    @property
    def events(self) -> list[OTelEvent]:
        if not self.span:
            return []
        return self.span.events  # type: ignore


class MetricName(Enum):
    SPEECH_DURATION = "Speech Duration"
    INTERRUPTION_DELAY = "Interruption Delay (Speech Start)"
    PIPELINE_START_DELAY = "Pipeline Start Delay (Speech End)"
    SPEECH_TO_TEXT_DELAY = "SPEECH-TO-TEXT Delay (Pipeline Start)"
    LLM_FIRST_TOKEN_DELAY = "LLM First Token Delay (Pipeline Start)"
    LLM_FIRST_SENTENCE_DELAY = "LLM First Sentence Delay (Pipeline Start)"
    TTS_FIRST_AUDIO_DELAY_FROM_PIPELINE_START = "TTS First Audio Delay (Pipeline Start)"
    TTS_FIRST_AUDIO_DELAY_FROM_SPEECH_END = "TTS First Audio Delay (Speech End)"


class Metric(BaseModel):
    name: MetricName
    value: float | None = Field(
        default=None,
        description="The value of the metric, in nanoseconds. If the metric is not applicable, the value will be None.",
    )

    def to_text(self):
        return (
            f"{self.name.value}: {self.value / 1_000_000_000:.3f}s"
            if self.value is not None
            else f"{self.name.value}: N/A"
        )


class PipelineLatencyMetrics(BaseModel):
    """Tracks latency metrics across the audio processing pipeline."""

    transcript: str = Field(default="", description="Transcript of the user query")
    speech_detection_start_time: float | None = Field(
        default=None,
        description="Timestamp when user speech is first detected",
    )
    speech_detection_end_time: float | None = Field(
        default=None, description="Timestamp when user speech ends"
    )
    interruption_trigger_time: float | None = Field(
        default=None,
        description="Timestamp when user interruption is detected",
    )
    pipeline_activation_time: float | None = Field(
        default=None,
        description="Timestamp when audio processing pipeline starts",
    )
    speech_to_text_completion_time: float | None = Field(
        default=None,
        description="Timestamp when audio transcription to text completes",
    )
    first_llm_token_time: float | None = Field(
        default=None,
        description="Timestamp when first LLM response token is received",
    )
    first_llm_sentence_time: float | None = Field(
        default=None,
        description="Timestamp when first complete LLM response sentence is ready",
    )
    first_audio_chunk_time: float | None = Field(
        default=None,
        description="Timestamp when first TTS audio chunk is sent to client",
    )

    def update_from_events(self, events: list[OTelEvent]):
        for event in events:
            if event.name == EventName.USER_STARTED_TALKING.value:
                self.speech_detection_start_time = event.timestamp
            elif (
                event.name == EventName.USER_STOPPED_TALKING.value
                and not self.speech_detection_end_time
            ):
                self.speech_detection_end_time = event.timestamp
            elif (
                event.name == EventName.USER_INTERRUPTED.value
                and not self.interruption_trigger_time
            ):
                self.interruption_trigger_time = event.timestamp
            elif (
                event.name == EventName.PIPELINE_ACTIVATED.value
                and not self.pipeline_activation_time
            ):
                self.pipeline_activation_time = event.timestamp
            elif (
                event.name == EventName.TRANSCRIPTION_COMPLETED.value
                and not self.speech_to_text_completion_time
            ):
                self.speech_to_text_completion_time = event.timestamp
            elif (
                event.name == EventName.FIRST_LLM_TOKEN_GENERATED.value
                and not self.first_llm_token_time
            ):
                self.first_llm_token_time = event.timestamp
            elif (
                event.name == EventName.FIRST_LLM_SENTENCE_GENERATED.value
                and not self.first_llm_sentence_time
            ):
                self.first_llm_sentence_time = event.timestamp
            elif (
                event.name == EventName.FIRST_AUDIO_CHUNK_SENT.value
                and not self.first_audio_chunk_time
            ):
                self.first_audio_chunk_time = event.timestamp

    def calculate_time_delta(
        self, end: float | None, start: float | None
    ) -> float | None:
        """Calculates the duration between two timestamps with safety checks.

        Args:
            end: The later timestamp in nanoseconds (Unix time).
            start: The earlier timestamp in nanoseconds (Unix time).

        Returns:
            The duration in nanoseconds rounded to specified precision,
            or None if either timestamp is missing/invalid.

        Example:
            >>> self.calculate_time_delta(1700000001.234, 1700000000.0)
            1.234
            >>> self.calculate_time_delta(None, 1700000000.0)
            None
        """
        return round(end - start) if end is not None and start is not None else None

    def log_latency_metrics(self):
        """Compute and log latency metrics from speech start to various stages."""
        metrics = [
            Metric(
                name=MetricName.SPEECH_DURATION,
                value=self.calculate_time_delta(
                    self.speech_detection_end_time, self.speech_detection_start_time
                ),
            ),
            Metric(
                name=MetricName.INTERRUPTION_DELAY,
                value=self.calculate_time_delta(
                    self.interruption_trigger_time, self.speech_detection_start_time
                ),
            ),
            Metric(
                name=MetricName.PIPELINE_START_DELAY,
                value=self.calculate_time_delta(
                    self.pipeline_activation_time, self.speech_detection_end_time
                ),
            ),
            Metric(
                name=MetricName.SPEECH_TO_TEXT_DELAY,
                value=self.calculate_time_delta(
                    self.speech_to_text_completion_time, self.pipeline_activation_time
                ),
            ),
            Metric(
                name=MetricName.LLM_FIRST_TOKEN_DELAY,
                value=self.calculate_time_delta(
                    self.first_llm_token_time, self.pipeline_activation_time
                ),
            ),
            Metric(
                name=MetricName.LLM_FIRST_SENTENCE_DELAY,
                value=self.calculate_time_delta(
                    self.first_llm_sentence_time, self.pipeline_activation_time
                ),
            ),
            Metric(
                name=MetricName.TTS_FIRST_AUDIO_DELAY_FROM_PIPELINE_START,
                value=self.calculate_time_delta(
                    self.first_audio_chunk_time, self.pipeline_activation_time
                ),
            ),
            Metric(
                name=MetricName.TTS_FIRST_AUDIO_DELAY_FROM_SPEECH_END,
                value=self.calculate_time_delta(
                    self.first_audio_chunk_time, self.speech_detection_end_time
                ),
            ),
        ]

        logger.info(
            f"[Pipeline Latency Metrics] Transcription: {self.transcript}, {', '.join([x.to_text() for x in metrics])}"
        )


class ScenarioItem(MapAttribute):
    name = UnicodeAttribute(null=False)
    prompt = UnicodeAttribute(null=False)
    description = UnicodeAttribute(null=True)
    createdAt = TimestampAttribute(default_for_new=datetime.datetime.now(datetime.UTC))
    updatedAt = TimestampAttribute(default=datetime.datetime.now(datetime.UTC))


class Scenarios(Model):
    class Meta:
        table_name = os.environ.get("TABLE_NAME", DEFAULT_TABLE_NAME)
        region = os.environ.get("AWS_REGION_NAME", DEFAULT_AWS_REGION_NAME)

    pk = UnicodeAttribute(hash_key=True, default="SCENARIO")
    sk = UnicodeAttribute(range_key=True, default="SCENARIO")

    scenarios = ListAttribute(of=ScenarioItem, default=())

    createdAt = TimestampAttribute(default_for_new=datetime.datetime.now(datetime.UTC))
    updatedAt = TimestampAttribute(default=datetime.datetime.now(datetime.UTC))


class User(Model):
    class Meta:
        table_name = os.environ.get("TABLE_NAME", DEFAULT_TABLE_NAME)
        region = os.environ.get("AWS_REGION_NAME", DEFAULT_AWS_REGION_NAME)

    pk = UnicodeAttribute(hash_key=True, default="USER")
    sk = UnicodeAttribute(range_key=True, default="USER")

    username = UnicodeAttribute(null=False)
    gender = UnicodeAttribute(null=False)

    createdAt = TimestampAttribute(default_for_new=datetime.datetime.now(datetime.UTC))
    updatedAt = TimestampAttribute(default=datetime.datetime.now(datetime.UTC))
