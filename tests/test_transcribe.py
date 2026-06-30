"""Tests for the transcription step (MP3 -> TXT).

faster-whisper's model is mocked so no model is downloaded and no real audio
is decoded.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

import transcribe


def test_transcribe_missing_audio_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        transcribe.transcribe(tmp_path / "nope.mp3", tmp_path / "out.txt")


def test_transcribe_writes_segments_to_file(tmp_path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake audio bytes")
    out = tmp_path / "sub" / "transcript.txt"

    segments = [
        SimpleNamespace(text=" Hello there. "),
        SimpleNamespace(text="Second line."),
    ]
    info = SimpleNamespace(language="en", language_probability=0.99)

    fake_model = mock.MagicMock()
    fake_model.transcribe.return_value = (segments, info)

    with mock.patch.object(transcribe, "WhisperModel", return_value=fake_model) as model_cls:
        result = transcribe.transcribe(audio, out, model_size="tiny", language="en")

    assert result == out
    model_cls.assert_called_once()
    fake_model.transcribe.assert_called_once_with(str(audio), language="en")
    assert out.read_text(encoding="utf-8") == "Hello there.\nSecond line.\n"
