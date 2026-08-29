"""Groq Whisper STT provider."""

import os
import io
import httpx

from .stt_provider import STTProvider


class GroqSTT(STTProvider):
    """Speech-to-Text using Groq's hosted Whisper API."""

    API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, model: str = "whisper-large-v3-turbo", timeout: float = 10.0):
        self.model = model
        self.timeout = timeout
        self.api_key = os.environ.get("GROQ_API_KEY", "")

    def transcribe(self, audio_bytes: bytes, language: str = None) -> dict:
        """
        Send audio to Groq Whisper for transcription.

        Args:
            audio_bytes: WAV audio data.
            language: Optional ISO 639-1 hint (e.g. 'en', 'kn').

        Returns:
            dict: {'text': ..., 'language': ..., 'confidence': ...}
        """
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY environment variable not set")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        files = {
            "file": ("audio.wav", io.BytesIO(audio_bytes), "audio/wav"),
        }

        data = {
            "model": self.model,
            "response_format": "verbose_json",
        }

        if language:
            data["language"] = language

        try:
            response = httpx.post(
                self.API_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            return {
                "text": result.get("text", "").strip(),
                "language": result.get("language", "unknown"),
                "confidence": 1.0,  # Whisper doesn't expose per-segment confidence
            }

        except httpx.TimeoutException:
            raise RuntimeError("Groq STT request timed out")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Groq STT API error: {e.response.status_code} {e.response.text}")

    def is_available(self) -> bool:
        return bool(self.api_key)
