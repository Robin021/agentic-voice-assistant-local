import os
import json
import yaml
import boto3
import httpx
import numpy as np
import logging
import librosa
from numpy.typing import NDArray
from typing import Literal, List, Dict, Any
from fastrtc.utils import audio_to_int16
from pydantic import BaseModel, Field
from litellm.types.router import DeploymentTypedDict

from logger import logger
from schemas import PauseDetectionAlgorithm, VadOptions, Language
from constants import (
    VERSION,
    BASIC_LLM_MODEL_NAME,
    CONTEXT_RELEVANCE_MODEL_NAME,
    AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
    TEXT_TO_SPEECH_MODEL_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_VERBOSE,
    DEFAULT_AUDIO_INPUT_SAMPLE_RATE,
    DEFAULT_AUDIO_OUTPUT_SAMPLE_RATE,
    DEFAULT_TTS_OUTPUT_SAMPLE_RATE,
    DEFAULT_EXPECTED_AUDIO_LAYOUT,
    DEFAULT_GREETING_ENABLED,
    DEFAULT_WAITING_MESSAGE_POOL,
    DEFAULT_AUDIO_PROMPT_DELAY_THRESHOLD,
    DEFAULT_WAITING_AUDIO_CUES,
)


DEFAULT_TTS_MODEL = "openai/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_TTS_API_BASE = "http://host.docker.internal:8001/v1"
DEFAULT_TTS_API_KEY = "EMPTY"
DEFAULT_TTS_VOICES = ["vivian", "ryan", "aiden"]


def _get_env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name, "").strip()
    if not value:
        return default.copy()
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_default_available_voices() -> list[str]:
    return _get_env_list("TTS_VOICES", DEFAULT_TTS_VOICES)


def _get_default_tts_model() -> str:
    return os.environ.get("TTS_MODEL", DEFAULT_TTS_MODEL)


def _get_default_tts_api_base() -> str:
    return os.environ.get("TTS_API_BASE", DEFAULT_TTS_API_BASE)


def _get_default_tts_api_key() -> str:
    return os.environ.get("TTS_API_KEY", DEFAULT_TTS_API_KEY)


def _get_tts_api_base(model_list: List[DeploymentTypedDict]) -> str:
    for deployment in model_list:
        if deployment.get("model_name") != TEXT_TO_SPEECH_MODEL_NAME:
            continue
        litellm_params = deployment.get("litellm_params", {})
        api_base = litellm_params.get("api_base")
        if isinstance(api_base, str) and api_base.strip():
            return api_base
    return _get_default_tts_api_base()


def _get_tts_api_key(model_list: List[DeploymentTypedDict]) -> str:
    for deployment in model_list:
        if deployment.get("model_name") != TEXT_TO_SPEECH_MODEL_NAME:
            continue
        litellm_params = deployment.get("litellm_params", {})
        api_key = litellm_params.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key
    return _get_default_tts_api_key()


def _get_tts_voices_endpoint(api_base: str) -> str:
    normalized_api_base = api_base.rstrip("/")
    if normalized_api_base.endswith("/audio/voices"):
        return normalized_api_base
    if normalized_api_base.endswith("/v1"):
        return f"{normalized_api_base}/audio/voices"
    return f"{normalized_api_base}/v1/audio/voices"


def _extract_available_voices(payload: Any) -> list[str]:
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("data", "voices", "items"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        else:
            items = [payload]

    voices: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            voice = item.strip()
        elif isinstance(item, dict):
            voice = ""
            for key in ("voice", "id", "name"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    voice = value.strip()
                    break
        else:
            voice = ""

        if voice and voice not in seen:
            seen.add(voice)
            voices.append(voice)

    return voices


def _fetch_available_voices(model_list: List[DeploymentTypedDict]) -> list[str]:
    endpoint = _get_tts_voices_endpoint(_get_tts_api_base(model_list))
    api_key = _get_tts_api_key(model_list)
    headers = {}
    if api_key and api_key.upper() != "EMPTY":
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0)) as client:
            response = client.get(endpoint, headers=headers)
            response.raise_for_status()
        voices = _extract_available_voices(response.json())
        if voices:
            logger.info("Loaded %s TTS voices from %s", len(voices), endpoint)
        else:
            logger.warning("TTS voice discovery returned no usable voices from %s", endpoint)
        return voices
    except Exception as exc:
        logger.warning("Falling back to default TTS voices after discovery failed from %s: %s", endpoint, exc)
        return []


