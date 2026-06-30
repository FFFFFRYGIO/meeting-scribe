"""Tests for the filesystem meeting store."""

from __future__ import annotations

from datetime import datetime

import pytest

import store


@pytest.fixture
def meetings_dir(tmp_path, monkeypatch):
    """Point the store at a temporary results directory."""
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    return tmp_path


def test_create_meeting_writes_metadata(meetings_dir):
    m = store.create_meeting(
        title="Planning",
        source="discord",
        channel="general",
        now=datetime(2026, 6, 30, 14, 30, 5),
    )
    assert m.name == "general-2026-06-30_14-30-05"
    assert (m.dir / "metadata.json").exists()

    reloaded = store.get_meeting(m.name)
    assert reloaded.title == "Planning"
    assert reloaded.channel == "general"
    assert reloaded.source == "discord"


def test_save_transcript_and_summary(meetings_dir):
    m = store.create_meeting(title="x")
    store.save_transcript(m, "hello world")
    store.save_summary(m, "# Summary\nshort")

    assert m.has_transcript and m.has_summary
    assert m.transcript_text() == "hello world"
    assert "Summary" in m.summary_text()


def test_list_meetings_newest_first(meetings_dir):
    store.create_meeting(title="old", now=datetime(2026, 1, 1, 9, 0, 0))
    store.create_meeting(title="new", now=datetime(2026, 6, 1, 9, 0, 0))
    titles = [m.title for m in store.list_meetings()]
    assert titles == ["new", "old"]


def test_find_meeting_by_date_name_and_latest(meetings_dir):
    a = store.create_meeting(title="alpha", now=datetime(2026, 6, 30, 10, 0, 0))
    store.create_meeting(title="beta", now=datetime(2026, 7, 1, 10, 0, 0))

    assert store.find_meeting("2026-06-30").name == a.name  # by date
    assert store.find_meeting("alpha").name == a.name  # by title
    assert store.find_meeting(None).title == "beta"  # latest
    assert store.find_meeting("nonexistent") is None


def test_update_persists_fields(meetings_dir):
    m = store.create_meeting(title="x")
    m.update(participants=["Alice", "Bob"], duration_seconds=12.0)
    reloaded = store.get_meeting(m.name)
    assert reloaded.participants == ["Alice", "Bob"]
    assert reloaded.duration_seconds == 12.0
