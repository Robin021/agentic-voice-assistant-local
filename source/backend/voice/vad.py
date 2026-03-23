import torch
import librosa
import webrtcvad
import numpy as np
from typing import Literal
from numpy.typing import NDArray
from pyrnnoise import RNNoise
from silero_vad import get_speech_timestamps, load_silero_vad
from huggingface_hub import hf_hub_download
from fastrtc.utils import AudioChunk, audio_to_float32, audio_to_int16

from logger import logger
from schemas import VadOptions, VadModel, VadMode


class VoiceActivityDetection:

    def __init__(self, options: VadOptions | None = None):
        self.options = options or VadOptions()
        self.sampling_rate: Literal[16000] = 16000
        self.mode = self.options.mode
        self.model_name = self.options.model
        self.threshold = self.options.threshold
        self.min_speech_duration_ms = self.options.min_speech_duration_ms
        self.max_speech_duration_s = self.options.max_speech_duration_s
        self.min_silence_duration_ms = self.options.min_silence_duration_ms
        self.window_size_samples = self.options.window_size_samples
        self.speech_pad_ms = self.options.speech_pad_ms
        self.webrtcvad_sensitivity = self.options.webrtcvad_sensitivity
        self.webrtcvad_voiced_frame_threshold = (
            self.options.webrtcvad_voiced_frame_threshold
        )
        # Initialize WebRTC VAD model with configured sensitivity
        self.webrtc_vad_model = webrtcvad.Vad()
        self.webrtc_vad_model.set_mode(self.webrtcvad_sensitivity)
        self.denoiser: RNNoise | None = None

        if self.model_name == VadModel.SILERO:
            self.model = load_silero_vad(onnx=True)
        elif self.model_name == VadModel.HUMMING_AWARE:
            path = hf_hub_download(
                repo_id="CuriousMonkey7/HumAware-VAD",
                filename="HumAwareVAD.jit",
                revision="d921cf5d288c9ad7a6a38d44ad5f57cd16b71e39",
            )
            self.model = torch.jit.load(path, map_location=torch.device("cpu"))
            self.model.eval()

    @staticmethod
    def collect_chunks(audio: np.ndarray, chunks: list[AudioChunk]) -> np.ndarray:
        """Collects and concatenates audio chunks."""
        if not chunks:
            return np.array([], dtype=np.float32)

        return np.concatenate(
            [audio[chunk["start"] : chunk["end"]] for chunk in chunks]
        )

    @staticmethod
    def convert_speech_chunks(
        chunks: list, source_sample_rate: int, target_sample_rate: int
    ) -> list:
        """
        Convert speech chunk indices from source to target sample rate.

        Args:
            speech_chunks: List of dicts containing 'start' and 'end' indices
                        in source sample rate units.
            source_sample_rate: Original sample rate (Hz) of the audio.
            target_sample_rate: Target sample rate (Hz) for conversion.

        Returns:
            List of dicts with converted 'start' and 'end' indices in target
            sample rate units. Returns empty list if input is empty.

        Example:
            >>> chunks = [{'start': 44100, 'end': 88200}]
            >>> convert_speech_chunks(chunks, 44100, 22050)
            [{'start': 22050, 'end': 44100}]
        """
        if not chunks:
            return []
        # Calculate conversion ratio (target/source)
        ratio = target_sample_rate / source_sample_rate

        converted_chunks = []
        for chunk in chunks:
            converted_chunks.append(
                dict(start=int(chunk["start"] * ratio), end=int(chunk["end"] * ratio))
            )
        return converted_chunks

    def warmup(self):
        for _ in range(10):
            dummy_audio = np.zeros(102400, dtype=np.float32)
            self.vad((24000, dummy_audio))

    def denoise_chunks(self, denoiser, audio: np.ndarray, is_last=False):
        frames = []
        for _, frame in denoiser.process_chunk(audio, is_last):
            frames.append(frame.squeeze())
        return np.concatenate(frames) if len(frames) > 0 else np.array([])

    def get_speech_timestamps_using_webrtc(
        self,
        audio: NDArray[np.int16],
        sample_rate: Literal[8000, 16000, 32000, 48000] = 16000,
        frame_duration_ms: Literal[10, 20, 30] = 10,
    ) -> list:
        """
        Detect speech in audio using WebRTC's Voice Activity Detection (VAD) algorithm.

        Args:
            audio: Input audio data as 16-bit PCM samples
            sample_rate: Audio sample rate in Hz (default 16000)
            frame_duration_ms: Duration of each analysis frame in milliseconds (default 10ms)

        Returns:
            bool: True if speech is detected, False otherwise
        """
        # Convert numpy array to bytes
        audio_bytes = audio.astype(np.int16).tobytes()

        # Calculate frame parameters
        samples_per_frame = int(sample_rate * frame_duration_ms / 1000)
        bytes_per_frame = samples_per_frame * 2  # 2 bytes per sample for int16
        total_frames = len(audio_bytes) // bytes_per_frame

        speeches = []
        current_speech = {}
        # current_start = current_end = 0
        for frame_idx in range(total_frames):
            frame_start = frame_idx * bytes_per_frame
            frame_end = frame_start + bytes_per_frame
            frame = audio_bytes[frame_start:frame_end]

            if self.webrtc_vad_model.is_speech(buf=frame, sample_rate=sample_rate):
                if not current_speech:
                    current_speech = {"start": frame_start // 2, "end": frame_end // 2}
                else:
                    current_speech["end"] = frame_end // 2
            else:
                if current_speech:
                    speeches.append(current_speech)
                    current_speech = {}

        if current_speech:
            speeches.append(current_speech)

        return speeches

    def vad(
        self,
        audio: tuple[int, NDArray[np.float32] | NDArray[np.int16]],
        noise_suppression_enabled: bool = False,
    ) -> tuple[float, float, list[AudioChunk]]:
        sampling_rate, input_audio = audio
        logger.debug("VAD audio shape input: %s", input_audio.shape)

        try:
            trailing_silence_duration = input_audio.shape[0] / self.sampling_rate
            processed_audio = audio_to_float32(input_audio)
            if self.sampling_rate != sampling_rate:
                processed_audio = librosa.resample(
                    processed_audio, orig_sr=sampling_rate, target_sr=self.sampling_rate
                )

            if self.mode in (VadMode.HYBRID, VadMode.WEBRTCVAD_ONLY):
                speech_chunks = self.get_speech_timestamps_using_webrtc(
                    audio=audio_to_int16(processed_audio),
                    sample_rate=self.sampling_rate,
                )
                speech_audio = self.collect_chunks(processed_audio, speech_chunks)
                logger.debug(
                    f"VAD speech chunks [webrtcvad]: {speech_chunks}, speech audio shape: {speech_audio.shape}, speech audio size: {speech_audio.size}, speech ratio: {speech_audio.size / processed_audio.size:.2f}"
                )
                duration_after_vad = speech_audio.shape[0] / self.sampling_rate

                if (
                    speech_audio.size / processed_audio.size
                    <= self.webrtcvad_voiced_frame_threshold
                ) or self.mode == VadMode.WEBRTCVAD_ONLY:
                    if speech_chunks:
                        trailing_silence_duration = (
                            input_audio.shape[0] - speech_chunks[-1]["end"]
                        ) / self.sampling_rate
                    else:
                        trailing_silence_duration = (
                            input_audio.shape[0] / self.sampling_rate
                        )

                    return (
                        duration_after_vad,
                        trailing_silence_duration,
                        self.convert_speech_chunks(
                            speech_chunks, self.sampling_rate, sampling_rate
                        ),
                    )

            if noise_suppression_enabled is True:
                if self.denoiser is None:
                    self.denoiser = RNNoise(self.sampling_rate)
                processed_audio = self.denoise_chunks(
                    self.denoiser, processed_audio, False
                )

            speech_chunks = get_speech_timestamps(
                audio=torch.from_numpy(processed_audio),
                model=self.model,
                sampling_rate=self.sampling_rate,
                threshold=self.threshold,
                min_speech_duration_ms=self.min_speech_duration_ms,
                max_speech_duration_s=self.max_speech_duration_s,
                min_silence_duration_ms=self.min_silence_duration_ms,
                speech_pad_ms=self.speech_pad_ms,
                window_size_samples=self.window_size_samples,
            )
            speech_audio = self.collect_chunks(processed_audio, speech_chunks)
            logger.debug(
                f"VAD speech chunks [{self.model_name.value}]: {speech_chunks}, speech audio shape: {speech_audio.shape}, speech audio size: {speech_audio.size}, speech ratio: {speech_audio.size / processed_audio.size:.2f}"
            )
            duration_after_vad = speech_audio.shape[0] / self.sampling_rate
            if speech_chunks:
                trailing_silence_duration = (
                    input_audio.shape[0] - speech_chunks[-1]["end"]
                ) / self.sampling_rate
            else:
                trailing_silence_duration = input_audio.shape[0] / self.sampling_rate

            return (
                duration_after_vad,
                trailing_silence_duration,
                self.convert_speech_chunks(
                    speech_chunks, self.sampling_rate, sampling_rate
                ),
            )
        except Exception as e:
            import math
            import traceback

            logger.debug("VAD Exception: %s", str(e))
            exec = traceback.format_exc()
            logger.debug("traceback %s", exec)
            return math.inf, 0.0, []
