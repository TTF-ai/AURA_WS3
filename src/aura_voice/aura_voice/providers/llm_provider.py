"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Interface for all LLM providers."""

    @abstractmethod
    def generate_intent(
        self,
        user_text: str,
        system_prompt: str,
        context: dict
    ) -> dict:
        """
        Extract structured intent from natural language.

        Args:
            user_text: The transcribed user speech.
            system_prompt: The system prompt with AURA identity.
            context: dict with auth state, follow state, behavior, language.

        Returns:
            dict with keys:
                'intent': string from allowed intent list
                'parameters': dict of parameters
                'response_text': string response for TTS
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        pass
