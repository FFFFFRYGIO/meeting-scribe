"""Tests for the audio extraction step (MP4 -> MP3).

The actual moviepy/FFmpeg work is mocked so the tests stay fast and run
without any media files or FFmpeg installed.
"""

from __future__ import annotations

from unittest import mock

import pytest

import extract_audio


def test_extract_audio_missing_video_raises(tmp_path):
    missing = tmp_path / "nope.mp4"
    with pytest.raises(FileNotFoundError):
        extract_audio.extract_audio(missing, tmp_path / "out.mp3")


def test_extract_audio_writes_audio_track(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video bytes")
    out = tmp_path / "sub" / "audio.mp3"

    fake_clip = mock.MagicMock()
    with mock.patch.object(extract_audio, "VideoFileClip", return_value=fake_clip) as clip_cls:
        result = extract_audio.extract_audio(video, out, bitrate="128k")

    assert result == out
    clip_cls.assert_called_once_with(str(video))
    fake_clip.audio.write_audiofile.assert_called_once()
    # Parent directory was created for us.
    assert out.parent.is_dir()
    # Clip is always released.
    fake_clip.close.assert_called_once()


def test_extract_audio_no_audio_track_raises_and_closes(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video bytes")

    fake_clip = mock.MagicMock()
    fake_clip.audio = None
    with mock.patch.object(extract_audio, "VideoFileClip", return_value=fake_clip):
        with pytest.raises(ValueError):
            extract_audio.extract_audio(video, tmp_path / "audio.mp3")

    fake_clip.close.assert_called_once()
