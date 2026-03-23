import io
import os
import json
import torch
import numpy as np
import asyncio
import argparse
import torchaudio
from typing import BinaryIO, Literal, AsyncGenerator
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import Response, StreamingResponse
from typing_extensions import Annotated
from model import SenseVoiceSmall  # type: ignore
from funasr.utils.postprocess_utils import rich_transcription_postprocess  # type: ignore

from schemas import (
    TranscriptionTextDeltaEvent,
    TranscriptionTextDoneEvent,
    TranscriptionSegment,
    Transcription,
    Language,
    ResponseFormat,
    ChunkingStrategy,
    AudioChunk,
)
from constants import SAMPLE_RATE, VAD_MIN_DURATION_S
from vad import VoiceActivityDetection
from logger import logger

model_dir = "iic/SenseVoiceSmall"
m, kwargs = SenseVoiceSmall.from_pretrained(
    model=model_dir, device=os.getenv("SENSEVOICE_DEVICE", "cuda:0")
)
m.eval()

silero_vad = VoiceActivityDetection()

app = FastAPI()


def resample(audio, original_rate, target_rate=SAMPLE_RATE):
    if original_rate != target_rate:
        transform = torchaudio.transforms.Resample(
            orig_freq=original_rate, new_freq=target_rate
        )
        audio = transform(audio)
    if audio.shape[0] > 1:
        audio = torch.mean(audio, dim=0, keepdim=True)
    return audio.squeeze(0)


def tensor_to_ndarray(audio_tensor: torch.Tensor) -> np.ndarray:
    """Convert torch audio tensor to numpy ndarray."""
    # Convert torch.Tensor to numpy.ndarray with optimal performance
    # For float32 tensor (most common case):
    if audio_tensor.dtype == torch.float32:
        # Use .numpy() with requires_grad=False for best performance
        # No copy is made as they share underlying memory (when on CPU)
        return audio_tensor.detach().cpu().numpy()
    # For int16 tensor:
    elif audio_tensor.dtype == torch.int16:
        # Same approach as float32
        return audio_tensor.detach().cpu().numpy()
    else:
        # For other dtypes, convert to float32 first (common audio processing practice)
        return audio_tensor.to(torch.float32).detach().cpu().numpy()


async def audio_chunk_generator(
    audio: torch.Tensor,
    chunking_strategy: ChunkingStrategy | None = None,
) -> AsyncGenerator[AudioChunk, None]:
    if chunking_strategy is None:
        yield AudioChunk(start=0, end=audio.shape[0])
        return

    _, _, speech_chunks = silero_vad.vad(
        audio=tensor_to_ndarray(audio),
        threshold=chunking_strategy.threshold,
        min_speech_duration_ms=chunking_strategy.min_speech_duration_ms,
        max_speech_duration_s=chunking_strategy.max_speech_duration_s,
        min_silence_duration_ms=chunking_strategy.silence_duration_ms,
        speech_pad_ms=chunking_strategy.prefix_padding_ms,
    )

    for chunk in speech_chunks:
        yield chunk


async def generate_sse_messages(
    transcription_events: AsyncGenerator[
        TranscriptionTextDeltaEvent | TranscriptionTextDoneEvent, None
    ],
) -> AsyncGenerator[str, None]:
    """Format an event as SSE-compliant string"""
    async for event in transcription_events:
        yield f"data: {event.json}\n\n"
        await asyncio.sleep(0)


async def generate_transcription_stream(
    uri: BinaryIO | str | os.PathLike,
    language: Language = Language.AUTO,
    chunking_strategy: ChunkingStrategy | Literal["auto"] | None = None,
) -> AsyncGenerator[TranscriptionTextDeltaEvent | TranscriptionTextDoneEvent, None]:
    """Generate Server-Sent Events stream of transcription results"""
    audio, sr = torchaudio.load(uri)
    audio = resample(audio=audio, original_rate=sr, target_rate=SAMPLE_RATE)
    duration = len(audio) / sr

    if chunking_strategy == "auto":
        if duration > VAD_MIN_DURATION_S:
            chunking_strategy = ChunkingStrategy()
        else:
            chunking_strategy = None

    index = 0
    text = ""
    segments = []
    async for chunk in audio_chunk_generator(
        audio=audio, chunking_strategy=chunking_strategy
    ):
        result = m.inference(
            data_in=audio[chunk["start"] : chunk["end"]],
            language=language.value,
            use_itn=True,
            ban_emo_unk=False,
            batch_size_s=60,
            key="audio",
            fs=SAMPLE_RATE,
            **kwargs,
        )
        if len(result) == 0:
            continue

        for res in result[0]:
            delta_text = rich_transcription_postprocess(res["text"])
            text += delta_text
            segment = TranscriptionSegment(
                id=index,
                start=int(chunk["start"] / sr * 1000),
                end=int(chunk["end"] / sr * 1000),
                text=delta_text,
            )
            segments.append(segment)
            yield TranscriptionTextDeltaEvent(delta=delta_text, segments=[segment])

    yield TranscriptionTextDoneEvent(text=text, segments=segments)


