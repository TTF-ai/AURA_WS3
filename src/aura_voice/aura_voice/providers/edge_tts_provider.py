"""Edge-TTS provider for fast, free, multilingual speech."""

import asyncio
import edge_tts
from .tts_provider import TTSProvider


class EdgeTTS(TTSProvider):
    """Text-to-Speech using edge-tts."""

    # Map language codes to default Edge TTS voices
    VOICES = {
        "en": "en-US-AriaNeural",
        "hi": "hi-IN-SwaraNeural",    # Hindi
        "kn": "kn-IN-GaganNeural",    # Kannada
        "te": "te-IN-ShrutiNeural",   # Telugu
        "ta": "ta-IN-PallaviNeural",  # Tamil
        "ml": "ml-IN-SobhanaNeural",  # Malayalam
        "mr": "mr-IN-AarohiNeural",   # Marathi
        "gu": "gu-IN-DhwaniNeural",   # Gujarati
        "bn": "bn-IN-TanishaaNeural", # Bengali
    }

    def __init__(self, timeout: float = 10.0, **kwargs):
        self.timeout = timeout

    async def _async_synthesize(self, text: str, voice: str) -> bytes:
        """Run edge-tts asynchronously and collect audio bytes."""
        communicate = edge_tts.Communicate(text, voice)
        audio_data = bytearray()
        
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
                
        return bytes(audio_data)

    def synthesize(self, text: str, language: str = "en", voice: str = None) -> bytes:
        """Synthesize text into audio."""
        if language not in self.VOICES:
            raise ValueError(f"Edge TTS does not support language '{language}'. Supported: {list(self.VOICES.keys())}")
            
        selected_voice = voice or self.VOICES[language]
        
        # EdgeTTS is async, so we wrap it in a synchronous call
        return asyncio.run(self._async_synthesize(text, selected_voice))

    def supports_language(self, language: str) -> bool:
        """Check if this provider supports the given language."""
        return language in self.VOICES

    def is_available(self) -> bool:
        """Edge TTS is always available (no API key needed)."""
        return True
