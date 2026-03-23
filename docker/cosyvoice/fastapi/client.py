import os
import time
import httpx
import requests
import argparse
import numpy as np
import soundfile as sf
from typing import AsyncIterator, Iterator, Optional


class CosyVoiceClient:
    def __init__(self, base_url: str = "http://localhost:50001"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def text_to_speech_sync(
        self,
        mode: str,
        text: str,
        instruct: Optional[str] = None,
        voice: str = "兰溪",
        stream: bool = True,
        speed: float = 1.0,
    ) -> Iterator[bytes]:
        """发送文本到语音合成请求

        Args:
            text: 要合成的文本内容
            voice: 音色ID或URI (默认: "兰溪")
            output_file: 输出文件路径 (可选)
            speed: 语速 (0.25-4.0)

        Returns:
            音频二进制数据
        """
        url = f"{self.base_url}/v1/tts/cosyvoice/inference"

        payload = {
            "mode": mode,
            "text": text,
            "instruct": instruct,
            "voice": voice,
            "stream": stream,
            "speed": speed,
        }

        try:
            # 流式接收响应
            start_time = time.time()
            with self.session.post(url, json=payload, stream=True) as response:
                response.raise_for_status()

                # 流式写入文件
                first_bytes_time = None

                for chunk in response.iter_content():
                    if not first_bytes_time:
                        first_bytes_time = time.time()
                    yield chunk

                print(f"first bytes latency: {first_bytes_time-start_time:.2f}")  # type: ignore
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
            raise

    async def text_to_speech(
        self,
        mode: str,
        text: str,
        instruct: Optional[str] = None,
        voice: str = "兰溪",
        stream: bool = True,
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """发送文本到语音合成请求

        Args:
            text: 要合成的文本内容
            voice: 音色ID或URI (默认: "兰溪")
            output_file: 输出文件路径 (可选)
            response_format: 音频格式 (mp3/wav)
            speed: 语速 (0.25-4.0)

        Returns:
            音频二进制数据
        """
        url = f"{self.base_url}/v1/tts/cosyvoice/inference"

        payload = {
            "mode": mode,
            "text": text,
            "instruct": instruct,
            "voice": voice,
            "stream": stream,
            "speed": speed,
        }
        start_time = time.time()
        first_bytes_time = None
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                async with client.stream(
                    method="POST",
                    url=url,
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for chunk in response.aiter_bytes():
                        if not first_bytes_time:
                            first_bytes_time = time.time()
                            print(
                                f"First bytes lantency: {first_bytes_time - start_time:.2f}"
                            )
                        yield chunk

            except Exception as e:
                print(f"请求失败: {e}")
                raise e


async def main():
    parser = argparse.ArgumentParser(description="CosyVoice 客户端测试工具")
    parser.add_argument(
        "--mode",
        default="zero_shot",
        choices=["zero_shot", "instruct"],
        help="Inrefence mode",
    )
    parser.add_argument("--text", type=str, required=True, help="要合成的文本内容")
    parser.add_argument("--instruct", type=str, default="使用四川话说")
    parser.add_argument("--output", type=str, help="输出文件路径 (如: output.mp3)")
    parser.add_argument(
        "--voice", type=str, default="兰溪", help="音色ID或URI (默认: 兰溪)"
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="语速 (0.25-4.0, 默认: 1.0)"
    )
    parser.add_argument(
        "--server",
        type=str,
        default="http://localhost:50001",
        help="服务器地址 (默认: http://localhost:50001)",
    )

    args = parser.parse_args()

    client = CosyVoiceClient(args.server)

    print(f"正在合成: {args.text}")
    print(f"音色: {args.voice}")
    print(f"格式: {args.format}")
    print(f"语速: {args.speed}")

    # 调用合成接口
    if args.output:
        # 确保目录存在
        if os.path.dirname(args.output):
            os.makedirs(os.path.dirname(args.output), exist_ok=True)

    total_size = 0
    raw_audio = b""
    async for chunk in client.text_to_speech(
        # for chunk in client.text_to_speech_sync(
        mode=args.mode,
        text=args.text,
        instruct=args.instruct,
        voice=args.voice,
        stream=True,
        speed=args.speed,
    ):
        total_size += len(chunk)
        raw_audio += chunk

    tts_array = np.frombuffer(raw_audio, dtype=np.int16).reshape(1, -1)

    sf.write(file=args.output, data=tts_array.T, samplerate=24000)

    print(f"总接收数据: {total_size} bytes")
    print(f"音频已保存到: {args.output}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
