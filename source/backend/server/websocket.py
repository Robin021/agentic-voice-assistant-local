import av
import time
import json
import uuid
import base64
import audioop
import asyncio
import secrets
import datetime
import numpy as np
from anyio.to_thread import run_sync
from numpy.typing import NDArray
from typing import cast
from fastapi import WebSocket
from fastapi.websockets import WebSocketState, WebSocketDisconnect
from fastrtc.utils import (
    CloseStream,
    Context,
    AdditionalOutputs,
    split_output,
    current_context,
)
from fastrtc.tracks import AsyncStreamHandler
from fastrtc.websocket import WebSocketHandler

from config import configure
from voice.utils import audio_resample
from logger import logger
from prompts.template import get_prompt_template


class SignalWebSocketHandler(WebSocketHandler):
    async def handle_websocket(self, websocket: WebSocket):
        await websocket.accept()
        self.websocket = websocket

        try:
            while not self.quit.is_set():
                if websocket.application_state != WebSocketState.CONNECTED:
                    was_disconnected = True
                    break

                message = await websocket.receive_json()

                if message["method"] == "call_established":
                    await websocket.send_json(
                        dict(
                            type="ack",
                            method="call_established",
                            pMsgId=message["id"],
                            data=dict(
                                sessionId=str(uuid.uuid4()),
                                callOriginNumber=message["data"]["callOriginNumber"],
                                callTargetNumber=message["data"]["callTargetNumber"],
                            ),
                        )
                    )
                elif message["method"] == "call_disconnected":
                    await websocket.send_json(
                        dict(
                            type="ack",
                            method="call_disconnected",
                            pMsgId=message["id"],
                            data=dict(
                                sessionId=message["data"]["sessionId"],
                                callOriginNumber=message["data"]["callOriginNumber"],
                                callTargetNumber=message["data"]["callTargetNumber"],
                            ),
                        )
                    )
                elif message["method"] == "heartbeat":
                    await websocket.send_json(
                        dict(
                            type="ack",
                            method="heartbeat",
                            pMsgId=message["id"],
                            data=dict(
                                sessionId=message["data"]["sessionId"],
                                callOriginNumber=message["data"]["callOriginNumber"],
                                callTargetNumber=message["data"]["callTargetNumber"],
                            ),
                        )
                    )

        except json.decoder.JSONDecodeError as e:
            await websocket.send_json(
                dict(
                    type="error",
                    method="",
                    pMsgId="",
                    pMsgTimestamp=int(datetime.datetime.now().timestamp()),
                    data=dict(
                        sessionId="",
                        callOriginNumber="",
                        callTargetNumber="",
                        message="Error when parsing payload JSON",
                    ),
                )
            )
        except WebSocketDisconnect:
            # Surprisingly, this leaves `websocket.application_state` as CONNECTED
            # in the `finally` block, so we use this variable
            was_disconnected = True
        finally:
            if not was_disconnected:
                await websocket.close()

            self.clean_up(cast(str, self.stream_id))


