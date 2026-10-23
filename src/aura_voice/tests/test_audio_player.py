from aura_voice.audio_player import AudioPlayer


def test_mp3_prefers_ffplay_when_available():
    player = AudioPlayer()
    assert player._resolve_player("mp3") in {"ffplay", "mpg123"}


def test_wav_falls_back_to_aplay_when_needed():
    player = AudioPlayer()
    player._player = "aplay"
    assert player._resolve_player("wav") == "aplay"