@app.post(f"/v1/audio/transcriptions")
async def transcription(
    file: Annotated[
        UploadFile,
        File(
            description="The audio file object (not file name) to transcribe, in one of these formats: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm."
        ),
    ],
    model: Annotated[
        str, Form(description="ID of the model to use.")
    ] = "SenseVoiceSmall",
    language: Annotated[
        Language | None,
        Form(
            description="The language of the input audio. Supplying the input language in ISO-639-1 (e.g. en) format will improve accuracy and latency.",
        ),
    ] = None,
    prompt: Annotated[
        str | None,
        Form(
            description="An optional text to guide the model's style or continue a previous audio segment.",
        ),
    ] = None,
    response_format: Annotated[
        ResponseFormat,
        Form(
            description="The format of the output, in one of these options: json, text, srt, verbose_json, or vtt.",
        ),
    ] = ResponseFormat.JSON,
    stream: Annotated[
        bool,
        Form(
            description="If set to true, the model response data will be streamed to the client as it is generated using server-sent events. See the Streaming section of the Speech-to-Text guide for more information.",
        ),
    ] = False,
    chunking_strategy: Annotated[
        Literal["auto"] | None,
        Form(
            description='Controls how the audio is cut into chunks. When set to "auto", the server first normalizes loudness and then uses voice activity detection (VAD) to choose boundaries. server_vad object can be provided to tweak VAD detection parameters manually. If unset, the audio is transcribed as a single block.',
        ),
    ] = "auto",
    chunking_strategy_type: Annotated[
        Literal["server_vad"] | None,
        Form(
            alias="chunking_strategy[type]",
            description="Must be set to server_vad to enable manual chunking using server side VAD.",
        ),
    ] = None,
    chunking_strategy_prefix_padding_ms: Annotated[
        int | None,
        Form(
            alias="chunking_strategy[prefix_padding_ms]",
            description="Amount of audio to include before the VAD detected speech (in milliseconds).",
        ),
    ] = None,
    chunking_strategy_silence_duration_ms: Annotated[
        int | None,
        Form(
            alias="chunking_strategy[silence_duration_ms]",
            description="Duration of silence to detect speech stop (in milliseconds). With shorter values the model will respond more quickly, but may jump in on short pauses from the user.",
        ),
    ] = None,
    chunking_strategy_threshold: Annotated[
        float | None,
        Form(
            alias="chunking_strategy[threshold]",
            description="Sensitivity threshold (0.0 to 1.0) for voice activity detection. A higher threshold will require louder audio to activate the model, and thus might perform better in noisy environments.",
        ),
    ] = None,
    chunking_strategy_min_speech_duration_ms: Annotated[
        float | None,
        Form(
            alias="chunking_strategy[min_speech_duration_ms]",
            description="Final speech chunks shorter min_speech_duration_ms are thrown out.",
        ),
    ] = None,
    chunking_strategy_max_speech_duration_s: Annotated[
        float | None,
        Form(
            alias="chunking_strategy[max_speech_duration_s]",
            description=(
                "Maximum duration of speech chunks in seconds. Chunks longer"
                "than max_speech_duration_s will be split at the timestamp of the last silence that"
                "lasts more than 100ms (if any), to prevent aggressive cutting. Otherwise, they will be"
                "split aggressively just before max_speech_duration_s."
            ),
        ),
    ] = None,
):
    """
    Transcribe audio file with optional streaming output.

    Args:
        audio_file: Uploaded audio file
        request_config: Transcription parameters including language and streaming preference

    Returns:
        Either complete transcription or SSE stream of transcription chunks
    """
    logger.info(
        f"received transcription request: {file.filename}, model: {model}, language: {language}, response_format: {response_format}, stream: {stream}, chunking_strategy: {chunking_strategy}, chunking_strategy_type: {chunking_strategy_type}"
    )
    audio_bytes = await file.read()
    audio_buf = io.BytesIO(audio_bytes)

    if language is None:
        language = Language.AUTO

    if chunking_strategy_type == "server_vad":
        chunking_strategy_params = {}

        if chunking_strategy_prefix_padding_ms is not None:
            chunking_strategy_params["prefix_padding_ms"] = (
                chunking_strategy_prefix_padding_ms
            )
        if chunking_strategy_silence_duration_ms is not None:
            chunking_strategy_params["silence_duration_ms"] = (
                chunking_strategy_silence_duration_ms
            )
        if chunking_strategy_threshold is not None:
            chunking_strategy_params["threshold"] = chunking_strategy_threshold
        if chunking_strategy_min_speech_duration_ms is not None:
            chunking_strategy_params["min_speech_duration_ms"] = (
                chunking_strategy_min_speech_duration_ms
            )
        if chunking_strategy_max_speech_duration_s is not None:
            chunking_strategy_params["max_speech_duration_s"] = (
                chunking_strategy_max_speech_duration_s
            )

        chunking_strategy_config = ChunkingStrategy(**chunking_strategy_params)
    else:
        chunking_strategy_config = "auto"

    if stream is True and response_format in (
        ResponseFormat.JSON,
        ResponseFormat.VERBOSE_JSON,
    ):
        return StreamingResponse(
            content=generate_sse_messages(
                transcription_events=generate_transcription_stream(
                    uri=audio_buf,
                    language=language,
                    chunking_strategy=chunking_strategy_config,
                ),
            ),
            media_type="text/event-stream",
        )

    content = Transcription(text="")
    async for event in generate_transcription_stream(
        uri=audio_buf,
        language=language,
        chunking_strategy=chunking_strategy_config,
    ):
        if event.type == "transcript.text.done":
            content.text = event.text
            content.segments = event.segments
            break

    if response_format == ResponseFormat.TEXT:
        return Response(content=content.text, media_type="text/plain")
    elif response_format == ResponseFormat.SRT:
        return Response(content=content.srt, media_type="text/plain")
    return Response(content=content.json, media_type="application/json")


@app.get(f"/v1/health", response_class=Response)
async def check_health():
    return Response()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=50000)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
