import av
import ssl
import uuid
import json
import numpy as np
import base64
import asyncio
import pyaudio
import audioop
import argparse
from av import AudioResampler, AudioFrame
from numpy.typing import NDArray
from typing import AsyncGenerator, Optional
from pydantic import WebsocketUrl
from websockets.asyncio.client import connect, ClientConnection


def audio_resample(
    resampler: AudioResampler, audio: tuple[int, NDArray[np.int16 | np.float32]]
) -> tuple[int, NDArray[np.int16 | np.float32]]:
    """
    Resample audio data to a new sample rate while preserving original dtype and channel layout.

    Args:
        resampler: AudioResampler instance
        audio: Tuple containing the original sample rate and audio data as numpy array

    Returns:
        Tuple containing the new sample rate and resampled audio data
    """
    sample_rate, audio_array = audio
    # Determine input properties
    dtype = audio_array.dtype
    frame_format = "s16" if dtype == np.int16 else "fltp"

    # Determine channel layout
    if audio_array.ndim == 1:
        layout = "mono"
        audio_array = audio_array.reshape(1, -1)  # Ensure 2D for processing
    else:
        if audio_array.shape[0] == 1:
            layout = "mono"
        elif audio_array.shape[0] == 2:
            layout = "stereo"
        else:
            raise ValueError("Only mono or stereo audio is supported")

    # Create AV frame from numpy array
    frame = AudioFrame.from_ndarray(audio_array, layout=layout, format=frame_format)  # type: ignore
    frame.sample_rate = sample_rate

    resampled = resampler.resample(frame)

    # Convert resampled frames to ndarray and concatenate
    resampled_arrays = [f.to_ndarray() for f in resampled]

    if not resampled_arrays:
        return resampler.rate, np.array([], dtype=dtype)

    output = np.concatenate(resampled_arrays, axis=1)

    # Convert back to original shape
    if layout == "mono":
        output = output.squeeze(0)  # Back to 1D for mono

    # Ensure output has same dtype as input
    return resampler.rate, output.astype(dtype)


class AudioStreamManager:
    """Manages audio input and output streams using PyAudio."""

    def __init__(self, sample_rate: int = 16_000):
        self.sample_rate = sample_rate
        self.frames_per_buffer = int(self.sample_rate * 0.02)

        self._pyaudio = pyaudio.PyAudio()
        self._input_stream: Optional[pyaudio.Stream] = None
        self._output_stream: Optional[pyaudio.Stream] = None

    async def open_input_stream(self) -> None:
        """Initialize the audio input stream."""
        dev_info = self._pyaudio.get_default_input_device_info()

        self._input_stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.frames_per_buffer,
        )

        print(
            f"🎤 Microphone initialized (Rate: {self.sample_rate}Hz, "
            f"Device: {dev_info['name']}, Chunk size: {self.frames_per_buffer})"
        )

    async def open_output_stream(self) -> None:
        """Initialize the audio output stream."""
        self._output_stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=self.frames_per_buffer,
        )

    def close(self) -> None:
        """Clean up all audio resources."""
        if self._input_stream:
            self._input_stream.stop_stream()
            self._input_stream.close()
        if self._output_stream:
            self._output_stream.stop_stream()
            self._output_stream.close()
        self._pyaudio.terminate()

    @property
    def input_stream(self) -> pyaudio.Stream:
        """Get the input stream with type checking."""
        if self._input_stream is None:
            raise RuntimeError("Input stream not initialized")
        return self._input_stream

    @property
    def output_stream(self) -> pyaudio.Stream:
        """Get the output stream with type checking."""
        if self._output_stream is None:
            raise RuntimeError("Output stream not initialized")
        return self._output_stream


async def generate_audio_chunks(
    audio_manager: AudioStreamManager,
) -> AsyncGenerator[bytes, None]:
    """
    Continuously generate audio chunks from the microphone.

    Args:
        audio_manager: Audio stream manager instance

    Yields:
        Chunks of audio data as bytes
    """
    frames_per_buffer = audio_manager.frames_per_buffer

    try:
        while True:
            yield audio_manager.input_stream.read(
                frames_per_buffer, exception_on_overflow=False
            )
    except KeyboardInterrupt:
        print("\nMicrophone stream stopped")
    except Exception as e:
        print(f"Microphone error: {e}")