def _get_default_model_list() -> List[DeploymentTypedDict]:
    return [
        {
            "model_name": "automatic-speech-recognition",
            "litellm_params": {
                "model": os.environ.get("ASR_MODEL", "openai/sensevoice"),
                "api_base": os.environ.get("ASR_API_BASE", "http://stt:50000/v1"),
                "api_key": os.environ.get("ASR_API_KEY", "EMPTY"),
            },
            "model_info": {"id": "automatic-speech-recognition"},
        },
        {
            "model_name": "text-to-speech",
            "litellm_params": {
                "model": _get_default_tts_model(),
                "api_base": _get_default_tts_api_base(),
                "api_key": _get_default_tts_api_key(),
            },
            "model_info": {"id": "text-to-speech"},
        },
        {
            "model_name": "basic-llm",
            "litellm_params": {
                "model": os.environ.get("BASIC_LLM_MODEL", "gpt-4o"),
                "api_key": os.environ.get("OPENAI_API_KEY", "dummy"),
            },
            "model_info": {"id": "basic-llm"},
        },
    ]


class Configuration(BaseModel):
    """Configurable fields."""

    class Config:
        arbitrary_types_allowed = True

    title: str = "Agentic Voice Assistant"
    description: str = "API for Agentic Voice Assistant"
    version: str = VERSION

    host: str = Field(default=DEFAULT_HOST, description="")
    port: int = Field(default=DEFAULT_PORT, description="")

    config_file_path: str | None = Field(
        default=None,
        description="Path to the configuration YAML/JSON file",
    )

    verbose: bool = Field(
        default=DEFAULT_VERBOSE,
        description="Whether to enable verbose logging",
    )

    language: Language = Field(
        default=Language.CHINESE,
        description="Language of the assistant",
    )
    greeting_enabled: bool = Field(
        default=DEFAULT_GREETING_ENABLED,
        description="Whether to enable greeting after connected",
    )

    server_rtc_configuration: dict[str, Any] | None = None

    available_voices: list[str] = Field(
        default_factory=_get_default_available_voices,
        description="The voice to use when generating the audio",
    )
    voice_generation_instruction: list[str] = Field(
        default=[],
        description="Control the voice of your generated audio with additional instructions. ",
    )

    pause_detection_algorithm: PauseDetectionAlgorithm = Field(
        default_factory=PauseDetectionAlgorithm,
        description="Configuration for voice activity detection algorithm",
    )
    voice_activity_detection_options: VadOptions = Field(
        default_factory=VadOptions,
        description="Runtime options for VAD model",
    )
    allow_interruption: bool = Field(
        default=True,
        description="Whether the assistant can be interrupted by new voice input",
    )
    expected_audio_layout: Literal["mono", "stereo"] = DEFAULT_EXPECTED_AUDIO_LAYOUT
    audio_input_sample_rate: int = DEFAULT_AUDIO_INPUT_SAMPLE_RATE
    audio_output_sample_rate: int = DEFAULT_AUDIO_OUTPUT_SAMPLE_RATE
    tts_output_sample_rate: int = int(
        os.environ.get("TTS_OUTPUT_SAMPLE_RATE", DEFAULT_TTS_OUTPUT_SAMPLE_RATE)
    )

    waiting_message_enabled: bool = False
    waiting_message_pool: Dict[str, list[str]] = DEFAULT_WAITING_MESSAGE_POOL
    audio_prompt_delay_threshold: int = DEFAULT_AUDIO_PROMPT_DELAY_THRESHOLD
    waiting_audio_cues: list[tuple[int, NDArray[np.int16]]] = []

    ui: Dict[str, Any] = Field(default_factory=dict)

    model_list: List[DeploymentTypedDict] = Field(
        default_factory=_get_default_model_list,
        description="List of models to be used for LiteLLM.",
    )

    def refresh_available_voices(self, prefer_existing: bool = True) -> None:
        env_voices = _get_env_list("TTS_VOICES", [])
        if env_voices:
            self.available_voices = env_voices
            return

        if prefer_existing and self.available_voices:
            return

        fetched_voices = _fetch_available_voices(self.model_list)
        if fetched_voices:
            self.available_voices = fetched_voices
        elif not self.available_voices:
            self.available_voices = DEFAULT_TTS_VOICES.copy()

    def load_config_file(self, config_path: str | None = None) -> None:
        """
        Load settings from a configuration file.

        Args:
            config_path (Optional[str]): Path to the configuration file.
                If None, searches in default locations.

        Raises:
            FileNotFoundError: If no configuration file is found or readable.
        """
        search_paths = []

        if config_path:
            search_paths.append(config_path)

        if self.config_file_path:
            search_paths.append(self.config_file_path)

        # Fallback to default paths
        search_paths += [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml"),
            "/etc/voicebot/config.yaml",
            os.path.expanduser("~/.voicebot.yaml"),
        ]

        for path in search_paths:
            if os.path.exists(path):
                config_path = path
                break

        if config_path is None:
            raise FileNotFoundError(
                f"Configuration file not found in locations: {search_paths}"
            )

        if not os.path.isfile(config_path) or not os.access(config_path, os.R_OK):
            raise FileNotFoundError(
                f"Configuration file {config_path} is not a file or not readable."
            )

        self.config_file_path = config_path

        # Read and parse config file
        config = yaml.safe_load(open(self.config_file_path, "r", encoding="utf-8"))

        if "SECRET_ARN" in os.environ and os.environ["SECRET_ARN"]:
            secretsmanager_client = boto3.client(
                "secretsmanager",
                region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"),
            )
            secret = json.loads(
                secretsmanager_client.get_secret_value(SecretId=os.environ["SECRET_ARN"])[
                    "SecretString"
                ]
            )
            config["model_list"] = secret.get("model_list", config.get("model_list", []))
            aws_webrtc = secret.get("webrtc", {})
            stunner_user = aws_webrtc.get("stunner_user", "test")
            stunner_password = aws_webrtc.get("stunner_password", "test")
        else:
            stunner_user = os.environ.get("STUNNER_USER", "test")
            stunner_password = os.environ.get("STUNNER_PASSWORD", "test")

        if not config.get("model_list") and "model_list" not in locals():
            config["model_list"] = _get_default_model_list()

        global_settings = config.get("global", {})
        self.host = global_settings.get("host", DEFAULT_HOST)
        self.port = int(global_settings.get("port", DEFAULT_PORT))
        self.verbose = bool(global_settings.get("verbose", DEFAULT_VERBOSE))

        if self.verbose is True:
            logger.setLevel(logging.DEBUG)
            os.environ["LITELLM_LOG"] = "DEBUG"

        rtc_settings = config.get("rtc", {})
        for server in rtc_settings.get("stun_servers", []):
            protocol = server.get("protocol", "udp")
            if protocol == "udp":
                port = server.get("port", 19302)
            else:
                port = server.get("port", 3478)
            username = stunner_user
            credential = stunner_password
            host = server["host"]
            if self.server_rtc_configuration is None:
                self.server_rtc_configuration = {"iceServers": []}

            self.server_rtc_configuration["iceServers"].append(
                dict(
                    urls=(
                        f"stun:{host}:{port}?transport={protocol}"
                        if protocol == "tcp"
                        else f"stun:{host}:{port}"
                    ),
                    username=username,
                    credential=credential,
                )
            )

        for server in rtc_settings.get("turn_servers", []):
            protocol = server.get("protocol", "udp")
            port = server.get("port", 3478)
            username = stunner_user
            credential = stunner_password
            host = server["host"]
            if self.server_rtc_configuration is None:
                self.server_rtc_configuration = {"iceServers": []}

            self.server_rtc_configuration["iceServers"].append(
                dict(
                    urls=f"turn:{host}:{port}?transport={protocol}",
                    username=username,
                    credential=credential,
                )
            )

        voice_settings = config.get("voice", {})

        self.language = Language(voice_settings.get("language", "chinese"))
        self.greeting_enabled = voice_settings.get(
            "greeting_enabled", DEFAULT_GREETING_ENABLED
        )
        configured_available_voices = voice_settings.get("available_voices")
        self.available_voices = configured_available_voices or []
        self.voice_generation_instruction = voice_settings.get(
            "voice_generation_instruction", []
        )

        self.pause_detection_algorithm = PauseDetectionAlgorithm(
            **voice_settings.get("pause_detection_algorithm", {})
        )

        self.voice_activity_detection_options = VadOptions(
            **voice_settings.get("voice_activity_detection_options", {})
        )
        self.allow_interruption = bool(voice_settings.get("allow_interruption", True))
        self.expected_audio_layout = voice_settings.get(
            "expected_audio_layout", DEFAULT_EXPECTED_AUDIO_LAYOUT
        )
        self.audio_input_sample_rate = int(
            voice_settings.get(
                "audio_input_sample_rate", DEFAULT_AUDIO_INPUT_SAMPLE_RATE
            )
        )
        self.audio_output_sample_rate = int(
            voice_settings.get(
                "audio_output_sample_rate", DEFAULT_AUDIO_OUTPUT_SAMPLE_RATE
            )
        )
        self.tts_output_sample_rate = int(
            voice_settings.get("tts_output_sample_rate", DEFAULT_TTS_OUTPUT_SAMPLE_RATE)
        )

        self.waiting_message_enabled = voice_settings.get(
            "waiting_message_enabled", False
        )
        DEFAULT_WAITING_MESSAGE_POOL.update(
            voice_settings.get("waiting_message_pool", DEFAULT_WAITING_MESSAGE_POOL)
        )
        self.waiting_message_pool = DEFAULT_WAITING_MESSAGE_POOL
        self.audio_prompt_delay_threshold = voice_settings.get(
            "audio_prompt_delay_threshold", DEFAULT_AUDIO_PROMPT_DELAY_THRESHOLD
        )
        for f in voice_settings.get("waiting_audio_cues", DEFAULT_WAITING_AUDIO_CUES):
            if os.path.isfile(f):
                audio, sr = librosa.load(path=f, sr=self.audio_output_sample_rate)
                self.waiting_audio_cues.append((int(sr), audio_to_int16(audio)))

        self.ui = config.get("ui", {})
        self.model_list = config.get("model_list", [])

        self.validate_model_references()
        self.refresh_available_voices(prefer_existing=bool(configured_available_voices))

        if self.pause_detection_algorithm.semantic_check_threshold > 0.0:
            if CONTEXT_RELEVANCE_MODEL_NAME not in self.available_models:
                logger.warning(
                    f"Context relevance model '{CONTEXT_RELEVANCE_MODEL_NAME}' not found. "
                    f"Falling back to LLM model '{BASIC_LLM_MODEL_NAME}'"
                )
                for model in self.model_list:
                    if model["model_name"] == BASIC_LLM_MODEL_NAME:
                        self.model_list.append(
                            DeploymentTypedDict(
                                model_name=CONTEXT_RELEVANCE_MODEL_NAME,
                                litellm_params=model.get("litellm_params", {}),
                                model_info=model.get("model_info", {}),
                            )
                        )
                        break

    @property
    def available_models(self):
        return {model["model_name"] for model in self.model_list}

    def validate_model_references(self):
        required_models = [
            BASIC_LLM_MODEL_NAME,
            AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
            TEXT_TO_SPEECH_MODEL_NAME,
        ]

        missing_models = [
            name for name in required_models if name not in self.available_models
        ]

        if missing_models:
            raise ValueError(
                f"Missing model definitions in model_list: {', '.join(missing_models)}"
            )


configure = Configuration()
