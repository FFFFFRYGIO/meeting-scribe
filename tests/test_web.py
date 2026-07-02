"""Tests for the FastAPI web UI.

Claude calls and the heavy processing pipeline are mocked; we verify routing,
settings persistence, and that the Q&A / upload endpoints wire through to the
right helpers.
"""

from __future__ import annotations

from pathlib import Path

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
    # Single-pass by default so call counts are deterministic (a test can override).
    settings_mod.save_settings(
        settings_mod.ExtractionSettings(two_pass=False), tmp_path / "settings.json"
    )
    # Auth is disabled unless a test opts in (keeps these tests hermetic).
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    # Stub auto-title so tests never hit the network (a test can override).
    monkeypatch.setattr(ai, "title", lambda *a, **k: "")
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


def test_settings_save_persists_summarize_toggle(client, monkeypatch):
    saved = {}
    monkeypatch.setattr(web, "save_settings", lambda s: saved.__setitem__("s", s))

    # Checkbox present → summaries stay on.
    client.post("/settings", data={"summarize": "1"}, follow_redirects=False)
    assert saved["s"].summarize is True

    # Checkbox absent (unchecked) → transcript-only, no Claude call.
    client.post("/settings", data={}, follow_redirects=False)
    assert saved["s"].summarize is False


def test_transcript_only_mode_skips_claude(client, monkeypatch):
    settings_mod.save_settings(
        settings_mod.ExtractionSettings(two_pass=False, summarize=False)
    )
    m = store.create_meeting(title="", status="error")  # blank title → would auto-title
    store.save_transcript(m, "some transcript text")

    called = {"summarize": 0, "title": 0}

    def bump(key):
        called[key] += 1

    monkeypatch.setattr(web, "summarize_meeting", lambda *a, **k: bump("summarize"))
    monkeypatch.setattr(ai, "title", lambda *a, **k: bump("title") or "X")

    resp = client.post(f"/meeting/{m.name}/reprocess", follow_redirects=False)
    assert resp.status_code == 303
    # No Anthropic calls at all: neither the summary nor the auto-title runs.
    assert called == {"summarize": 0, "title": 0}
    assert store.get_meeting(m.name).status == "done"


def test_ask_saves_and_shows_qa_history(client, monkeypatch):
    m = store.create_meeting(title="Q meeting")
    store.save_transcript(m, "Bob owns the docs.")
    monkeypatch.setattr(ai, "answer", lambda q, t, **k: f"answer to: {q}")

    # POST-redirect-GET: the answer is persisted and shown in the Q&A history.
    body = client.post(f"/meeting/{m.name}/ask", data={"question": "who?"}).text
    assert "answer to: who?" in body and "who?" in body
    assert [t["q"] for t in store.load_qa(m)] == ["who?"]


def test_ask_passes_history_for_followups(client, monkeypatch):
    m = store.create_meeting(title="threaded")
    store.save_transcript(m, "transcript")
    store.append_qa(m, "first?", "first answer")
    seen = {}
    monkeypatch.setattr(
        ai, "answer", lambda q, t, **k: seen.update(history=k.get("history")) or "ok"
    )

    client.post(f"/meeting/{m.name}/ask", data={"question": "second?"})
    assert [h["q"] for h in seen["history"]] == ["first?"]  # prior turn passed as context


def test_search_finds_text(client):
    m = store.create_meeting(title="Budget review")
    store.save_transcript(m, "We agreed the marketing budget is 50k.")
    body = client.get("/search", params={"q": "marketing budget"}).text
    assert "Budget review" in body and "marketing budget" in body
    assert "0 results" in client.get("/search", params={"q": "zzz-nope"}).text


def test_ask_all_uses_corpus(client, monkeypatch):
    m = store.create_meeting(title="Budget review")
    store.save_summary(m, "budget is 50k")
    captured = {}

    def fake_ask(question, corpus, *a, **k):
        captured["q"] = question
        captured["corpus"] = corpus
        return "Across meetings: 50k (Budget review)"

    monkeypatch.setattr(ai, "ask_across", fake_ask)
    body = client.get("/ask", params={"q": "budget?"}).text
    assert "Across meetings: 50k" in body
    assert "Budget review" in captured["corpus"] and captured["q"] == "budget?"


