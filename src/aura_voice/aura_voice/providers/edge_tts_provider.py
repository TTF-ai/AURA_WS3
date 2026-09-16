"""Edge-TTS provider for fast, free, multilingual speech."""

import asyncio
import edge_tts
from .tts_provider import TTSProvider


class EdgeTTS(TTSProvider):
    """Text-to-Speech using edge-tts."""

    # Map language codes to default Edge TTS voices
    VOICES = {
        "en": "en-US-AriaNeural",
        "en-in": "en-IN-NeerjaNeural",
        "hi": "hi-IN-SwaraNeural",
        "kn": "kn-IN-GaganNeural",
        "te": "te-IN-ShrutiNeural",
        "ta": "ta-IN-PallaviNeural",
        "ml": "ml-IN-SobhanaNeural",
        "mr": "mr-IN-AarohiNeural",
        "gu": "gu-IN-DhwaniNeural",
        "bn": "bn-IN-TanishaaNeural",
        "en+kn": "kn-IN-GaganNeural",
        "kn+en": "kn-IN-GaganNeural",
        "en+hi": "hi-IN-SwaraNeural",
        "hi+en": "hi-IN-SwaraNeural",
        "en+te": "te-IN-ShrutiNeural",
        "te+en": "te-IN-ShrutiNeural",
        "en+ta": "ta-IN-PallaviNeural",
        "ta+en": "ta-IN-PallaviNeural",
    }

    def __init__(self, timeout: float = 10.0, **kwargs):
        self.timeout = timeout

    @staticmethod
    def _normalize_language(language: str) -> str:
        """Normalize tags like en+kn, en-IN, en_US."""
        if not language:
            return "en"

        normalized = str(language).strip().lower().replace("_", "-")
        candidates = [normalized]

        if "+" in normalized:
            parts = [p.strip() for p in normalized.split("+") if p.strip()]
            if len(parts) >= 2:
                candidates.extend([parts[0], parts[1]])

        if "-" in normalized:
            prefix = normalized.split("-", 1)[0]
            candidates.append(prefix)

        for candidate in candidates:
            if candidate in EdgeTTS.VOICES:
                return candidate

        if normalized.startswith("en"):
            return "en"
        return normalized

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
        normalized_language = self._normalize_language(language)
        if normalized_language not in self.VOICES:
            raise ValueError(
                f"Edge TTS does not support language '{language}'. Supported: {list(self.VOICES.keys())}"
            )

        selected_voice = voice or self.VOICES[normalized_language]
        return asyncio.run(self._async_synthesize(text, selected_voice))

    def supports_language(self, language: str) -> bool:
        """Check if this provider supports the given language."""
        return self._normalize_language(language) in self.VOICES

    def is_available(self) -> bool:
        """Edge TTS is always available (no API key needed)."""
        return True
