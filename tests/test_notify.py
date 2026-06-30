"""Tests for the wait-for-file notification helper."""

from __future__ import annotations

import notify


def test_wait_for_file_returns_immediately_when_present(tmp_path):
    target = tmp_path / "audio.txt"
    target.write_text("done", encoding="utf-8")

    # File already exists, beep disabled -> should return without sleeping.
    result = notify.wait_for_file(target, poll_seconds=0, beep=False)
    assert result == target


def test_wait_for_file_polls_until_file_appears(tmp_path, monkeypatch):
    target = tmp_path / "late.txt"
    calls = {"n": 0}

    real_sleep = notify.time.sleep

    def fake_sleep(_seconds):
        # Create the file after the first poll so the loop then exits.
        calls["n"] += 1
        if calls["n"] == 1:
            target.write_text("ready", encoding="utf-8")

    monkeypatch.setattr(notify.time, "sleep", fake_sleep)
    try:
        result = notify.wait_for_file(target, poll_seconds=0, beep=False)
    finally:
        notify.time.sleep = real_sleep

    assert result == target
    assert calls["n"] >= 1
