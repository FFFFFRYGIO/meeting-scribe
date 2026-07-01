"""Tests for the Google Meet bot wiring.

Playwright and ffmpeg are never launched here — we test the ffmpeg command shape
and the web wiring (create meeting → record → process, and the stop signal).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import ai
import meet_bot
import settings as settings_mod
import store
import web


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path / "results")
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", tmp_path / "settings.json")
    settings_mod.save_settings(
        settings_mod.ExtractionSettings(two_pass=False), tmp_path / "settings.json"
    )
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.setattr(ai, "title", lambda *a, **k: "")
    return TestClient(web.app)


def test_start_ffmpeg_builds_pulse_command(tmp_path, monkeypatch):
    captured = {}

    class _Proc:
        def poll(self):
            return None

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(meet_bot.subprocess, "Popen", fake_popen)
    meet_bot._start_ffmpeg(tmp_path / "sub" / "out.mp3")

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "pulse" in cmd and meet_bot.AUDIO_DEVICE in cmd
    assert str(tmp_path / "sub" / "out.mp3") in cmd


def test_meet_start_records_then_processes(client, monkeypatch):
    def fake_record(url, out_audio, **kwargs):
        Path(out_audio).write_bytes(b"FAKE-AUDIO")  # simulate captured audio
        return out_audio

    def fake_process(meeting, media, *a, **k):
        store.save_transcript(meeting, "[0:00] hello")
        store.save_summary(meeting, "s")

    monkeypatch.setattr(meet_bot, "record_meet", fake_record)
    monkeypatch.setattr(web, "process_meeting", fake_process)

    resp = client.post(
        "/meet",
        data={"url": "https://meet.google.com/abc-defg-hij", "project": "DroneScanner"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    m = store.list_meetings()[0]
    assert m.source == "meet" and m.project == "DroneScanner"
    assert m.status == "done" and m.has_summary and m.has_transcript


def test_meet_recording_failure_marks_error(client, monkeypatch):
    def boom(url, out_audio, **kwargs):
        raise RuntimeError("could not join")

    monkeypatch.setattr(meet_bot, "record_meet", boom)
    client.post("/meet", data={"url": "https://meet.google.com/x"}, follow_redirects=False)
    m = store.list_meetings()[0]
    assert m.status == "error" and "could not join" in m.error


def test_stop_recording_sets_event(client):
    m = store.create_meeting(title="x", source="meet", status="processing")
    event = threading.Event()
    web._meet_stops[m.name] = event
    client.post(f"/meeting/{m.name}/stop-recording", follow_redirects=False)
    assert event.is_set()
