"""Provider factory and exports."""

from .groq_stt import GroqSTT
from .groq_llm import GroqLLM
from .openrouter_llm import OpenRouterLLM
from .edge_tts_provider import EdgeTTS


def create_stt_provider(provider_name: str, **kwargs):
    """Factory for STT providers."""
    providers = {
        "groq": GroqSTT,
    }
    cls = providers.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown STT provider: {provider_name}. Available: {list(providers.keys())}")
    return cls(**kwargs)


def create_llm_provider(provider_name: str, **kwargs):
    """Factory for LLM providers."""
    providers = {
        "groq": GroqLLM,
        "openrouter": OpenRouterLLM,
    }
    cls = providers.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider_name}. Available: {list(providers.keys())}")
    return cls(**kwargs)


def create_tts_provider(provider_name: str, **kwargs):
    """Factory for TTS providers."""
    providers = {
        "edge": EdgeTTS,
    }
    cls = providers.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown TTS provider: {provider_name}. Available: {list(providers.keys())}")
    return cls(**kwargs)
