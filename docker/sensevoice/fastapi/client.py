import os
import requests
from typing import List, Optional
from enum import Enum
from pathlib import Path
import soundfile as sf
import io


class Language(str, Enum):
    auto = "auto"
    zh = "zh"
    en = "en"
    yue = "yue"
    ja = "ja"
    ko = "ko"
    nospeech = "nospeech"


class ASRClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        初始化ASR客户端

        Args:
            base_url: ASR服务的基础URL (默认: http://localhost:8000)
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def transcribe(
        self,
        audio_paths: List[str],
        keys: Optional[List[str]] = None,
        lang: Language = Language.auto,
        sample_rate: int = 16000,
    ) -> dict:
        """
        调用ASR接口进行语音识别

        Args:
            audio_paths: 音频文件路径列表
            keys: 每个音频对应的名称列表 (可选)
            lang: 语言类型 (默认: auto)
            sample_rate: 音频采样率 (默认: 16000)

        Returns:
            dict: 识别结果
        """
        # 准备文件数据
        files = []
        for path in audio_paths:
            # 读取并确保音频为16kHz单声道
            data, sr = sf.read(path, dtype="float32")
            if sr != sample_rate:
                raise ValueError(f"音频采样率应为{sample_rate}Hz，当前为{sr}Hz")
            if len(data.shape) > 1:
                data = data.mean(axis=1)  # 转为单声道

            # 转换为WAV格式字节流
            buffer = io.BytesIO()
            sf.write(buffer, data, sample_rate, format="WAV")
            files.append(("files", buffer.getvalue()))
            buffer.close()

        # 准备表单数据
        data = {
            "lang": lang.value if isinstance(lang, Language) else lang,
            "keys": (
                ",".join(keys)
                if keys
                else ",".join([Path(p).stem for p in audio_paths])
            ),
        }

        # 发送请求
        response = self.session.post(
            f"{self.base_url}/v1/asr/sensevoice/transcribe",
            files=files,
            data=data,
            verify=False,
        )

        if response.status_code != 200:
            raise Exception(f"ASR请求失败: {response.status_code} - {response.text}")

        return response.json()

    def close(self):
        """关闭会话"""
        self.session.close()


# 使用示例
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ASR客户端")
    parser.add_argument("audio_files", nargs="+", help="音频文件路径")
    parser.add_argument(
        "--lang",
        type=str,
        default="auto",
        choices=[e.value for e in Language],
        help="语言类型 (默认: auto)",
    )
    parser.add_argument(
        "--server",
        type=str,
        default="http://localhost:50000",
        help="ASR服务器地址 (默认: http://localhost:50000)",
    )
    args = parser.parse_args()

    client = ASRClient(args.server)
    try:
        # 调用ASR服务
        result = client.transcribe(args.audio_files, lang=args.lang)

        # 打印结果
        print("识别结果:")
        for item in result.get("result", []):
            print(f"\n音频: {item.get('key', 'unknown')}")
            print(f"原始文本: {item.get('raw_text', '')}")
            print(f"处理后文本: {item.get('text', '')}")
            print(f"干净文本: {item.get('clean_text', '')}")
            print("-" * 50)

    except Exception as e:
        print(f"发生错误: {str(e)}")
    finally:
        client.close()
