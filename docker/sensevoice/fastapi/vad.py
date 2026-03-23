import math
import torch
import numpy as np
import traceback
from numpy.typing import NDArray
from silero_vad import get_speech_timestamps, load_silero_vad

from logger import logger
from schemas import AudioChunk
from constants import SAMPLE_RATE


class VoiceActivityDetection:

    def __init__(self):
        self.model = load_silero_vad(onnx=True)

    @staticmethod
    def collect_chunks(audio: np.ndarray, chunks: list[AudioChunk]) -> np.ndarray:
        """Collects and concatenates audio chunks."""
        if not chunks:
            return np.array([], dtype=np.float32)

        return np.concatenate(
            [audio[chunk["start"] : chunk["end"]] for chunk in chunks]
        )

    def warmup(self):
        for _ in range(10):
            dummy_audio = np.zeros(102400, dtype=np.float32)
            self.vad(dummy_audio)

    def vad(
        self,
        audio: NDArray[np.float32] | NDArray[np.int16],
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        max_speech_duration_s: float = float("inf"),
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
    ) -> tuple[float, float, list[AudioChunk]]:
        logger.debug("VAD audio shape input: %s", audio.shape)

        try:
            trailing_silence_duration = audio.shape[0] / SAMPLE_RATE

            speech_chunks = get_speech_timestamps(
                audio=torch.from_numpy(audio),
                model=self.model,
                sampling_rate=SAMPLE_RATE,
                threshold=threshold,
                min_speech_duration_ms=min_speech_duration_ms,
                max_speech_duration_s=max_speech_duration_s,
                min_silence_duration_ms=min_silence_duration_ms,
                speech_pad_ms=speech_pad_ms,
            )
            speech_audio = self.collect_chunks(audio, speech_chunks)
            logger.debug(
                f"VAD speech chunks [Silero]: {speech_chunks}, speech audio shape: {speech_audio.shape}, speech audio size: {speech_audio.size}, speech ratio: {speech_audio.size / audio.size:.2f}"
            )
            duration_after_vad = speech_audio.shape[0] / SAMPLE_RATE
            if speech_chunks:
                trailing_silence_duration = (
                    audio.shape[0] - speech_chunks[-1]["end"]
                ) / SAMPLE_RATE
            else:
                trailing_silence_duration = audio.shape[0] / SAMPLE_RATE

            return duration_after_vad, trailing_silence_duration, speech_chunks
        except Exception as e:
            logger.error("VAD Exception: %s", str(e))
            exec = traceback.format_exc()
            logger.error("traceback %s", exec)
            return math.inf, 0.0, []
