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


def test_find_meetings_disambiguates_same_date(meetings_dir):
    a = store.create_meeting(title="alpha", now=datetime(2026, 6, 30, 10, 0, 0))
    b = store.create_meeting(title="beta", now=datetime(2026, 6, 30, 14, 0, 0))
    store.create_meeting(title="other", now=datetime(2026, 7, 1, 9, 0, 0))

    # A bare date matches both meetings that day...
    same_day = {m.name for m in store.find_meetings("2026-06-30")}
    assert same_day == {a.name, b.name}
    # ...but the unique id matches exactly one.
    assert [m.name for m in store.find_meetings(a.name)] == [a.name]
    assert store.find_meetings("nothing") == []


def test_delete_meeting(meetings_dir):
    m = store.create_meeting(title="bye")
    assert m.dir.exists()
    assert store.delete_meeting(m.name) is True
    assert store.get_meeting(m.name) is None
    assert not m.dir.exists()
    # Missing / traversal names are refused.
    assert store.delete_meeting("does-not-exist") is False
    assert store.delete_meeting("../escape") is False


def test_qa_history_round_trip(meetings_dir):
    m = store.create_meeting(title="qa")
    assert store.load_qa(m) == []
    store.append_qa(m, "q1", "a1")
    store.append_qa(m, "q2", "a2")
    qa = store.load_qa(m)
    assert [(t["q"], t["a"]) for t in qa] == [("q1", "a1"), ("q2", "a2")]
    assert all("at" in t for t in qa)


def test_search_matches_transcript_and_title(meetings_dir):
    a = store.create_meeting(title="Planning", now=datetime(2026, 6, 1, 9, 0, 0))
    store.save_transcript(a, "we discussed the roadmap and hiring")
    b = store.create_meeting(title="Roadmap sync", now=datetime(2026, 6, 2, 9, 0, 0))
    store.save_transcript(b, "unrelated content")

    names = {m.name for m, _ in store.search("roadmap")}
    assert names == {a.name, b.name}  # matches transcript (a) and title (b)
    hits = store.search("hiring")
    assert len(hits) == 1 and "hiring" in hits[0][1].lower()  # snippet contains the term
    assert store.search("   ") == []


def test_corpus_labels_meetings(meetings_dir):
    a = store.create_meeting(title="Planning", now=datetime(2026, 6, 1, 9, 0, 0))
    store.save_summary(a, "budget agreed")
    b = store.create_meeting(title="No content", now=datetime(2026, 6, 2, 9, 0, 0))

    text = store.corpus()
    assert "### Planning (2026-06-01, id=" in text
    assert "budget agreed" in text
    assert "No content" not in text  # meetings without summary/transcript are skipped
    assert store.corpus() and b.name not in text


def test_update_persists_fields(meetings_dir):
    m = store.create_meeting(title="x")
    m.update(participants=["Alice", "Bob"], duration_seconds=12.0)
    reloaded = store.get_meeting(m.name)
    assert reloaded.participants == ["Alice", "Bob"]
    assert reloaded.duration_seconds == 12.0
