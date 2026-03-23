import io
import os
import sys
import torch
import numpy as np
import logging
import argparse
import torchaudio
from enum import Enum
from typing import Literal, Optional, Annotated, AsyncGenerator, Dict, Any
from pydantic import ValidationError, Field
from fastapi import FastAPI, HTTPException, UploadFile, Form, Body, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(f"{ROOT_DIR}/../../..")
sys.path.append(f"{ROOT_DIR}/../../../third_party/Matcha-TTS")
from async_cosyvoice.async_cosyvoice import AsyncCosyVoice2  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

COSYVOICE_INPUT_SAMPLE_RATE = 16000
COSYVOICE_OUTPUT_SAMPLE_RATE = 24000


app = FastAPI()


class AudioFormat(Enum):
    MP3 = "mp3"
    WAV = "wav"
    PCM = "pcm"
    OGG = "ogg"
    FLAC = "flac"


def save_voice_data(
    voice: str, audio_data: bytes, text: str, name: Optional[str] = None
) -> str:
    """保存音频数据并生成音色对应的URI"""
    prompt_speech_16k = load_audio_from_bytes(audio_data)
    cosyvoice.frontend.generate_spk_info(
        spk_id=voice,
        prompt_text=text,
        prompt_speech_16k=prompt_speech_16k,
        resample_rate=24000,
        name=name,
    )
    return voice


def get_content_type(format: AudioFormat, sample_rate: int = 16000) -> str:
    """获取对应格式的Content-Type"""
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "pcm": f"audio/L16; rate={sample_rate}; channels=1",
    }[format.value]


async def generate_audio_stream(
    processor: AsyncGenerator,
    sample_rate: int = 24000,
    format: AudioFormat = AudioFormat.WAV,
) -> AsyncGenerator[bytes, None]:

    if sample_rate != COSYVOICE_OUTPUT_SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(
            orig_freq=COSYVOICE_OUTPUT_SAMPLE_RATE, new_freq=sample_rate
        )

    if format == AudioFormat.PCM:
        async for chunk in processor:
            speech = chunk["tts_speech"]
            if sample_rate != COSYVOICE_OUTPUT_SAMPLE_RATE:
                speech = resampler(speech)
            yield np.clip(speech.numpy() * 32767, -32768, 32767).astype(
                np.int16
            ).tobytes()
    else:
        speech = torch.empty((1, 0), dtype=torch.float32)
        async for chunk in processor:
            speech_chunk = chunk["tts_speech"]
            if sample_rate != COSYVOICE_OUTPUT_SAMPLE_RATE:
                speech_chunk = resampler(speech_chunk)

            speech = torch.cat([speech, speech_chunk], dim=1)

        extra_params: Dict[str, Any] = dict(
            wav=dict(format="wav", encoding="PCM_F"),
            mp3=dict(format="mp3"),
            ogg=dict(format="ogg"),
            flac=dict(format="flac", encoding="PCM_F"),
        )

        with io.BytesIO() as buffer:
            torchaudio.save(
                uri=buffer,
                src=speech,
                sample_rate=sample_rate,
                **extra_params[format.value],
            )
            yield buffer.getvalue()


def load_audio_from_bytes(audio_data: bytes) -> torch.Tensor:
    # 将字节数据包装成文件对象
    buffer = io.BytesIO(audio_data)
    # 使用soundfile后端加载音频
    speech, sample_rate = torchaudio.load(buffer, backend="soundfile")
    # 多声道转单声道（取均值）
    speech = speech.mean(dim=0, keepdim=True)

    # 检查并调整采样率
    if sample_rate != COSYVOICE_INPUT_SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(
            orig_freq=sample_rate, new_freq=COSYVOICE_INPUT_SAMPLE_RATE
        )
        speech = resampler(speech)
    return speech


