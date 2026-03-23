import httpx
import litellm
from typing import Any, Dict
from litellm.llms.base import BaseLLM
from litellm.types.llms.openai import HttpxBinaryResponseContent
from litellm.llms.custom_httpx.http_handler import (
    AsyncHTTPHandler,
    _get_httpx_client,
    get_async_httpx_client,
)


class FunASRCosyVoiceAPI(BaseLLM):
    def __init__(self) -> None:
        super().__init__()

    def speech(
        self,
        model: str,
        input: str,
        voice: str,
        optional_params: dict,
        api_base: str,
        timeout: float | httpx.Timeout,
        *args,
        stream: bool | None = None,
        client=None,
        aspeech: bool | None = None,
        litellm_params: dict | None = None,
        **kwargs,
    ) -> HttpxBinaryResponseContent:
        if client is None or isinstance(client, AsyncHTTPHandler):
            _params = {}
            if timeout is not None:
                if isinstance(timeout, float) or isinstance(timeout, int):
                    timeout = httpx.Timeout(timeout)
                _params["timeout"] = timeout
            client = _get_httpx_client(_params)  # type: ignore
        else:
            client = client

        if api_base.endswith("/"):
            api_base_url = api_base.rstrip("/")
        api_base_url = f"{api_base}/audio/speech"
        stream = True if stream else False
        data: Dict[str, Any] = dict(
            input=input, voice=voice, stream=True, **optional_params
        )

        if aspeech is True:
            return self.aspeech(
                model=model,
                input=input,
                voice=voice,
                optional_params=optional_params,
                api_base=api_base,
                timeout=timeout,
                *args,
                stream=stream,
                client=None,
                litellm_params=litellm_params,
            )  # type: ignore

        response = client.post(url=api_base_url, stream=stream, data=data)
        response.raise_for_status()
        return HttpxBinaryResponseContent(response=response)

    async def aspeech(
        self,
        model: str,
        input: str,
        voice: str,
        optional_params: dict,
        api_base: str,
        timeout: float | httpx.Timeout,
        *args,
        stream: bool | None = None,
        client=None,
        aspeech: bool | None = None,
        litellm_params: dict | None = None,
        **kwargs,
    ) -> HttpxBinaryResponseContent:
        if client is None or not isinstance(client, AsyncHTTPHandler):
            _params = {}
            if timeout is not None:
                if isinstance(timeout, float) or isinstance(timeout, int):
                    timeout = httpx.Timeout(timeout)
                _params["timeout"] = timeout
            client = get_async_httpx_client(params=_params, llm_provider=litellm.LlmProviders.CUSTOM)  # type: ignore
        else:
            client = client  # type: ignore

        if api_base.endswith("/"):
            api_base = api_base.rstrip("/")
        api_base_url = f"{api_base}/audio/speech"
        stream = True if stream else False
        data: Dict[str, Any] = dict(
            input=input, voice=voice, stream=stream, **optional_params
        )

        response = await client.post(url=api_base_url, stream=stream, json=data)
        response.raise_for_status()
        return HttpxBinaryResponseContent(response=response)