class MediaWebSocketHandler(WebSocketHandler):

    async def handle_websocket(self, websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.websocket = websocket
        # self.data_channel = WebSocketDataChannel(websocket, loop)
        self.stream_handler._loop = loop
        # self.stream_handler.set_channel(self.data_channel)
        self._emit_task = asyncio.create_task(self._emit_loop())
        self._emit_to_queue_task = asyncio.create_task(self._emit_to_queue())
        self._frame_cleanup_task = asyncio.create_task(self._cleanup_frames_loop())

        if isinstance(self.stream_handler, AsyncStreamHandler):
            start_up = self.stream_handler.start_up()
        else:
            start_up = run_sync(self.stream_handler.start_up)  # type: ignore

        was_disconnected = False

        session_id = self.websocket.query_params.get("sessionId", str(uuid.uuid4()))
        current_context.set(Context(webrtc_id=session_id))
        self.set_additional_outputs = self.set_additional_outputs_factory(session_id)

        self.stream_handler.set_args(
            [
                "__webrtc_value__",
                get_prompt_template("assistant"),
                session_id,
                secrets.choice(configure.available_voices),
                None,
                configure.language.value,
                configure.allow_interruption,
                configure.voice_activity_detection_options.noise_suppression_enabled,
            ]
        )

        self.input_resampler = av.AudioResampler(
            rate=self.stream_handler.input_sample_rate,
            layout="mono",
            format="s16",
        )
        self.output_sample_rate = 8_000
        self.output_resampler = av.AudioResampler(
            rate=self.output_sample_rate,
            layout="mono",
            format="s16",
        )

        self.start_up_task = asyncio.create_task(start_up)
        try:
            while not self.quit.is_set():
                if websocket.application_state != WebSocketState.CONNECTED:
                    was_disconnected = True
                    break

                message = await websocket.receive_text()
                audio_payload = base64.b64decode(message)

                audio_array = np.frombuffer(
                    audioop.ulaw2lin(audio_payload, 2), dtype=np.int16
                )

                if self.stream_handler.input_sample_rate != 8000:
                    audio: tuple[int, NDArray[np.int16]] = audio_resample(
                        resampler=self.input_resampler,
                        audio=(8000, audio_array),
                    )  # type: ignore
                else:
                    audio = (8000, audio_array)

                try:
                    if isinstance(self.stream_handler, AsyncStreamHandler):
                        await self.stream_handler.receive(audio)
                    else:
                        await run_sync(
                            self.receive_with_context,
                            audio,
                        )
                except Exception as e:
                    print(e)
                    import traceback

                    traceback.print_exc()
                    logger.debug("Error in websocket handler %s", e)

        except WebSocketDisconnect:
            # Surprisingly, this leaves `websocket.application_state` as CONNECTED
            # in the `finally` block, so we use this variable
            was_disconnected = True
        finally:
            if self._emit_task:
                self._emit_task.cancel()
            if self._emit_to_queue_task:
                self._emit_to_queue_task.cancel()
            if self._frame_cleanup_task:
                self._frame_cleanup_task.cancel()
            if self._graceful_shutdown_task:
                self._graceful_shutdown_task.cancel()
            if self.start_up_task:
                self.start_up_task.cancel()

            if not was_disconnected:
                await websocket.close()

            self.clean_up(cast(str, self.stream_id))

    async def _emit_loop(self):
        """Asynchronously emits audio data to WebSocket client with adaptive rate control.

        Dynamically adjusts send rate based on network conditions to maintain smooth playback
        while avoiding client-side buffer buildup.
        """
        try:
            # Initialize flow control variables
            self.last_send_ts = None  # Timestamp of last send operation
            wait_duration = 0.02  # Initial wait duration between sends

            while not self.quit.is_set():
                output = await self.queue.get()

                if output is None:
                    wait_duration = 0.02  # Reset wait duration
                    await asyncio.sleep(wait_duration)
                    self.last_send_ts = None  # Reset timestamp
                    continue

                # Split output into frame and metadata
                frame, output = split_output(output)

                # Handle special output types
                if isinstance(output, AdditionalOutputs):
                    pass
                    self.set_additional_outputs(output)
                elif isinstance(output, CloseStream):
                    self._graceful_shutdown_task = asyncio.create_task(
                        self._wait_for_audio_completion()
                    )
                    continue

                # Skip if frame is not in expected format
                if not isinstance(frame, tuple):
                    continue

                # Calculate audio duration in seconds
                duration = np.atleast_2d(frame[1]).shape[1] / frame[0]

                # Resample if needed to match output sample rate
                if frame[0] != self.output_sample_rate:
                    frame = audio_resample(resampler=self.output_resampler, audio=frame)

                # Convert audio to μ-law and base64 for transmission
                mulaw_audio = audioop.lin2ulaw(frame[1].tobytes(), 2)
                audio_payload = base64.b64encode(mulaw_audio)

                # Only proceed if websocket connection exists
                if self.websocket:
                    self.playing_durations.append(duration)

                    # Calculate delay since last send
                    now = time.perf_counter()
                    if self.last_send_ts is None:
                        delay = 0
                    else:
                        delay = now - self.last_send_ts - wait_duration

                    # Dynamic flow control: adjust wait time based on actual delay
                    wait_duration = max(0.0, duration - delay)
                    self.last_send_ts = now

                    await self.websocket.send_bytes(audio_payload)

                await asyncio.sleep(wait_duration)

        except asyncio.CancelledError:
            logger.debug("Emit loop cancelled")
        except Exception as e:
            import traceback

            traceback.print_exc()
            logger.debug("Error in emit loop: %s", e)
