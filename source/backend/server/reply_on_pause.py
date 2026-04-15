import time
import numpy as np
import secrets
import asyncio
import traceback
from typing import Any
from fastrtc.utils import (
    AdditionalOutputs,
    create_message,
    async_aggregate_bytes_to_16bit,
    wait_for_item,
)
from fastrtc.tracks import AsyncStreamHandler
from opentelemetry.trace import set_span_in_context
from opentelemetry.sdk.trace import Event as OTelEvent

from chat import (
    context_relevance_classifier,
    async_split_sentences,
    count_lexical_chars,
    conversations,
)
from voice.vad import VoiceActivityDetection
from logger import logger
from config import configure
from schemas import (
    Event,
    Opcode,
    EventName,
    AIMessage,
    HumanMessage,
    PipelineLatencyMetrics,
)
from prompts.template import apply_prompt
from constants import (
    TEXT_TO_SPEECH_MODEL_NAME,
    BASIC_LLM_MODEL_NAME,
)

from .trace import tracer
from .router import router
from .utils import atranscription, normalize_text, wait_for_event


class ReplyOnPause(AsyncStreamHandler):
    """
    A stream handler that processes incoming audio, detects pauses,
    and triggers a reply function (`fn`) when a pause is detected.

    This handler accumulates audio chunks, uses a Voice Activity Detection (VAD)
    model to determine speech segments, and identifies pauses based on configurable
    thresholds. Once a pause is detected after speech has started, it calls the
    provided generator function `fn` with the accumulated audio.

    It can optionally run a `startup_fn` at the beginning and supports interruption
    of the reply function if new audio arrives.

    Attributes:
        fn (ReplyFnGenerator): The generator function to call when a pause is detected.
        startup_fn (Callable | None): An optional function to run at startup.
        algo_options (AudioProcessingOptions): Configuration for the pause detection algorithm.
        model_options (ModelOptions | None): Configuration for the VAD model.
        can_interrupt (bool): Whether incoming audio can interrupt the `fn` execution.
        expected_layout (Literal["mono", "stereo"]): Expected audio channel layout.
        output_sample_rate (int): Sample rate for the output audio from `fn`.
        input_sample_rate (int): Expected sample rate of the input audio.
        model (PauseDetectionModel): The VAD model instance.
        state (AppState): The current state of the pause detection logic.
        generator (Generator | AsyncGenerator | None): The active generator instance from `fn`.
        event (Event): Threading event used to signal pause detection.
        loop (asyncio.AbstractEventLoop): The asyncio event loop.
    """

    def __init__(self):
        """
        Initializes the ReplyOnPause handler.

        Args:
            fn: The generator function to execute upon pause detection.
                It receives `(sample_rate, audio_array)` and optionally `*args`.
            startup_fn: An optional function to run once at the beginning.
            algo_options: Options for the pause detection algorithm.
            model_options: Options for the VAD model.
            can_interrupt: If True, incoming audio during `fn` execution
                will stop the generator and process the new audio.
            expected_layout: Expected input audio layout ('mono' or 'stereo').
            output_sample_rate: The sample rate expected for audio yielded by `fn`.
            output_frame_size: Deprecated.
            input_sample_rate: The expected sample rate of incoming audio.
            model: An optional pre-initialized VAD model instance.
            needs_args: Whether the reply function expects additional arguments.
        """
        super().__init__(
            expected_layout=configure.expected_audio_layout,
            output_sample_rate=configure.audio_output_sample_rate,
            input_sample_rate=configure.audio_input_sample_rate,
        )

        self.vad_model = VoiceActivityDetection(
            configure.voice_activity_detection_options
        )
        self.algo_options = configure.pause_detection_algorithm
        self.min_endpointing_delay = (
            configure.pause_detection_algorithm.min_endpointing_delay
        )
        self.can_interrupt = configure.allow_interruption
        self.output_sample_rate = configure.audio_output_sample_rate
        self.tts_output_sample_rate = configure.tts_output_sample_rate
        self.waiting_message_enabled = configure.waiting_message_enabled
        self.waiting_audio_cues = configure.waiting_audio_cues
        self.waiting_message_pool = configure.waiting_message_pool
        self.prompt_delay_threshold = configure.audio_prompt_delay_threshold
        self.greeting_message = configure.greeting_message.strip()
        self.chunk_size = int(self.tts_output_sample_rate * 0.1)

        self.interrupted: asyncio.Event = asyncio.Event()
        self.responding: bool = False
        self.started_talking: bool = False
        self.buffer: np.ndarray | None = None
        self.padding_buffer: np.ndarray | None = None
        self.padding_buffer_size: int = 2 * self.input_sample_rate
        self.speech_duration: float = 0.0
        self.last_speech_duration: float = 0.0
        self.endpointing_delay: float = 0.0
        self.startup_complete: bool = False
        self.should_shutdown: bool = False
        self.stop_waiting_flag: asyncio.Event = asyncio.Event()

        self.speech_recognition_queue: asyncio.Queue[Event] = asyncio.Queue()
        self.text_generation_queue: asyncio.Queue[Event] = asyncio.Queue()
        self.speech_synthesis_queue: asyncio.Queue[Event] = asyncio.Queue()
        self.output_queue: asyncio.Queue = asyncio.Queue()

        self.lock: asyncio.Lock = asyncio.Lock()

        self.speech_recognition_task = None
        self.text_generation_task = None
        self.text_generation_complete: asyncio.Event = asyncio.Event()
        self.speech_synthesis_task = None
        self.speech_synthesis_complete: asyncio.Event = asyncio.Event()

    async def start_up(self):
        """
        Executes the startup function `startup_fn` if provided.

        Waits for additional arguments if `_needs_additional_inputs` is True
        before calling `startup_fn`. Sets the `event` after completion.
        """
        # Start Speech Recognition
        self.speech_recognition_task = asyncio.create_task(
            self.speech_recognition_worker()
        )

        # Start LLM response generation
        self.text_generation_task = asyncio.create_task(self.text_generation_worker())

        # Start Speech synthesis
        self.speech_synthesis_task = asyncio.create_task(self.speech_synthesis_worker())

        await self.wait_for_args()
        self.conversation = conversations.get_or_create(
            conversation_id=self.conversation_id
        )
        self.session_span = tracer.start_span(
            name="conversation.session",
            attributes=dict(conversation_id=self.conversation_id),
        )

        if configure.greeting_enabled is True and self.greeting_message:
            self.conversation.add_ai_message(message=self.greeting_message)

            await self.output_queue.put(
                AdditionalOutputs([x.model_dump() for x in self.conversation.messages])
            )
            self.text_generation_complete.set()

            event = Event(
                span=tracer.start_span(
                    "conversation.interaction",
                    context=set_span_in_context(self.session_span),
                ),
                opcode=Opcode.TEXT,
                transcript=self.greeting_message,
                data=self.greeting_message,
                fin=True,
            )
            event.add_event(name=EventName.USER_STOPPED_TALKING.value)
            await self.speech_synthesis_queue.put(event)

        self.startup_complete = True

    async def shutdown(self):
        """Executes the shutdown function"""
        try:
            self.should_shutdown = True

            if (
                hasattr(self, "conversation_id")
                and conversations.exists(conversation_id=self.conversation_id) is True
            ):
                conversations.save(conversation_id=self.conversation_id)

            for queue in (
                self.speech_recognition_queue,
                self.text_generation_queue,
                self.speech_synthesis_queue,
                self.output_queue,
            ):
                while not queue.empty():
                    queue.get_nowait()

            if self.speech_recognition_task and not self.speech_recognition_task.done():
                await self.speech_recognition_queue.put(Event(opcode=Opcode.CLOSE))
                await self.speech_recognition_task

            if self.text_generation_task and not self.text_generation_task.done():
                await self.text_generation_queue.put(Event(opcode=Opcode.CLOSE))
                await self.text_generation_task

            if self.speech_synthesis_task and not self.speech_synthesis_task.done():
                await self.speech_synthesis_queue.put(Event(opcode=Opcode.CLOSE))
                await self.speech_synthesis_task
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error in shutdown: {e}")

    def set_args(self, args: list[Any]):
        """
        Sets additional arguments received (e.g., from UI components).

        Args:
            args: A list of arguments.
        """
        logger.debug("setting args in audio callback %s", args)
        self.latest_args = list(args)
        self.args_set.set()
        normalized_args = self.latest_args[1:8] if len(self.latest_args) >= 8 else self.latest_args[:7]
        if len(normalized_args) != 7:
            raise ValueError(
                f"Unexpected input args for ReplyOnPause.set_args: expected 7 values, got {len(normalized_args)} from {self.latest_args}"
            )
        (
            self.system_prompts,
            self.conversation_id,
            self.voice,
            self.instructions,
            self.language,
            self.can_interrupt,
            self.noise_suppression_enabled,
        ) = normalized_args

        if self.noise_suppression_enabled is True:
            self.min_endpointing_delay = min(
                self.min_endpointing_delay * 2, self.algo_options.max_endpointing_delay
            )

    def copy(self):
        """Creates a new instance of ReplyOnPause with the same configuration."""
        return self.__class__()

    async def play_waiting_feedback_worker(self):
        """Play waiting messages/audio while LLM is processing."""
        # Initial delay before playing waiting feedback
        await asyncio.sleep(self.prompt_delay_threshold)

        if self.stop_waiting_flag.is_set():
            return

        # Play random waiting message
        waiting_message_duration = 0.0

        self.responding = True
        if self.waiting_message_pool:
            async with self.lock:
                response = await router.aspeech(
                    model=TEXT_TO_SPEECH_MODEL_NAME,
                    input=normalize_text(
                        secrets.choice(self.waiting_message_pool[self.language]),
                    ),
                    voice=self.voice,
                    instructions=self.instructions,
                    response_format="pcm",
                    stream=True,
                )
                async for audio_chunk in async_aggregate_bytes_to_16bit(
                    await response.aiter_bytes(self.chunk_size)
                ):
                    await self.output_queue.put(
                        (self.tts_output_sample_rate, audio_chunk)
                    )
                    duration = (
                        np.atleast_2d(audio_chunk).shape[1]
                        / self.tts_output_sample_rate
                    )
                    waiting_message_duration = duration * 0.75

                await asyncio.sleep(waiting_message_duration)

        # Play background audio cues if still waiting
        sample_rate, waiting_audio = secrets.choice(configure.waiting_audio_cues)
        chunk_size = int(sample_rate * 0.02)  # 20ms chunks

        # Initialize flow control variables
        last_send_ts = None  # Timestamp of last send operation
        wait_duration = 0.02  # Initial wait duration between sends

        while not self.stop_waiting_flag.is_set():
            logger.debug("Playing background waiting audio...")
            total_samples = waiting_audio.shape[0]

            for i in range(0, total_samples, chunk_size):
                chunk = waiting_audio[i : i + chunk_size]

                # Calculate delay since last send
                duration = np.atleast_2d(chunk).shape[1] / sample_rate
                now = time.time()
                if last_send_ts is None:
                    delay = 0
                else:
                    delay = now - last_send_ts - wait_duration

                # Dynamic flow control: adjust wait time based on actual delay
                wait_duration = max(0.0, duration - delay)
                last_send_ts = now

                await self.output_queue.put((sample_rate, chunk))

                await wait_for_event(
                    event=self.stop_waiting_flag, timeout=wait_duration
                )
                if self.stop_waiting_flag.is_set():
                    break

        logger.debug("Waiting feedback completed")

    async def speech_recognition_worker(self):
        """
        Worker that processes incoming audio chunks, performs speech recognition (ASR),
        and puts recognized text into the input text queue.

        Analyzes an audio chunk to detect if a significant pause occurred after speech.

        Uses the VAD model to measure speech duration within the chunk. Updates the
        application state (`state`) regarding whether talking has started and
        accumulates speech segments.

        Args:
            audio: The numpy array containing the audio chunk.
            sampling_rate: The sample rate of the audio chunk.
        """
        stream: np.ndarray | None = None
        while not self.should_shutdown:
            try:
                event = await self.speech_recognition_queue.get()

                # Accumulate audio chunks: must be (sample_rate, np.ndarray) format
                if event.opcode == Opcode.AUDIO:
                    if isinstance(event.data, np.ndarray) and event.data.size > 0:
                        stream = (
                            event.data
                            if stream is None
                            else np.concatenate((stream, event.data))
                        )

                    if event.fin is False:
                        continue

                    # Shouldn't happen, but defensive check
                    if stream is None:
                        continue

                    # Handle speech segment completion: transcribe accumulated audio
                    event.add_event(name=EventName.PIPELINE_ACTIVATED.value)

                    # Transcribe audio using ASR engine
                    transcript = await atranscription(
                        audio=(self.input_sample_rate, stream)
                    )
                    event.add_event(name=EventName.TRANSCRIPTION_COMPLETED.value)

                    # Reset buffer for next segment
                    lexical_count = count_lexical_chars(transcript) if transcript else 0
                    stream = None
                    is_context_relevant = None

                    if lexical_count > 0 and (
                        self.last_speech_duration
                        < self.algo_options.semantic_check_threshold
                    ):
                        is_context_relevant = context_relevance_classifier(
                            query=transcript,
                            conversation=conversations.get(
                                conversation_id=self.conversation_id
                            ),
                            history_num=10,
                        )

                    logger.info(
                        f"Audio segment: Transcript: {transcript}, Token count: {lexical_count}/{self.algo_options.min_interruption_tokens}, Context relevant: {str(is_context_relevant)}."
                    )

                    if (
                        lexical_count < self.algo_options.min_interruption_tokens
                        or is_context_relevant is False
                    ):
                        self.log_latency_metrics(
                            transcript=transcript, events=event.events
                        )
                        event.end()
                        continue

                    await self.interrupt()
                    await self.text_generation_queue.put(
                        Event(
                            span=event.span,
                            opcode=Opcode.TEXT,
                            transcript=transcript,
                            data=transcript,
                            fin=True,
                        )
                    )
                elif event.opcode == Opcode.CLOSE:
                    logger.debug(
                        "Speech Recognition worker received termination signal"
                    )
                    break
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error in speech recognition worker: {e}")

    async def text_generation_worker(self):
        """
        Worker that processes LLM response and splits it into sentences.
        Sends full sentences to the TTS queue and partials to output queue.
        """
        message = ""
        while not self.should_shutdown:
            try:
                event = await self.text_generation_queue.get()

                if event.opcode == Opcode.TEXT:
                    if isinstance(event.data, str) and event.data:
                        message += event.data

                    if event.fin is False:
                        continue

                    # Shouldn't happen, but defensive check
                    if not message:
                        continue

                    self.interrupted.clear()
                    self.responding = False

                    # Start waiting feedback if enabled
                    if self.waiting_message_enabled:
                        self.stop_waiting_flag.clear()
                        asyncio.create_task(self.play_waiting_feedback_worker())

                    self.conversation.add_user_message(message=message)
                    await self.output_queue.put(
                        AdditionalOutputs(
                            [x.model_dump() for x in self.conversation.messages]
                        )
                    )
                    message = ""

                    # Prepare conversation context (last 10 messages)
                    messages = apply_prompt(
                        system_prompts=self.system_prompts,
                        messages=self.conversation.messages[-10:],
                    )

                    # Start streaming LLM response
                    response = await router.acompletion(
                        model=BASIC_LLM_MODEL_NAME,
                        messages=messages,
                        stream=True,
                    )

                    ai_message = AIMessage(content="")
                    chatbot = [x.model_dump() for x in self.conversation.messages]

                    first_llm_token_time = None
                    first_llm_sentence_time = None

                    # Process LLM response sentence by sentence
                    async for sentence_event in async_split_sentences(
                        response=response, stop_event=self.interrupted
                    ):
                        if self.interrupted.is_set():
                            event.add_event(name=EventName.USER_INTERRUPTED.value)
                            break

                        # First text received
                        if first_llm_token_time is None:
                            first_llm_token_time = time.time()
                            event.add_event(
                                name=EventName.FIRST_LLM_TOKEN_GENERATED.value
                            )
                            chatbot.append(ai_message.model_dump())
                            self.conversation.add_ai_message(message=ai_message)

                        # Partial sentence → stream to output
                        if sentence_event.is_partial:
                            chatbot[-1]["content"] += sentence_event.content
                            await self.output_queue.put(AdditionalOutputs(chatbot))
                            continue

                        # Full sentence → send to TTS
                        ai_message.content += sentence_event.content

                        if first_llm_sentence_time is None:
                            first_llm_sentence_time = time.time()
                            event.add_event(
                                name=EventName.FIRST_LLM_SENTENCE_GENERATED.value
                            )

                        await self.speech_synthesis_queue.put(
                            Event(
                                span=event.span,
                                opcode=Opcode.TEXT,
                                transcript=event.transcript,
                                data=sentence_event.content,
                                fin=False,
                            )
                        )
                        await asyncio.sleep(0.1)

                    await self.speech_synthesis_queue.put(
                        Event(
                            span=event.span,
                            opcode=Opcode.TEXT,
                            transcript=event.transcript,
                            fin=True,
                        )
                    )
                    self.text_generation_complete.set()
                elif event.opcode == Opcode.CLOSE:
                    logger.debug("Text generation worker received termination signal")
                    break
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error in text generation worker: {e}")

            logger.debug("LLM response generation completed")

    async def speech_synthesis_worker(self):
        """
        Worker that consumes full sentences from the queue,
        synthesizes speech, and streams audio chunks to the output.
        """
        while not self.should_shutdown:
            try:
                event = await self.speech_synthesis_queue.get()
                logger.debug(
                    f"speech_synthesis_worker received event: {event.model_dump()}"
                )

                if event.opcode == Opcode.TEXT:
                    if not event.data:
                        if event.fin is True:
                            self.responding = False
                            self.speech_synthesis_complete.set()
                            self.log_latency_metrics(
                                transcript=event.transcript, events=event.events
                            )
                            event.end()
                        continue

                    if not isinstance(event.data, str):
                        continue

                    if self.interrupted.is_set():
                        event.add_event(name=EventName.USER_INTERRUPTED.value)
                        continue

                    logger.debug("Generating speech from text...")

                    response = await router.aspeech(
                        model=TEXT_TO_SPEECH_MODEL_NAME,
                        input=normalize_text(event.data),
                        voice=self.voice,
                        instructions=self.instructions,
                        response_format="pcm",
                        stream=True,
                    )

                    # Initial wait duration between sends
                    self.responding = True

                    first_audio_chunk_time = None

                    # Convert byte stream to 16-bit audio
                    async for audio_chunk in async_aggregate_bytes_to_16bit(
                        await response.aiter_bytes(self.chunk_size)
                    ):
                        if self.interrupted.is_set():
                            event.add_event(name=EventName.USER_INTERRUPTED.value)
                            break

                        # First audio chunk received
                        if first_audio_chunk_time is None:
                            first_audio_chunk_time = time.time()
                            event.add_event(name=EventName.FIRST_AUDIO_CHUNK_SENT.value)

                            # Clear output queue and stop feedback
                            async with self.lock:
                                self.stop_waiting_flag.set()
                                while not self.output_queue.empty():
                                    self.output_queue.get_nowait()

                        await self.output_queue.put(
                            (configure.tts_output_sample_rate, audio_chunk)
                        )
                        await wait_for_event(
                            event=self.interrupted,
                            timeout=np.atleast_2d(audio_chunk).shape[1]
                            / configure.tts_output_sample_rate
                            * 0.75,
                        )

                    # Ensure flag is set to stop any waiting feedback
                    self.stop_waiting_flag.set()

                    if event.fin is True:
                        self.responding = False
                        self.speech_synthesis_complete.set()
                        self.log_latency_metrics(
                            transcript=event.transcript, events=event.events
                        )
                        event.end()
                elif event.opcode == Opcode.CLOSE:
                    logger.debug("Speech synthesis worker received termination signal")
                    break

            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error in speech synthesis worker: {e}")

            logger.debug("Speech synthesis complete.")

    async def determine_pause(self, audio: np.ndarray) -> None:
        # Run voice activity detection (VAD) on the current audio frame
        speech_duration, trailing_silence_duration, _ = self.vad_model.vad(
            (self.input_sample_rate, audio), self.noise_suppression_enabled
        )
        logger.debug(
            f"Speech duration: {speech_duration:.2f}s, Trailing silence duration: {trailing_silence_duration:.2f}s"
        )

        if self.started_talking:
            event = Event(
                span=self.interaction_span,
                opcode=Opcode.AUDIO,
                data=audio,
                fin=False,
            )
            await self.speech_recognition_queue.put(event)

            self.speech_duration += speech_duration

            # Check if speech duration exceeds the interruption threshold
            if self.speech_duration >= self.algo_options.min_interruption_duration:
                logger.info(
                    f"Speech duration {self.speech_duration:.2f}s exceeded threshold {self.algo_options.min_interruption_duration:.2f}s, triggering interruption"
                )
                await self.interrupt()

            # If current frame is below speech threshold, treat as silence
            if speech_duration < self.algo_options.speech_threshold:
                self.endpointing_delay += trailing_silence_duration

                # Not enough silence frames yet; wait for more
                if self.endpointing_delay < self.min_endpointing_delay:
                    return

                # Trigger silence completion
                event.add_event(
                    name=EventName.USER_STOPPED_TALKING.value,
                    timestamp=time.time_ns()
                    - int(self.endpointing_delay * 1_000_000_000),
                )
                logger.info(
                    f"Endpointing delay {self.endpointing_delay:.2f}s exceeded threshold {self.min_endpointing_delay:.2f}s, triggering silence completion"
                )
                self.last_speech_duration = self.speech_duration
                self.started_talking = False
                self.endpointing_delay = 0.0
                self.speech_duration = 0.0

                await self.speech_recognition_queue.put(
                    Event(
                        span=self.interaction_span,
                        opcode=Opcode.AUDIO,
                        fin=True,
                    )
                )
                return

            # Still speech; reset silence counter and forward frame
            self.endpointing_delay = trailing_silence_duration
            logger.debug("Speech detected again. Resetting endpointing delay.")
            return

        # Not currently in speech mode; check if speech has started
        if speech_duration > self.algo_options.started_talking_threshold:
            self.started_talking = True
            self.interaction_span = tracer.start_span(
                "conversation.interaction",
                context=set_span_in_context(self.session_span),
            )
            event = Event(
                span=self.interaction_span,
                opcode=Opcode.AUDIO,
                data=audio,
                fin=False,
            )

            event.add_event(
                name=EventName.USER_STARTED_TALKING.value,
                timestamp=time.time_ns() - int(speech_duration * 1_000_000_000),
            )
            logger.debug("Started talking")

            await self.send_message(create_message("log", "started_talking"))

            # Prepend buffered padding audio before new speech frame
            if self.padding_buffer is not None:
                await self.speech_recognition_queue.put(
                    Event(
                        span=self.interaction_span,
                        opcode=Opcode.AUDIO,
                        data=self.padding_buffer,
                        fin=False,
                    )
                )
                self.padding_buffer = None

            await self.speech_recognition_queue.put(event)
            return

        # Still not enough to consider speech — maintain padding buffer
        if self.padding_buffer is None:
            self.padding_buffer = audio
        elif self.padding_buffer.size < self.padding_buffer_size:
            self.padding_buffer = np.concatenate((self.padding_buffer, audio))
        else:
            # Shift left and append new frame to maintain fixed padding size
            self.padding_buffer = np.concatenate(
                (self.padding_buffer[audio.size :], audio)
            )

    async def receive(self, frame: tuple[int, np.ndarray]) -> None:
        """
        Receives an audio frame from the stream.

        Processes the audio frame using `process_audio`. If a pause is detected,
        it sets the `event`. If interruption is enabled and a reply is ongoing,
        it closes the current generator and clears the processing queue.

        Args:
            frame: A tuple containing the sample rate and the audio frame data.
        """
        if (
            not self.startup_complete
            or self.should_shutdown
            or (self.responding and not self.can_interrupt)
        ):
            return

        array = np.squeeze(frame[1])

        if self.buffer is None:
            self.buffer = array
        else:
            self.buffer = np.concatenate((self.buffer, array))

        duration = len(self.buffer) / frame[0]

        if duration < self.algo_options.audio_chunk_duration:
            return

        await self.determine_pause(audio=self.buffer)
        self.buffer = None

    async def interrupt(self):
        """
        Interrupts the current reply process if it is ongoing.

        Sets the `interrupted` event, which can be used to signal that a new
        audio frame has arrived while a reply is being generated.
        """
        if self.can_interrupt:
            await self.send_message(create_message("log", "pause_detected"))
            if self.responding and not self.interrupted.is_set():
                self.interruption_trigger_time = time.time()
                self.interrupted.set()
                await self.text_generation_complete.wait()
                await self.speech_synthesis_complete.wait()
                async with self.lock:
                    for queue in (self.speech_synthesis_queue, self.output_queue):
                        while not queue.empty():
                            queue.get_nowait()
                self.text_generation_complete.clear()
                self.speech_synthesis_complete.clear()
                self.responding = False
                logger.info("Successfully interrupted and cleared pipeline queues")
            self.clear_queue()

    def log_latency_metrics(self, transcript: str, events: list[OTelEvent]):
        metrics = PipelineLatencyMetrics(transcript=transcript)
        metrics.update_from_events(events)
        metrics.log_latency_metrics()

    async def emit(self):
        async with self.lock:
            return await wait_for_item(self.output_queue)
