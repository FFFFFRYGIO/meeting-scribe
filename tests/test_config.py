"""Tests for shared paths and the timestamped default run name."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

import config


def test_default_run_name_with_fixed_timestamp():
    name = config.default_run_name(datetime(2026, 6, 30, 14, 30, 5))
    assert name == "meeting-2026-06-30_14-30-05"


def test_default_run_name_format_is_filesystem_safe():
    name = config.default_run_name()
    # Prefix + a timestamp; no characters that are illegal in folder names.
    assert re.fullmatch(r"meeting-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", name)
    assert not set(name) & set(r'<>:"/\|?* ')


def test_default_run_name_is_unique_over_time():
    a = config.default_run_name(datetime(2026, 6, 30, 14, 30, 5))
    b = config.default_run_name(datetime(2026, 6, 30, 14, 30, 6))
    assert a != b


def test_ensure_parent_creates_missing_directory(tmp_path):
    target = tmp_path / "nested" / "deep" / "file.txt"
    assert not target.parent.exists()
    returned = config.ensure_parent(target)
    assert returned == target
    assert target.parent.is_dir()


def test_data_and_results_dirs_under_project_root():
    assert config.DATA_DIR == config.PROJECT_ROOT / "data"
    assert config.RESULTS_DIR == config.PROJECT_ROOT / "results"


@pytest.mark.parametrize("name", ["video.mp4", "clip.MOV", "x.mkv", "y.webm"])
def test_classify_media_detects_video(name):
    assert config.classify_media(name) == "video"


@pytest.mark.parametrize("name", ["audio.mp3", "voice.WAV", "x.m4a", "y.flac"])
def test_classify_media_detects_audio(name):
    assert config.classify_media(name) == "audio"


@pytest.mark.parametrize("name", ["notes.txt", "archive.zip", "no_extension"])
def test_classify_media_rejects_unknown(name):
    with pytest.raises(ValueError, match="Unsupported file type"):
        config.classify_media(name)