def test_upload_sets_project(client, monkeypatch):
    monkeypatch.setattr(web, "process_meeting", lambda *a, **k: None)
    client.post(
        "/upload",
        data={"project": "DroneScanner"},
        files={"file": ("c.mp3", b"x", "audio/mpeg")},
        follow_redirects=False,
    )
    assert store.list_meetings()[0].project == "DroneScanner"


def test_upload_custom_project_overrides_dropdown(client, monkeypatch):
    monkeypatch.setattr(web, "process_meeting", lambda *a, **k: None)
    client.post(
        "/upload",
        data={"project": "DocCompan", "project_custom": "Inne"},
        files={"file": ("c.mp3", b"x", "audio/mpeg")},
        follow_redirects=False,
    )
    assert store.list_meetings()[0].project == "Inne"


def test_set_project_route(client):
    m = store.create_meeting(title="x")
    client.post(f"/meeting/{m.name}/project", data={"project": "DocCompan"}, follow_redirects=False)
    assert store.get_meeting(m.name).project == "DocCompan"


def test_recorder_page_renders(client):
    body = client.get("/recorder").text
    assert "Start recording" in body and "/api/upload" in body


def test_api_upload_creates_meeting_and_returns_json(client, monkeypatch):
    monkeypatch.setattr(web, "_recorder_job", lambda *a, **k: None)  # skip ffmpeg/pydub
    resp = client.post(
        "/api/upload",
        data={"title": "Laptop sync", "project": "DroneScanner"},
        files={"file": ("recording.webm", b"AUDIO", "audio/webm")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == f"/meeting/{data['name']}"
    m = store.get_meeting(data["name"])
    assert m.source == "recorder" and m.project == "DroneScanner" and m.status == "processing"
    assert any(p.name.startswith("source") for p in m.dir.iterdir())  # blob saved to disk


def test_rename_updates_title(client):
    m = store.create_meeting(title="old")
    client.post(f"/meeting/{m.name}/rename", data={"title": "New name"}, follow_redirects=False)
    assert store.get_meeting(m.name).title == "New name"


def test_two_pass_runs_preview_then_deep(client, monkeypatch):
    settings_mod.save_settings(
        settings_mod.ExtractionSettings(
            two_pass=True, preview_model="small", whisper_model="large-v3"
        ),
        settings_mod.SETTINGS_FILE,
    )
    models = []

    def fake_process(meeting, media, *a, settings=None, **k):
        models.append(settings.whisper_model)
        store.save_transcript(meeting, "t")
        store.save_summary(meeting, "s")

    monkeypatch.setattr(web, "process_meeting", fake_process)
    client.post(
        "/upload",
        files={"file": ("c.mp3", b"x", "audio/mpeg")},
        follow_redirects=False,
    )
    assert models == ["small", "large-v3"]  # fast preview first, then the deep pass


def test_upload_redirects_and_processes_in_background(client, monkeypatch):
    seen = {}

    def fake_process(meeting, media, *a, **k):
        # media was streamed to disk before the background task ran
        seen["media_exists"] = Path(media).exists()
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
    # Responds immediately with a redirect to the meeting page.
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/meeting/")

    # TestClient runs the background task; the meeting ends up done.
    m = store.list_meetings()[0]
    assert m.title == "Uploaded call"
    assert m.status == "done"
    assert m.has_summary and m.has_transcript
    assert seen["media_exists"] is True


def test_upload_marks_error_on_failure(client, monkeypatch):
    def boom(meeting, media, *a, **k):
        raise RuntimeError("ffmpeg blew up")

    monkeypatch.setattr(web, "process_meeting", boom)
    resp = client.post(
        "/upload",
        files={"file": ("call.mp3", b"x", "audio/mpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    m = store.list_meetings()[0]
    assert m.status == "error" and "ffmpeg blew up" in m.error


def test_progress_callback_updates_meeting(client, monkeypatch):
    seen = {}

    def fake_process(meeting, media, *a, progress_callback=None, **k):
        if progress_callback:
            progress_callback(0.5)
            seen["mid"] = store.get_meeting(meeting.name).progress  # persisted mid-run
        store.save_transcript(meeting, "t")
        store.save_summary(meeting, "s")

    monkeypatch.setattr(web, "process_meeting", fake_process)
    client.post(
        "/upload",
        files={"file": ("c.mp3", b"x", "audio/mpeg")},
        follow_redirects=False,
    )
    m = store.list_meetings()[0]
    assert seen["mid"] == 50  # progress persisted during transcription
    assert m.status == "done" and m.progress == 100


def test_processing_meeting_page_auto_refreshes(client):
    m = store.create_meeting(title="In progress", status="processing")
    body = client.get(f"/meeting/{m.name}").text
    assert 'http-equiv="refresh"' in body and "Processing" in body


def test_reprocess_only_summarises_when_transcript_exists(client, monkeypatch):
    m = store.create_meeting(title="Has transcript", status="error")
    store.save_transcript(m, "some transcript text")

    called = {"summarize": 0, "process": 0}

    def fake_summarize(meeting, *a, **k):
        called["summarize"] += 1

    def fake_process(*a, **k):
        called["process"] += 1

    monkeypatch.setattr(web, "summarize_meeting", fake_summarize)
    monkeypatch.setattr(web, "process_meeting", fake_process)

    resp = client.post(f"/meeting/{m.name}/reprocess", follow_redirects=False)
    assert resp.status_code == 303
    # Transcript present → only the summary step runs, full pipeline skipped.
    assert called == {"summarize": 1, "process": 0}
    assert store.get_meeting(m.name).status == "done"


def test_reprocess_forces_retranscription_when_audio_exists(client, monkeypatch):
    m = store.create_meeting(title="Redo with better model", status="done")
    store.save_transcript(m, "old transcript")
    m.audio_path.write_bytes(b"fake-audio")  # audio present → force re-transcribe

    called = {"summarize": 0, "process": 0}

    def fake_summarize(meeting, *a, **k):
        called["summarize"] += 1

    def fake_process(meeting, media, *a, **k):
        called["process"] += 1

    monkeypatch.setattr(web, "summarize_meeting", fake_summarize)
    monkeypatch.setattr(web, "process_meeting", fake_process)

    client.post(f"/meeting/{m.name}/reprocess", follow_redirects=False)
    # Audio present → full pipeline (re-transcribe), not summary-only.
    assert called == {"summarize": 0, "process": 1}


def test_reprocess_marks_error_when_source_missing(client):
    m = store.create_meeting(title="Nothing to process", status="processing")
    resp = client.post(f"/meeting/{m.name}/reprocess", follow_redirects=False)
    assert resp.status_code == 303
    reloaded = store.get_meeting(m.name)
    assert reloaded.status == "error" and "re-upload" in reloaded.error.lower()


def test_meeting_not_found(client):
    assert client.get("/meeting/nope").status_code == 404


def test_render_transcript_html_makes_timestamps_clickable():
    out = web.render_transcript_html("[1:05] hello <world>\nno timestamp here")
    assert '<a href="#" class="ts" data-s="65">[1:05]</a> hello &lt;world&gt;' in out
    assert "no timestamp here" in out  # plain lines pass through (escaped)


def test_audio_route_serves_and_404s(client):
    m = store.create_meeting(title="with audio")
    assert client.get(f"/meeting/{m.name}/audio").status_code == 404  # no audio yet
    m.audio_path.write_bytes(b"ID3fake")
    assert client.get(f"/meeting/{m.name}/audio").status_code == 200


def test_download_routes(client):
    m = store.create_meeting(title="dl")
    store.save_transcript(m, "[0:00] hi")
    store.save_summary(m, "# S")
    r = client.get(f"/meeting/{m.name}/download/transcript")
    assert r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "")
    assert client.get(f"/meeting/{m.name}/download/summary").status_code == 200
    assert client.get(f"/meeting/{m.name}/download/bogus").status_code == 404


def test_upload_auto_titles_when_blank(client, monkeypatch):
    monkeypatch.setattr(ai, "title", lambda *a, **k: "Sprint Planning")

    def fake_process(meeting, media, *a, **k):
        store.save_transcript(meeting, "[0:00] we planned the sprint")
        store.save_summary(meeting, "s")

    monkeypatch.setattr(web, "process_meeting", fake_process)
    client.post("/upload", files={"file": ("x.mp3", b"x", "audio/mpeg")}, follow_redirects=False)
    assert store.list_meetings()[0].title == "Sprint Planning"


def test_delete_meeting_route(client):
    m = store.create_meeting(title="bye")
    resp = client.post(f"/meeting/{m.name}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert store.get_meeting(m.name) is None


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
