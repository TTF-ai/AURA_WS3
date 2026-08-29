"""
Microphone audio capture using PyAudio.

Provides a blocking stream of audio frames for VAD processing.
"""

import numpy as np
import wave
import io
import struct


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit
CHUNK_SIZE = 480  # 30ms at 16kHz


class AudioCapture:
    """Manages microphone input using PyAudio."""

    def __init__(self, sample_rate=SAMPLE_RATE, channels=CHANNELS, chunk_size=CHUNK_SIZE):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.stream = None
        self.pa = None

    def start(self):
        """Open the microphone stream."""
        import pyaudio
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

    def read_frame(self) -> np.ndarray:
        """
        Read one audio frame from the microphone.

        Returns:
            numpy array of int16 samples.
        """
        if self.stream is None:
            raise RuntimeError("AudioCapture not started. Call start() first.")

        data = self.stream.read(self.chunk_size, exception_on_overflow=False)
        return np.frombuffer(data, dtype=np.int16)

    def stop(self):
        """Close the microphone stream."""
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        if self.pa is not None:
            self.pa.terminate()
            self.pa = None

    @staticmethod
    def pcm_to_wav(pcm_bytes: bytes, sample_rate=SAMPLE_RATE, channels=CHANNELS) -> bytes:
        """
        Wrap raw PCM int16 bytes into a WAV container.

        Args:
            pcm_bytes: Raw PCM data.
            sample_rate: Sample rate.
            channels: Number of channels.

        Returns:
            bytes: Complete WAV file.
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()
