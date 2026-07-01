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


def test_format_timestamp():
    assert transcribe.format_timestamp(5) == "0:05"
    assert transcribe.format_timestamp(65) == "1:05"
    assert transcribe.format_timestamp(3725) == "1:02:05"


def _fake_run(tmp_path, **kwargs):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake audio bytes")
    out = tmp_path / "sub" / "transcript.txt"
    segments = [
        SimpleNamespace(text=" Hello there. ", start=0.0, end=1.0),
        SimpleNamespace(text="Second line.", start=65.0, end=66.0),
    ]
    info = SimpleNamespace(language="en", language_probability=0.99, duration=66.0)
    fake_model = mock.MagicMock()
    fake_model.transcribe.return_value = (segments, info)
    with mock.patch.object(transcribe, "WhisperModel", return_value=fake_model):
        transcribe.transcribe(audio, out, model_size="tiny", language="en", **kwargs)
    return out


def test_transcribe_writes_timestamped_segments(tmp_path):
    out = _fake_run(tmp_path)
    assert out.read_text(encoding="utf-8") == "[0:00] Hello there.\n[1:05] Second line.\n"


def test_transcribe_without_timestamps(tmp_path):
    out = _fake_run(tmp_path, include_timestamps=False)
    assert out.read_text(encoding="utf-8") == "Hello there.\nSecond line.\n"


def test_transcribe_reports_progress(tmp_path):
    seen = []
    _fake_run(tmp_path, progress_callback=seen.append)
    assert seen and seen[-1] == 1.0  # final callback reports completion
