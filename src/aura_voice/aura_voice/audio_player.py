"""
Audio playback module.

Plays WAV/MP3 audio through the system speaker.
"""

import subprocess
import tempfile
import os


class AudioPlayer:
    """Plays audio bytes through the system speaker."""

    def __init__(self):
        # Detect available player
        self._player = self._detect_player()

    def _detect_player(self) -> str:
        """Find an available audio player on the system."""
        for player in ["ffplay", "mpg123", "paplay", "aplay"]:
            try:
                result = subprocess.run(
                    ["which", player],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return player
            except FileNotFoundError:
                continue
        return "aplay"  # Default fallback

    def play(self, audio_bytes: bytes, audio_format: str = "wav"):
        """
        Play audio bytes through the speaker.

        Args:
            audio_bytes: Raw audio data.
            audio_format: 'wav' or 'mp3'.
        """
        if not audio_bytes:
            return

        suffix = f".{audio_format}"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.flush()
            tmp.close()

            if self._player == "ffplay":
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp.name]
            elif self._player == "paplay":
                cmd = ["paplay", tmp.name]
            else:
                cmd = ["aplay", "-q", tmp.name]

            subprocess.run(cmd, timeout=30)

        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def is_available(self) -> bool:
        """Check if audio playback is possible."""
        try:
            result = subprocess.run(
                ["which", self._player],
                capture_output=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
