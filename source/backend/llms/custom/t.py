import json
import boto3
import httpx
from typing import Optional, Union, Callable, Iterator, AsyncIterator
from litellm.types.utils import ModelResponse, GenericStreamingChunk, Choices, Message
from litellm.llms.custom_llm import CustomLLM, CustomLLMError
from litellm.llms.custom_httpx.http_handler import (
    AsyncHTTPHandler,
    HTTPHandler,
)
from litellm.llms.sagemaker.chat.handler import SagemakerChatHandler
from litellm._logging import verbose_logger


class MiniAssistantLLM(SagemakerChatHandler, CustomLLM):
    def __init__(self) -> None:
        super().__init__()
        self.sagemaker_runtime = None

    def completion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout: Optional[Union[float, httpx.Timeout]] = 120,
        client: Optional[HTTPHandler] = None,
    ) -> ModelResponse:
        content = ""
        for chunk in self.streaming(
            model=model,
            messages=messages,
            api_base=api_base,
            custom_prompt_dict=custom_prompt_dict,
            model_response=model_response,
            print_verbose=print_verbose,
            encoding=encoding,
            api_key=api_key,
            logging_obj=logging_obj,
            optional_params=optional_params,
            acompletion=acompletion,
            litellm_params=litellm_params,
            logger_fn=logger_fn,
            headers=headers,
            timeout=timeout,
            client=client,
        ):
            content += chunk["text"]
        return ModelResponse(
            stream=False,
            choices=[
                Choices(index=0, message=Message(content=content), finish_reason="stop")
            ],
        )

    def streaming(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[HTTPHandler] = None,
    ) -> Iterator[GenericStreamingChunk]:
        if self.sagemaker_runtime is None:
            credentials = optional_params.pop("credentials", None)
            aws_access_key_id = credentials.get("aws_access_key_id", None)
            aws_secret_access_key = credentials.get("aws_secret_access_key", None)
            aws_session_token = credentials.get("aws_session_token", None)
            aws_region_name = credentials.get("aws_region_name", None)

            # Initialize the SageMaker runtime client if not already done
            self.sagemaker_runtime = boto3.client(
                "sagemaker-runtime",
                region_name=aws_region_name,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
            )

        try:
            payload = dict(
                stream=True,
                query=messages[-1]["content"],
                userid="",
                button_id="",
                query_type="text",
                topic="",
            )
            payload.update(optional_params.get("additional_params", {}))

            response = self.sagemaker_runtime.invoke_endpoint_with_response_stream(
                EndpointName=model,
                Body=json.dumps(payload),
                ContentType="application/json",
            )
            verbose_logger.debug(f"response: {response}")

            event_stream_buffer = ""
            accumulated_json = ""

            event_stream = response["Body"]
            for event in event_stream:
                try:
                    verbose_logger.debug(f"event: {event}")
                    if "PayloadPart" not in event:
                        continue

                    # Decode and process each chunk
                    chunk = event["PayloadPart"]["Bytes"].decode("utf-8")
                    verbose_logger.debug(f"chunk: {chunk}")

                    event_stream_buffer += chunk

                    if "\n\n" not in event_stream_buffer:
                        continue

                    _event_stream_buffer_list = event_stream_buffer.split("\n\n")

                    accumulated_json = _event_stream_buffer_list[0][6:].strip()
                    verbose_logger.debug(f"accumulated_json: {accumulated_json}")
                    event_stream_buffer = "\n\n".join(_event_stream_buffer_list[1:])

                    if accumulated_json.startswith("[DONE]"):
                        event_stream_buffer = ""
                        break

                    chunk_data = json.loads(accumulated_json)
                    verbose_logger.debug(f"chunk_data: {chunk_data}")

                    for choice in chunk_data.get("choices", []):
                        verbose_logger.debug(f"choice: {choice}")
                        yield GenericStreamingChunk(
                            text=choice.get("delta", {}).get("content", ""),
                            index=choice.get("index", 0),
                            is_finished=choice.get("finish_reason") is not None,
                            finish_reason=choice.get("finish_reason"),
                            usage={
                                "completion_tokens": 0,
                                "prompt_tokens": 0,
                                "total_tokens": 0,
                            },
                        )
                except json.JSONDecodeError:
                    # If it's not valid JSON yet, continue to the next event
                    continue

            if event_stream_buffer:
                for message in event_stream_buffer.split("\n\n"):
                    accumulated_json = message[6:].strip()
                    verbose_logger.debug(f"accumulated_json: {accumulated_json}")

                    try:
                        chunk_data = json.loads(accumulated_json)
                        verbose_logger.debug(f"chunk_data: {chunk_data}")

                        for choice in chunk_data.get("choices", []):
                            verbose_logger.debug(f"choice: {choice}")
                            yield GenericStreamingChunk(
                                text=choice.get("delta", {}).get("content", ""),
                                index=choice.get("index", 0),
                                is_finished=choice.get("finish_reason") is not None,
                                finish_reason=choice.get("finish_reason"),
                                usage={
                                    "completion_tokens": 0,
                                    "prompt_tokens": 0,
                                    "total_tokens": 0,
                                },
                            )
                    except json.JSONDecodeError:
                        # If it's not valid JSON yet, continue to the next event
                        continue

        except Exception as e:
            # Catch-all for other unexpected errors
            raise CustomLLMError(
                status_code=500, message=f"Unexpected error during streaming: {str(e)}"
            )

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[AsyncHTTPHandler] = None,
    ) -> ModelResponse:
        return self.completion(
            model=model,
            messages=messages,
            api_base=api_base,
            custom_prompt_dict=custom_prompt_dict,
            model_response=model_response,
            print_verbose=print_verbose,
            encoding=encoding,
            api_key=api_key,
            logging_obj=logging_obj,
            optional_params=optional_params,
            acompletion=acompletion,
            litellm_params=litellm_params,
            logger_fn=logger_fn,
            headers=headers,
            timeout=timeout,
            client=client,  # type: ignore
        )

    async def astreaming(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[AsyncHTTPHandler] = None,
    ) -> AsyncIterator[GenericStreamingChunk]:
        for chunk in self.streaming(
            model=model,
            messages=messages,
            api_base=api_base,
            custom_prompt_dict=custom_prompt_dict,
            model_response=model_response,
            print_verbose=print_verbose,
            encoding=encoding,
            api_key=api_key,
            logging_obj=logging_obj,
            optional_params=optional_params,
            acompletion=acompletion,
            litellm_params=litellm_params,
            logger_fn=logger_fn,
            headers=headers,
            timeout=timeout,
            client=client,  # type: ignore
        ):
            yield chunk
