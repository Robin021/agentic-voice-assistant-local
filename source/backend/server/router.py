import httpx
import openai
import litellm
import asyncio
import traceback
import contextvars
from functools import partial
from litellm.main import (
    openai_chat_completions,
    azure_chat_completions,
    vertex_text_to_speech,
)
from litellm.utils import client
from litellm.router import Router as _Router
from litellm.types.router import GenericLiteLLMParams
from litellm.types.utils import TranscriptionResponse
from litellm.types.llms.openai import HttpxBinaryResponseContent
from litellm._logging import verbose_router_logger
from litellm.router_utils.handle_error import send_llm_exception_alert
from litellm.litellm_core_utils.core_helpers import _get_parent_otel_span_from_kwargs
from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider
from litellm.litellm_core_utils.get_litellm_params import get_litellm_params
from litellm.litellm_core_utils.exception_mapping_utils import exception_type
from litellm.secret_managers.main import get_secret, get_secret_str

from llms import FunASRCosyVoiceAPI


funasr_cosyvoice = FunASRCosyVoiceAPI()


class Router(_Router):
    def transcription(self, model: str, file: bytes, **kwargs) -> TranscriptionResponse:
        """
        Example usage:
        response = router.transcription(model="gpt-3.5-turbo", file=b"")
        """
        try:
            verbose_router_logger.debug(f"router.transcription(model={model},..)")
            kwargs["model"] = model
            kwargs["file"] = file
            kwargs["original_function"] = self._transcription
            self._update_kwargs_before_fallbacks(model=model, kwargs=kwargs)

            response = self.function_with_fallbacks(**kwargs)
            return response
        except Exception as e:
            raise e

    def _transcription(
        self, model: str, file: bytes, **kwargs
    ) -> TranscriptionResponse:
        model_name = model
        try:
            verbose_router_logger.debug(
                f"Inside _atranscription()- model: {model}; kwargs: {kwargs}"
            )
            parent_otel_span = _get_parent_otel_span_from_kwargs(kwargs)
            deployment = self.get_available_deployment(
                model=model,
                messages=[{"role": "user", "content": "prompt"}],
                specific_deployment=kwargs.pop("specific_deployment", None),
                request_kwargs=kwargs,
            )

            self._update_kwargs_with_deployment(deployment=deployment, kwargs=kwargs)
            data = deployment["litellm_params"].copy()
            model_client = self._get_client(
                deployment=deployment,
                kwargs=kwargs,
            )

            self.total_calls[model_name] += 1
            response: TranscriptionResponse = litellm.transcription(
                **{
                    **data,
                    "file": file,
                    "caching": self.cache_responses,
                    "client": model_client,
                    **kwargs,
                }
            )  # type: ignore

            self.success_calls[model_name] += 1
            verbose_router_logger.info(
                f"litellm.transcription(model={model_name})\033[32m 200 OK\033[0m"
            )
            return response
        except Exception as e:
            verbose_router_logger.info(
                f"litellm.transcription(model={model_name})\033[31m Exception {str(e)}\033[0m"
            )
            if model_name is not None:
                self.fail_calls[model_name] += 1
            raise e

    def speech(
        self, model: str, input: str, voice: str | None = None, **kwargs
    ) -> HttpxBinaryResponseContent:
        """
        Example Usage:

        ```
        from litellm import Router
        client = Router(model_list = [
            {
                "model_name": "tts",
                "litellm_params": {
                    "model": "tts-1",
                },
            },
        ])

        async with client.speech(
            model="tts",
            voice="alloy",
            input="the quick brown fox jumped over the lazy dogs",
            api_base=None,
            api_key=None,
            organization=None,
            project=None,
            max_retries=1,
            timeout=600,
            client=None,
            optional_params={},
        ) as response:
            response.stream_to_file(speech_file_path)

        ```
        """
        try:
            kwargs["input"] = input
            kwargs["voice"] = voice

            deployment = self.get_available_deployment(
                model=model,
                messages=[{"role": "user", "content": "prompt"}],
                specific_deployment=kwargs.pop("specific_deployment", None),
                request_kwargs=kwargs,
            )
            self._update_kwargs_before_fallbacks(model=model, kwargs=kwargs)
            data = deployment["litellm_params"].copy()
            data["model"]
            for k, v in self.default_litellm_params.items():
                if (
                    k not in kwargs
                ):  # prioritize model-specific params > default router params
                    kwargs[k] = v
                elif k == "metadata":
                    kwargs[k].update(v)

            potential_model_client = self._get_client(
                deployment=deployment, kwargs=kwargs, client_type="async"
            )
            # check if provided keys == client keys #
            dynamic_api_key = kwargs.get("api_key", None)
            if (
                dynamic_api_key is not None
                and potential_model_client is not None
                and dynamic_api_key != potential_model_client.api_key
            ):
                model_client = None
            else:
                model_client = potential_model_client

            response = self._speech(
                **{
                    **data,
                    "client": model_client,
                    **kwargs,
                }
            )
            return response
        except Exception as e:
            asyncio.create_task(
                send_llm_exception_alert(
                    litellm_router_instance=self,
                    request_kwargs=kwargs,
                    error_traceback_str=traceback.format_exc(),
                    original_exception=e,
                )
            )
            raise e

    @client
    def _speech(
        self,
        model: str,
        input: str,
        voice: str | dict | None = None,
        stream: bool | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        max_retries: int | None = None,
        metadata: dict | None = None,
        timeout: float | httpx.Timeout | None = None,
        response_format: str | None = None,
        speed: int | None = None,
        instructions: str | None = None,
        sample_rate: int | None = None,
        client=None,
        headers: dict | None = None,
        custom_llm_provider: str | None = None,
        aspeech: bool | None = None,
        **kwargs,
    ) -> HttpxBinaryResponseContent:
        user = kwargs.get("user", None)
        litellm_call_id: str | None = kwargs.get("litellm_call_id", None)
        proxy_server_request = kwargs.get("proxy_server_request", None)
        extra_headers = kwargs.get("extra_headers", None)
        model_info = kwargs.get("model_info", None)
        model, custom_llm_provider, dynamic_api_key, api_base = get_llm_provider(
            model=model, custom_llm_provider=custom_llm_provider, api_base=api_base
        )  # type: ignore
        kwargs.pop("tags", [])

        optional_params = {}
        if response_format is not None:
            optional_params["response_format"] = response_format
        if speed is not None:
            optional_params["speed"] = speed  # type: ignore
        if instructions is not None:
            optional_params["instructions"] = instructions
        if timeout is None:
            timeout = litellm.request_timeout  # type: ignore

        if max_retries is None:
            max_retries = litellm.num_retries or openai.DEFAULT_MAX_RETRIES
        litellm_params_dict = get_litellm_params(**kwargs)
        logging_obj = kwargs.get("litellm_logging_obj", None)
        logging_obj.update_environment_variables(  # type: ignore
            model=model,
            user=user,
            optional_params={},
            litellm_params={
                "litellm_call_id": litellm_call_id,
                "proxy_server_request": proxy_server_request,
                "model_info": model_info,
                "metadata": metadata,
                "preset_cache_key": None,
                "stream_response": {},
                **kwargs,
            },
            custom_llm_provider=custom_llm_provider,
        )
        response: HttpxBinaryResponseContent | None = None
        if (
            custom_llm_provider == "openai"
            or custom_llm_provider in litellm.openai_compatible_providers  # type: ignore
        ):
            if voice is None or not (isinstance(voice, str)):
                raise litellm.BadRequestError(  # type: ignore
                    message="'voice' is required to be passed as a string for OpenAI TTS",
                    model=model,
                    llm_provider=custom_llm_provider,
                )
            api_base = (
                api_base  # for deepinfra/perplexity/anyscale/groq/friendliai we check in get_llm_provider and pass in the api base from there
                or litellm.api_base
                or get_secret("OPENAI_BASE_URL")
                or get_secret("OPENAI_API_BASE")
                or "https://api.openai.com/v1"
            )  # type: ignore
            # set API KEY
            api_key = (
                api_key
                or litellm.api_key  # for deepinfra/perplexity/anyscale we check in get_llm_provider and pass in the api key from there
                or litellm.openai_key
                or get_secret("OPENAI_API_KEY")
            )  # type: ignore

            organization = (
                organization
                or litellm.organization
                or get_secret("OPENAI_ORGANIZATION")
                or None  # default - https://github.com/openai/openai-python/blob/284c1799070c723c6a553337134148a7ab088dd8/openai/util.py#L105
            )  # type: ignore

            project = (
                project
                or litellm.project
                or get_secret("OPENAI_PROJECT")
                or None  # default - https://github.com/openai/openai-python/blob/284c1799070c723c6a553337134148a7ab088dd8/openai/util.py#L105
            )  # type: ignore

            headers = headers or litellm.headers

            response = openai_chat_completions.audio_speech(
                model=model,
                input=input,
                voice=voice,
                optional_params=optional_params,
                api_key=api_key,
                api_base=api_base,
                organization=organization,
                project=project,
                max_retries=max_retries,
                timeout=timeout,
                client=client,  # pass AsyncOpenAI, OpenAI client
                aspeech=aspeech,
            )
        elif custom_llm_provider == "azure":
            # azure configs
            if voice is None or not (isinstance(voice, str)):
                raise litellm.BadRequestError(  # type: ignore
                    message="'voice' is required to be passed as a string for Azure TTS",
                    model=model,
                    llm_provider=custom_llm_provider,
                )
            api_base = api_base or litellm.api_base or get_secret("AZURE_API_BASE")  # type: ignore

            api_version = api_version or litellm.api_version or get_secret("AZURE_API_VERSION")  # type: ignore

            api_key = (
                api_key
                or litellm.api_key
                or litellm.azure_key
                or get_secret("AZURE_OPENAI_API_KEY")
                or get_secret("AZURE_API_KEY")
            )  # type: ignore

            azure_ad_token: str | None = optional_params.get("extra_body", {}).pop(  # type: ignore
                "azure_ad_token", None
            ) or get_secret(
                "AZURE_AD_TOKEN"
            )
            azure_ad_token_provider = kwargs.get("azure_ad_token_provider", None)

            if extra_headers:
                optional_params["extra_headers"] = extra_headers

            response = azure_chat_completions.audio_speech(
                model=model,
                input=input,
                voice=voice,
                optional_params=optional_params,
                api_key=api_key,
                api_base=api_base,
                api_version=api_version,
                azure_ad_token=azure_ad_token,
                azure_ad_token_provider=azure_ad_token_provider,
                organization=organization,
                max_retries=max_retries,
                timeout=timeout,
                client=client,  # pass AsyncOpenAI, OpenAI client
                aspeech=aspeech,
                litellm_params=litellm_params_dict,
            )
        elif (
            custom_llm_provider == "vertex_ai"
            or custom_llm_provider == "vertex_ai_beta"
        ):
            generic_optional_params = GenericLiteLLMParams(**kwargs)

            api_base = generic_optional_params.api_base or ""
            vertex_ai_project = (
                generic_optional_params.vertex_project
                or litellm.vertex_project
                or get_secret_str("VERTEXAI_PROJECT")
            )
            vertex_ai_location = (
                generic_optional_params.vertex_location
                or litellm.vertex_location
                or get_secret_str("VERTEXAI_LOCATION")
            )
            vertex_credentials = (
                generic_optional_params.vertex_credentials
                or get_secret_str("VERTEXAI_CREDENTIALS")
            )

            if voice is not None and not isinstance(voice, dict):
                raise litellm.BadRequestError(  # type: ignore
                    message=f"'voice' is required to be passed as a dict for Vertex AI TTS, passed in voice={voice}",
                    model=model,
                    llm_provider=custom_llm_provider,
                )
            if "gemini" in model:
                from litellm.endpoints.speech.speech_to_completion_bridge.handler import (
                    speech_to_completion_bridge_handler,
                )

                return speech_to_completion_bridge_handler.speech(
                    model=model,
                    input=input,
                    voice=voice,
                    optional_params=optional_params,
                    litellm_params=litellm_params_dict,
                    headers=headers or {},
                    logging_obj=logging_obj,  # type: ignore
                    custom_llm_provider=custom_llm_provider,
                )
            response = vertex_text_to_speech.audio_speech(
                _is_async=aspeech,
                vertex_credentials=vertex_credentials,
                vertex_project=vertex_ai_project,
                vertex_location=vertex_ai_location,
                timeout=timeout,
                api_base=api_base,
                model=model,
                input=input,
                voice=voice,
                optional_params=optional_params,
                kwargs=kwargs,
                logging_obj=logging_obj,
            )
        elif custom_llm_provider == "gemini":
            from litellm.endpoints.speech.speech_to_completion_bridge.handler import (
                speech_to_completion_bridge_handler,
            )

            return speech_to_completion_bridge_handler.speech(
                model=model,
                input=input,
                voice=voice,
                optional_params=optional_params,
                litellm_params=litellm_params_dict,
                headers=headers or {},
                logging_obj=logging_obj,  # type: ignore
                custom_llm_provider=custom_llm_provider,
            )
        elif custom_llm_provider == "funasr":
            if not voice or not isinstance(voice, str):
                raise litellm.BadRequestError(  # type: ignore
                    message=f"'voice' is required to be passed as a str for CosyVoice, passed in voice={voice}",
                    model=model,
                    llm_provider=custom_llm_provider,
                )
            if not api_base or not isinstance(api_base, str):
                raise litellm.BadRequestError(  # type: ignore
                    message=f"'api_base' is required for CosyVoice, passed in api_base={api_base}",
                    model=model,
                    llm_provider=custom_llm_provider,
                )

            if sample_rate is not None:
                optional_params["sample_rate"] = sample_rate

            response = funasr_cosyvoice.speech(
                model=model,
                input=input,
                voice=voice,
                optional_params=optional_params,
                api_base=api_base,
                timeout=timeout,
                client=client,  # pass AsyncOpenAI, OpenAI client
                stream=stream,
                litellm_params=litellm_params_dict,
                aspeech=aspeech,
            )

        if response is None:
            raise Exception(
                "Unable to map the custom llm provider={} to a known provider={}.".format(
                    custom_llm_provider, litellm.provider_list
                )
            )
        return response

    async def aspeech(
        self, model: str, input: str, voice: str, **kwargs
    ) -> HttpxBinaryResponseContent:
        """
        Example Usage:

        ```
        from litellm import Router
        client = Router(model_list = [
            {
                "model_name": "tts",
                "litellm_params": {
                    "model": "tts-1",
                },
            },
        ])

        async with client.aspeech(
            model="tts",
            voice="alloy",
            input="the quick brown fox jumped over the lazy dogs",
            api_base=None,
            api_key=None,
            organization=None,
            project=None,
            max_retries=1,
            timeout=600,
            client=None,
            optional_params={},
        ) as response:
            response.stream_to_file(speech_file_path)

        ```
        """
        try:
            kwargs["input"] = input
            kwargs["voice"] = voice

            deployment = await self.async_get_available_deployment(
                model=model,
                messages=[{"role": "user", "content": "prompt"}],
                specific_deployment=kwargs.pop("specific_deployment", None),
                request_kwargs=kwargs,
            )
            self._update_kwargs_before_fallbacks(model=model, kwargs=kwargs)
            data = deployment["litellm_params"].copy()
            data["model"]
            for k, v in self.default_litellm_params.items():
                if (
                    k not in kwargs
                ):  # prioritize model-specific params > default router params
                    kwargs[k] = v
                elif k == "metadata":
                    kwargs[k].update(v)

            potential_model_client = self._get_client(
                deployment=deployment, kwargs=kwargs, client_type="async"
            )
            # check if provided keys == client keys #
            dynamic_api_key = kwargs.get("api_key", None)
            if (
                dynamic_api_key is not None
                and potential_model_client is not None
                and dynamic_api_key != potential_model_client.api_key
            ):
                model_client = None
            else:
                model_client = potential_model_client

            response = await self._aspeech(
                **{
                    **data,
                    "client": model_client,
                    **kwargs,
                }
            )
            return response
        except Exception as e:
            asyncio.create_task(
                send_llm_exception_alert(
                    litellm_router_instance=self,
                    request_kwargs=kwargs,
                    error_traceback_str=traceback.format_exc(),
                    original_exception=e,
                )
            )
            raise e

    @client
    async def _aspeech(self, *args, **kwargs) -> HttpxBinaryResponseContent:
        """
        Calls openai tts endpoints.
        """
        loop = asyncio.get_event_loop()
        model = args[0] if len(args) > 0 else kwargs["model"]
        ### PASS ARGS TO Image Generation ###
        kwargs["aspeech"] = True
        custom_llm_provider = kwargs.get("custom_llm_provider", None)
        try:
            # Use a partial function to pass your keyword arguments
            func = partial(self.speech, *args, **kwargs)

            # Add the context to the function
            ctx = contextvars.copy_context()
            func_with_context = partial(ctx.run, func)

            _, custom_llm_provider, _, _ = get_llm_provider(
                model=model, api_base=kwargs.get("api_base", None)
            )

            # Await normally
            init_response = await loop.run_in_executor(None, func_with_context)
            if asyncio.iscoroutine(init_response):
                response = await init_response
            else:
                # Call the synchronous function using run_in_executor
                response = await loop.run_in_executor(None, func_with_context)
            return response  # type: ignore
        except Exception as e:
            custom_llm_provider = custom_llm_provider or "openai"
            raise exception_type(
                model=model,
                custom_llm_provider=custom_llm_provider,
                original_exception=e,
                completion_kwargs=args,
                extra_kwargs=kwargs,
            )


router = Router()
