from enum import Enum
from pydantic import BaseModel, Field


class Language(Enum):
    CHINESE = "chinese"
    ENGLISH = "english"
    JAPANESE = "japanese"
    KOREAN = "korean"


class VadModel(Enum):
    SILERO = "Silero"
    HUMMING_AWARE = "Humming-Aware"


class VadMode(Enum):
    SILERO_ONLY = "silero_only"
    WEBRTCVAD_ONLY = "webrtcvad_only"
    HYBRID = "hybrid"


class VadOptions(BaseModel):
    """VAD options.

    Attributes:
      model: Silero or Humming-Aware.
      threshold: Speech threshold. Silero VAD outputs speech probabilities for each audio chunk,
        probabilities ABOVE this value are considered as SPEECH. It is better to tune this
        parameter for each dataset separately, but "lazy" 0.5 is pretty good for most datasets.
      min_speech_duration_ms: Final speech chunks shorter min_speech_duration_ms are thrown out.
      max_speech_duration_s: Maximum duration of speech chunks in seconds. Chunks longer
        than max_speech_duration_s will be split at the timestamp of the last silence that
        lasts more than 100ms (if any), to prevent aggressive cutting. Otherwise, they will be
        split aggressively just before max_speech_duration_s.
      min_silence_duration_ms: In the end of each speech chunk wait for min_silence_duration_ms
        before separating it
      window_size_samples: Audio chunks of window_size_samples size are fed to the silero VAD model.
        WARNING! Silero VAD models were trained using 512, 1024, 1536 samples for 16000 sample rate.
        Values other than these may affect model performance!!
      speech_pad_ms: Final speech chunks are padded by speech_pad_ms each side
      webrtcvad_sensitivity:  Sensitivity for the WebRTC Voice Activity Detection engine ranging from 0
        (least aggressive / most sensitive) to 3 (most aggressive, least sensitive). Default is 3.
      webrtcvad_voiced_frame_threshold: Minimum ratio of frames that must be detected as voiced within the sliding
        window to trigger speech segment collection (0.0 to 1.0). Defaults to 0.1 (10%). Higher values
        reduce false positives but may clip speech beginnings/endings.
      noise_suppression_enabled: Whether to enable background noise suppression.
    """

    mode: VadMode = VadMode.HYBRID
    model: VadModel = VadModel.SILERO
    threshold: float = 0.5
    min_speech_duration_ms: int = 250
    max_speech_duration_s: float = float("inf")
    min_silence_duration_ms: int = 2000
    window_size_samples: int = 1024
    speech_pad_ms: int = 400
    webrtcvad_sensitivity: int = 3
    webrtcvad_voiced_frame_threshold: float = 0.1
    noise_suppression_enabled: bool = False


class PauseDetectionAlgorithm(BaseModel):
    """Configuration parameters for pause detection in speech streams."""

    audio_chunk_duration: float = Field(
        default=0.6, description="Duration of audio chunks to process (in seconds)"
    )
    started_talking_threshold: float = Field(
        default=0.2, description="Threshold to determine when speech begins"
    )
    speech_threshold: float = Field(
        default=0.1, description="Threshold to detect ongoing speech"
    )
    semantic_check_threshold: float = Field(
        default=1.0,
        description=(
            "Duration threshold (seconds) for semantic analysis. "
            "Short segments (< threshold) are verified for semantic content, "
            "long segments bypass verification."
        ),
    )
    min_endpointing_delay: float = Field(
        default=0.5,
        description=(
            "Minimum time-in-seconds the agent must wait after a potential "
            "end-of-utterance signal (from VAD model) before it declares the "
            "user’s turn complete. Default `0.5` s."
        ),
    )
    max_endpointing_delay: float = Field(
        default=2.0,
        description=(
            "Maximum time-in-seconds the agent will wait before terminating the turn. Default `2.0` s."
        ),
    )
    min_interruption_duration: float = Field(
        default=0.5,
        description=(
            "Minimum speech length (s) to register as an interruption. Default `0.5` s."
        ),
    )
    min_interruption_tokens: int = Field(
        default=1,
        description=(
            "Minimum number of tokens to consider an interruption. Default `1`."
        ),
    )
