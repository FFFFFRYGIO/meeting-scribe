"""On-disk store for recorded meetings.

A meeting is just a folder under ``results/`` holding everything about one
recording:

    results/<name>/
        metadata.json   # title, source, channel, participants, timestamps, flags
        audio.mp3       # the (mixed) recording, when there is one
        transcript.txt  # plain-text transcript
        summary.md      # AI-generated summary

This is deliberately filesystem-only — no database — so it stays simple and
inspectable. The web UI and the Discord bot both go through this module.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import RESULTS_DIR, ensure_parent

METADATA_NAME = "metadata.json"
TRANSCRIPT_NAME = "transcript.txt"
SUMMARY_NAME = "summary.md"
AUDIO_NAME = "audio.mp3"

# Characters allowed in a meeting folder name (filesystem-safe on every OS).
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _slugify(text: str) -> str:
    """Turn arbitrary text into a safe folder-name fragment."""
    slug = _SAFE_NAME.sub("-", text.strip()).strip("-")
    return slug or "meeting"


@dataclass
class Meeting:
    """A single recorded/processed meeting, backed by a folder on disk."""

    name: str  # folder name, unique; used as the id
    dir: Path
    title: str = ""
    created_at: str = ""  # ISO-8601
    source: str = "upload"  # "discord" | "upload"
    channel: str = ""  # discord channel name, if any
    participants: list[str] = field(default_factory=list)
    duration_seconds: float | None = None

    # ---- derived paths -------------------------------------------------
    @property
    def transcript_path(self) -> Path:
        return self.dir / TRANSCRIPT_NAME

    @property
    def summary_path(self) -> Path:
        return self.dir / SUMMARY_NAME

    @property
    def audio_path(self) -> Path:
        return self.dir / AUDIO_NAME

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path.exists()

    @property
    def has_summary(self) -> bool:
        return self.summary_path.exists()

    @property
    def has_audio(self) -> bool:
        return self.audio_path.exists()

    # ---- content -------------------------------------------------------
    def transcript_text(self) -> str:
        return self.transcript_path.read_text(encoding="utf-8") if self.has_transcript else ""

    def summary_text(self) -> str:
        return self.summary_path.read_text(encoding="utf-8") if self.has_summary else ""

    # ---- persistence ---------------------------------------------------
    def metadata(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "created_at": self.created_at,
            "source": self.source,
            "channel": self.channel,
            "participants": self.participants,
            "duration_seconds": self.duration_seconds,
        }

    def save_metadata(self) -> None:
        path = ensure_parent(self.dir / METADATA_NAME)
        path.write_text(json.dumps(self.metadata(), indent=2, ensure_ascii=False), encoding="utf-8")

    def update(self, **fields) -> Meeting:
        """Update metadata fields in place, persist, and return self."""
        for key, value in fields.items():
            setattr(self, key, value)
        self.save_metadata()
        return self


def meetings_root() -> Path:
    return RESULTS_DIR


def _load(dir: Path) -> Meeting | None:
    meta_path = dir / METADATA_NAME
    if not meta_path.exists():
        return None
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    return Meeting(
        name=data.get("name", dir.name),
        dir=dir,
        title=data.get("title", ""),
        created_at=data.get("created_at", ""),
        source=data.get("source", "upload"),
        channel=data.get("channel", ""),
        participants=data.get("participants", []) or [],
        duration_seconds=data.get("duration_seconds"),
    )


def list_meetings() -> list[Meeting]:
    """Return all meetings, newest first."""
    root = meetings_root()
    meetings = [m for d in root.iterdir() if d.is_dir() and (m := _load(d))]
    meetings.sort(key=lambda m: m.created_at, reverse=True)
    return meetings


def get_meeting(name: str) -> Meeting | None:
    """Return the meeting whose folder name matches *name* exactly."""
    return _load(meetings_root() / name)


def find_meeting(query: str | None) -> Meeting | None:
    """Best-effort lookup for the Discord bot.

    With no query, returns the most recent meeting. Otherwise matches the query
    (case-insensitive) against the folder name, title, or date — handy for
    "question 2026-06-30 ...".
    """
    meetings = list_meetings()
    if not meetings:
        return None
    if not query:
        return meetings[0]
    needle = query.strip().lower()
    for meeting in meetings:
        haystack = f"{meeting.name} {meeting.title} {meeting.created_at}".lower()
        if needle in haystack:
            return meeting
    return None


def create_meeting(
    *,
    title: str = "",
    source: str = "upload",
    channel: str = "",
    participants: list[str] | None = None,
    name: str | None = None,
    now: datetime | None = None,
) -> Meeting:
    """Create a new meeting folder with metadata and return it.

    The folder name is timestamped (and prefixed with the channel/title slug
    when given) so meetings never collide.
    """
    now = now or datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    if name is None:
        prefix = _slugify(channel or title or "meeting")
        name = f"{prefix}-{stamp}"
    name = _slugify(name)

    meeting = Meeting(
        name=name,
        dir=meetings_root() / name,
        title=title,
        created_at=now.isoformat(timespec="seconds"),
        source=source,
        channel=channel,
        participants=participants or [],
    )
    meeting.dir.mkdir(parents=True, exist_ok=True)
    meeting.save_metadata()
    return meeting


def save_transcript(meeting: Meeting, text: str) -> Path:
    path = ensure_parent(meeting.transcript_path)
    path.write_text(text, encoding="utf-8")
    return path


def save_summary(meeting: Meeting, text: str) -> Path:
    path = ensure_parent(meeting.summary_path)
    path.write_text(text, encoding="utf-8")
    return path


def import_audio(meeting: Meeting, src: Path) -> Path:
    """Copy an audio file into the meeting folder as the canonical recording."""
    dest = ensure_parent(meeting.audio_path)
    shutil.copyfile(src, dest)
    return dest
