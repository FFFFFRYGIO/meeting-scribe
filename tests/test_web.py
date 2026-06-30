"""Tests for the FastAPI web UI.

Claude calls and the heavy processing pipeline are mocked; we verify routing,
settings persistence, and that the Q&A / upload endpoints wire through to the
right helpers.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import ai
import settings as settings_mod
import store
import web


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path / "results")
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", tmp_path / "settings.json")
    # Auth is disabled unless a test opts in (keeps these tests hermetic).
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    return TestClient(web.app)


def test_index_lists_meetings(client):
    store.create_meeting(title="Daily sync")
    body = client.get("/").text
    assert "Daily sync" in body


def test_settings_save_round_trip(client, monkeypatch):
    saved = {}
    monkeypatch.setattr(web, "save_settings", lambda s: saved.setdefault("s", s))

    resp = client.post(
        "/settings",
        data={
            "claude_model": "claude-opus-4-8",
            "whisper_model": "small",
            "language": "pl",
            "summary_system": "sys",
            "summary_instructions": "instr",
            "qa_system": "qa",
            "section_title": ["Overview", "Risks", ""],
            "section_instructions": ["ov", "risk", ""],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Empty-title rows are dropped; filled ones are kept in order.
    assert [s.title for s in saved["s"].sections] == ["Overview", "Risks"]
    assert saved["s"].language == "pl"


def test_ask_uses_ai_answer(client, monkeypatch):
    m = store.create_meeting(title="Q meeting")
    store.save_transcript(m, "Bob owns the docs.")
    monkeypatch.setattr(ai, "answer", lambda q, t: f"answer to: {q}")

    body = client.post(f"/meeting/{m.name}/ask", data={"question": "who?"}).text
    assert "answer to: who?" in body


def test_upload_processes_and_redirects(client, monkeypatch):
    def fake_process(meeting, media, *a, **k):
        store.save_transcript(meeting, "transcribed")
        store.save_summary(meeting, "summarised")
        return meeting

    monkeypatch.setattr(web, "process_meeting", fake_process)

    resp = client.post(
        "/upload",
        data={"title": "Uploaded call"},
        files={"file": ("call.mp3", b"fake-bytes", "audio/mpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/meeting/")
    assert store.list_meetings()[0].title == "Uploaded call"


def test_meeting_not_found(client):
    assert client.get("/meeting/nope").status_code == 404


def test_basic_auth_gates_ui_when_configured(client, monkeypatch):
    import base64

    monkeypatch.setenv("AUTH_USERNAME", "Orka")
    monkeypatch.setenv("AUTH_PASSWORD", "Walen")

    # No credentials → challenged.
    r = client.get("/")
    assert r.status_code == 401 and "Basic" in r.headers.get("www-authenticate", "")

    # Wrong password → still blocked.
    bad = base64.b64encode(b"Orka:nope").decode()
    assert client.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401

    # Correct credentials → allowed through.
    ok = base64.b64encode(b"Orka:Walen").decode()
    assert client.get("/", headers={"Authorization": f"Basic {ok}"}).status_code == 200

    # Health check stays public for Coolify.
    assert client.get("/healthz").status_code == 200
