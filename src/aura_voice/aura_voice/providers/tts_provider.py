"""Abstract base class for Text-to-Speech providers."""

from abc import ABC, abstractmethod


class TTSProvider(ABC):
    """Interface for all TTS providers."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        language: str = "en",
        voice: str = None
    ) -> bytes:
        """
        Synthesize text into audio.

        Args:
            text: Text to speak.
            language: ISO 639-1 language code.
            voice: Optional voice identifier.

        Returns:
            bytes: Raw audio data (WAV/PCM).
        """
        pass

    @abstractmethod
    def supports_language(self, language: str) -> bool:
        """Check if this provider supports the given language."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        pass
