import numpy as np
from av import AudioFrame, AudioResampler
from numpy.typing import NDArray


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