@app.post(f"/v1/audio/speech")
async def speech(
    input: Annotated[
        str,
        Body(
            min_length=1,
            max_length=4096,
            description="The text to generate audio for. The maximum length is 4096 characters.",
        ),
    ],
    model: Annotated[str, Body(description="ID of the model to use.")] = "CosyVoice2",
    voice: Annotated[
        str,
        Body(
            description="The voice to use when generating the audio.",
        ),
    ] = "凯亚",
    instructions: Annotated[
        str | None,
        Body(
            description="Control the voice of your generated audio with additional instructions.",
        ),
    ] = None,
    response_format: Annotated[
        AudioFormat,
        Body(
            description="The format to audio in. Supported formats are mp3, opus, aac, flac, wav, and pcm.",
        ),
    ] = AudioFormat.WAV,
    stream: Annotated[
        bool,
        Body(
            description="If set to true, the model response data will be streamed to the client as it is generated.",
        ),
    ] = False,
    speed: Annotated[
        float,
        Body(
            description="The speed of the generated audio. Select a value from 0.25 to 4.0. 1.0 is the default. ",
        ),
    ] = 1.0,
    sample_rate: Annotated[
        Literal[
            8000,
            16000,
            24000,
            32000,
            44100,
            48000,
            64000,
            96000,
        ],
        Body(
            description="The sample rate of the generated audio. Select a value from 8000 to 96000. 16000 is the default.",
        ),
    ] = 16000,
):
    """Generates audio from the input text."""
    if instructions:
        processor = cosyvoice.inference_instruct2_by_spk_id(
            tts_text=input,
            instruct_text=instructions,
            spk_id=voice,
            stream=stream,
            speed=speed,
            text_frontend=True,
        )
    else:
        processor = cosyvoice.inference_zero_shot_by_spk_id(
            tts_text=input,
            spk_id=voice,
            stream=stream,
            speed=speed,
            text_frontend=True,
        )

    try:
        content_type = get_content_type(format=response_format, sample_rate=sample_rate)
        headers = {"Content-Disposition": f"attachment; filename=audio.wav"}

        if stream is True:
            return StreamingResponse(
                content=generate_audio_stream(
                    processor=processor, format=response_format, sample_rate=sample_rate
                ),
                media_type=content_type,
                headers=headers,
            )
        else:
            audio = b""
            async for chunk in generate_audio_stream(
                processor=processor, format=response_format, sample_rate=sample_rate
            ):
                audio += chunk
            return Response(
                content=audio,
                media_type=content_type,
                headers=headers,
            )
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.post(f"/v1/audio/inference")
async def inference(
    input: Annotated[
        str,
        Form(
            min_length=1,
            max_length=4096,
            description="The text to generate audio for. The maximum length is 4096 characters.",
        ),
    ],
    model: Annotated[str, Field(description="ID of the model to use.")] = "CosyVoice2",
    reference_file: Annotated[
        UploadFile | None,
        File(
            description=(
                "Reference audio file for voice cloning."
                "Requirements:"
                "  - Format: WAV/MP3 (16kHz, mono recommended)"
                "  - Duration: 5-30 seconds of clear speech"
                "  - Content: Neutral reading (avoid emotions/background noise)"
            )
        ),
    ] = None,
    reference_text: Annotated[
        str | None,
        Form(
            min_length=1,
            description=(
                "Transcript of the reference audio (`reference_file`)."
                "Guidelines:"
                "  - Must EXACTLY match the spoken content in the audio"
                "  - Language: Consistent with the TTS model's supported language"
                "  - Avoid special symbols or abbreviations"
                "  - Example: The quick brown fox jumps over the lazy dog."
            ),
        ),
    ] = None,
    voice: Annotated[
        str | None,
        Form(
            description="The voice to use when generating the audio.",
        ),
    ] = None,
    instructions: Annotated[
        str | None,
        Form(
            description="Control the voice of your generated audio with additional instructions.",
        ),
    ] = None,
    response_format: Annotated[
        AudioFormat,
        Form(
            description="The format to audio in. Supported formats are mp3, opus, aac, flac, wav, and pcm.",
        ),
    ] = AudioFormat.WAV,
    stream: Annotated[
        bool,
        Form(
            description="If set to true, the model response data will be streamed to the client as it is generated.",
        ),
    ] = False,
    speed: Annotated[
        float,
        Form(
            description="The speed of the generated audio. Select a value from 0.25 to 4.0. 1.0 is the default.",
        ),
    ] = 1.0,
    sample_rate: Annotated[
        Literal[
            "8000",
            "16000",
            "24000",
            "32000",
            "44100",
            "48000",
            "64000",
            "96000",
        ],
        Form(
            description="The sample rate of the generated audio. Select a value from 8000 to 96000. 16000 is the default.",
        ),
    ] = "16000",
    cross_lingual_language: Annotated[
        bool | None,
        Form(
            description="The language of the input text when using cross-lingual TTS. ",
        ),
    ] = None,
):
    """Generates audio from the input text."""
    if voice:
        if instructions:
            processor = cosyvoice.inference_instruct2_by_spk_id(
                tts_text=input,
                instruct_text=instructions,
                spk_id=voice,
                stream=stream,
                speed=speed,
                text_frontend=True,
            )
        else:
            processor = cosyvoice.inference_zero_shot_by_spk_id(
                tts_text=input,
                spk_id=voice,
                stream=stream,
                speed=speed,
                text_frontend=True,
            )
    else:
        if reference_file:
            audio_bytes = await reference_file.read()
            audio = load_audio_from_bytes(audio_bytes)

            if cross_lingual_language is True:
                processor = cosyvoice.inference_cross_lingual(
                    tts_text=input,
                    prompt_speech_16k=audio,
                    stream=stream,
                    speed=speed,
                    text_frontend=True,
                )
            elif reference_text:
                processor = cosyvoice.inference_zero_shot(
                    tts_text=input,
                    prompt_text=reference_text,
                    prompt_speech_16k=audio,
                    stream=stream,
                    speed=speed,
                    text_frontend=True,
                )
            elif instructions:
                processor = cosyvoice.inference_instruct2(
                    tts_text=input,
                    instruct_text=instructions,
                    prompt_speech_16k=audio,
                    stream=stream,
                    speed=speed,
                    text_frontend=True,
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "Missing required parameter: 'reference_text' or 'instructions'"
                    },
                )
        else:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Missing required parameter: 'voice' or 'reference_file'"
                },
            )

    try:
        content_type = get_content_type(
            format=response_format, sample_rate=int(sample_rate)
        )
        headers = {"Content-Disposition": f"attachment; filename=audio.wav"}

        if stream is True:
            return StreamingResponse(
                content=generate_audio_stream(
                    processor=processor,
                    format=response_format,
                    sample_rate=int(sample_rate),
                ),
                media_type=content_type,
                headers=headers,
            )
        else:
            audio = b""
            async for chunk in generate_audio_stream(
                processor=processor,
                format=response_format,
                sample_rate=int(sample_rate),
            ):
                audio += chunk
            return Response(
                content=audio,
                media_type=content_type,
                headers=headers,
            )
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.post("/v1/audio/voice")
async def upload_voice(
    voice: Annotated[
        str,
        Form(
            description="The voice to be used.",
        ),
    ],
    reference_file: Annotated[
        UploadFile,
        File(
            description=(
                "Reference audio file for voice cloning."
                "Requirements:"
                "  - Format: WAV/MP3 (16kHz, mono recommended)"
                "  - Duration: 5-30 seconds of clear speech"
                "  - Content: Neutral reading (avoid emotions/background noise)"
            ),
        ),
    ],
    reference_text: Annotated[
        str,
        Form(
            min_length=1,
            description=(
                "Transcript of the reference audio (`reference_file`)."
                "Guidelines:"
                "  - Must EXACTLY match the spoken content in the audio"
                "  - Language: Consistent with the TTS model's supported language"
                "  - Avoid special symbols or abbreviations"
                "  - Example: The quick brown fox jumps over the lazy dog."
            ),
        ),
    ],
    name: Annotated[
        str | None,
        Form(
            description="The name of the voice.",
        ),
    ] = None,
):
    """Create a voice by you."""
    try:
        audio_data = await reference_file.read()
        voice = save_voice_data(
            voice=voice, audio_data=audio_data, text=reference_text, name=name
        )
        return Response()
    except ValidationError as ve:
        raise HTTPException(422, detail=ve.errors())
    except Exception as e:
        logging.error(f"Create Failed: {str(e)}")
        raise HTTPException(500, detail=str(e))


@app.get(f"/v1/health", response_class=Response)
async def check_health():
    return Response()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=50001)
    parser.add_argument(
        "--model_dir",
        type=str,
        default="../../../pretrained_models/CosyVoice2-0.5B",
        help="local path or modelscope repo id",
    )
    parser.add_argument("--load_jit", action="store_true", help="load jit model")
    parser.add_argument("--load_trt", action="store_true", help="load tensorrt model")
    parser.add_argument("--fp16", action="store_true", help="use fp16")
    args = parser.parse_args()

    cosyvoice = AsyncCosyVoice2(
        args.model_dir, load_jit=args.load_jit, load_trt=args.load_trt, fp16=args.fp16
    )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
