"""Abstract base class for Speech-to-Text providers."""

from abc import ABC, abstractmethod


class STTProvider(ABC):
    """Interface for all STT providers."""

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, language: str = None) -> dict:
        """
        Transcribe audio to text.

        Args:
            audio_bytes: Raw audio data (WAV format, 16kHz mono).
            language: Optional language hint (ISO 639-1 code).

        Returns:
            dict with keys:
                'text': transcribed string
                'language': detected language code
                'confidence': float 0.0-1.0
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        pass
