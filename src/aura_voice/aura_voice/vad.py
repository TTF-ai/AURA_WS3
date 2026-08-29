"""
Lightweight energy-based Voice Activity Detection.

Detects when a person starts and stops speaking by monitoring
audio energy levels. No cloud calls, no ML model.
"""

import numpy as np
import time


class VAD:
    """Energy-based voice activity detector."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        energy_threshold: float = 0.01,
        speech_pad_ms: int = 300,
        min_speech_ms: int = 500,
        max_speech_ms: int = 10000,
    ):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)
        self.energy_threshold = energy_threshold
        self.speech_pad_frames = int(speech_pad_ms / frame_duration_ms)
        self.min_speech_frames = int(min_speech_ms / frame_duration_ms)
        self.max_speech_frames = int(max_speech_ms / frame_duration_ms)

        # State
        self.is_speaking = False
        self.silence_count = 0
        self.speech_frames = []
        self.speech_frame_count = 0

    def reset(self):
        """Reset the VAD state."""
        self.is_speaking = False
        self.silence_count = 0
        self.speech_frames = []
        self.speech_frame_count = 0

    def process_frame(self, audio_frame: np.ndarray) -> bytes:
        """
        Process a single audio frame.

        Args:
            audio_frame: numpy array of int16 audio samples.

        Returns:
            bytes: Complete speech segment (WAV-ready PCM) if speech ended,
                   None if still recording or silent.
        """
        # Calculate RMS energy
        float_frame = audio_frame.astype(np.float32) / 32768.0
        energy = np.sqrt(np.mean(float_frame ** 2))

        is_speech = energy > self.energy_threshold

        if is_speech:
            if not self.is_speaking:
                self.is_speaking = True
                self.silence_count = 0
                self.speech_frames = []
                self.speech_frame_count = 0

            self.silence_count = 0
            self.speech_frames.append(audio_frame.copy())
            self.speech_frame_count += 1

            # Max speech limit
            if self.speech_frame_count >= self.max_speech_frames:
                return self._finalize_speech()

        else:
            if self.is_speaking:
                self.speech_frames.append(audio_frame.copy())
                self.speech_frame_count += 1
                self.silence_count += 1

                # End of speech detected
                if self.silence_count >= self.speech_pad_frames:
                    if self.speech_frame_count >= self.min_speech_frames:
                        return self._finalize_speech()
                    else:
                        # Too short — discard
                        self.reset()

        return None

    def _finalize_speech(self) -> bytes:
        """Concatenate speech frames into a single PCM buffer."""
        if not self.speech_frames:
            self.reset()
            return None

        audio = np.concatenate(self.speech_frames)
        self.reset()
        return audio.tobytes()