async def send_audio_to_websocket(
    websocket: ClientConnection, audio_manager: AudioStreamManager
) -> None:
    """
    Process and send audio data to WebSocket server.

    Args:
        websocket: Active WebSocket connection
        audio_manager: Audio stream manager instance
    """
    input_layout = "mono"
    mulaw_sample_rate = 8000
    output_chunk_size = int(
        audio_manager.frames_per_buffer
        * (mulaw_sample_rate / audio_manager.sample_rate)
    )

    input_resampler = av.AudioResampler(
        rate=mulaw_sample_rate,
        layout=input_layout,
        format="s16",
    )

    try:
        async for chunk in generate_audio_chunks(audio_manager):
            # Convert and resample audio
            audio_np = np.frombuffer(chunk, dtype=np.int16)

            _, audio = audio_resample(
                resampler=input_resampler, audio=(audio_manager.sample_rate, audio_np)
            )

            # Convert to ulaw and send
            ulaw_data = audioop.lin2ulaw(audio[: output_chunk_size * 2], 2)
            await websocket.send(base64.b64encode(ulaw_data).decode("utf-8"))
            await asyncio.sleep(0)
    except Exception as e:
        print(f"Audio sending error: {e}")
        raise


async def receive_audio_from_websocket(
    websocket: ClientConnection, audio_manager: AudioStreamManager
) -> None:
    """
    Receive and play audio from WebSocket server.

    Args:
        websocket: Active WebSocket connection
        audio_manager: Audio stream manager instance
    """
    output_layout = "mono"
    output_resampler = av.AudioResampler(
        rate=audio_manager.sample_rate,
        layout=output_layout,
        format="s16",
    )
    try:
        while True:
            message = await websocket.recv()

            audio_pcm = audioop.ulaw2lin(base64.b64decode(message), 2)
            audio_np = np.frombuffer(audio_pcm, dtype=np.int16)

            _, audio = audio_resample(
                resampler=output_resampler, audio=(8000, audio_np)
            )
            audio_manager.output_stream.write(audio.tobytes())
            await asyncio.sleep(0)
    except Exception as e:
        print(f"Audio receiving error: {e}")
        raise


async def send_signal_event(
    websocket: ClientConnection, method: str, session_id: str = ""
) -> dict:
    """
    Send a signaling event to the WebSocket server.

    Args:
        websocket: Active WebSocket connection
        method: Event method name
        session_id: Optional session ID

    Returns:
        Response from the server as a dictionary
    """
    event = {
        "id": str(uuid.uuid4()),
        "type": "event",
        "method": method,
        "data": {
            "sessionId": session_id,
            "callOriginNumber": "+85212345670",
            "callTargetNumber": "+85287654321",
        },
    }

    await websocket.send(json.dumps(event))
    response = await websocket.recv()
    return json.loads(response)


async def create_ssl_context() -> ssl.SSLContext:
    """Create and configure SSL context for secure connections."""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


class WebSocketAudioClient:
    """Main client class for WebSocket audio streaming."""

    def __init__(self, websocket_url: str):
        self.websocket_url = WebsocketUrl(websocket_url)
        self.audio_manager = AudioStreamManager()
        self.ssl_context = None

    async def initialize(self) -> None:
        """Initialize the client and SSL context."""
        if self.websocket_url.scheme == "wss":
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
        await self.audio_manager.open_input_stream()
        await self.audio_manager.open_output_stream()

    async def run(self) -> None:
        """Main execution method for the client."""
        try:
            await self.initialize()

            # Connect to signaling WebSocket
            signal_ws = await connect(
                f"{self.websocket_url.scheme}://{self.websocket_url.host}:{self.websocket_url.port}/telephone/websocket/signal",
                ssl=self.ssl_context,
            )

            # Establish call session
            response = await send_signal_event(signal_ws, "call_established")
            session_id = response.get("data", {}).get("sessionId", str(uuid.uuid4()))

            # Connect to media WebSocket
            media_ws = await connect(
                f"{self.websocket_url.scheme}://{self.websocket_url.host}:{self.websocket_url.port}/telephone/websocket/media?sessionId={session_id}",
                ssl=self.ssl_context,
            )

            print(f"\033[92mSession ID: {session_id} connected.\033[0m")

            # Start audio streaming
            await asyncio.gather(
                send_audio_to_websocket(media_ws, self.audio_manager),
                receive_audio_from_websocket(media_ws, self.audio_manager),
                return_exceptions=True,
            )

        except Exception as e:
            print(f"Client error: {e}")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up all resources."""
        self.audio_manager.close()


async def main(server_url: str) -> None:
    """Entry point for the application."""
    client = WebSocketAudioClient(websocket_url=server_url)

    try:
        await client.run()
    except KeyboardInterrupt:
        print("\nApplication terminated by user")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Voice Assistant server")
    parser.add_argument(
        "-s",
        "--server",
        type=str,
        required=True,
        help=f"WebSocket server address (e.g., wss://example.com:80).",
    )
    args = parser.parse_args()

    asyncio.run(main(server_url=args.server))
