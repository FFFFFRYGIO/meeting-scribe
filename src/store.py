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
QA_NAME = "qa.jsonl"

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
    project: str = ""  # which project this recording belongs to
    channel: str = ""  # discord channel name, if any
    participants: list[str] = field(default_factory=list)
    duration_seconds: float | None = None
    status: str = "done"  # "processing" | "done" | "error"
    error: str = ""  # populated when status == "error"
    progress: int = 0  # transcription progress percent (0-100) while processing
    refining: bool = False  # True during the deep (2nd) transcription pass

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
            "project": self.project,
            "channel": self.channel,
            "participants": self.participants,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error": self.error,
            "progress": self.progress,
            "refining": self.refining,
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
        project=data.get("project", ""),
        channel=data.get("channel", ""),
        participants=data.get("participants", []) or [],
        duration_seconds=data.get("duration_seconds"),
        status=data.get("status", "done"),  # default keeps old meetings valid
        error=data.get("error", ""),
        progress=data.get("progress", 0),
        refining=data.get("refining", False),
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


def find_meetings(query: str) -> list[Meeting]:
    """Return every meeting matching *query* (newest first).

    Case-insensitive substring match against the unique name (id), title, or
    timestamp. A bare date can match several meetings; the unique name never does.
    """
    needle = query.strip().lower()
    if not needle:
        return []
    return [m for m in list_meetings() if needle in f"{m.name} {m.title} {m.created_at}".lower()]


def find_meeting(query: str | None) -> Meeting | None:
    """Single best match for *query*, or the most recent meeting when query is empty.

    Returns the newest match; use :func:`find_meetings` when you need to detect
    and disambiguate multiple matches.
    """
    meetings = list_meetings()
    if not meetings:
        return None
    if not query:
        return meetings[0]
    matches = find_meetings(query)
    return matches[0] if matches else None


def create_meeting(
    *,
    title: str = "",
    source: str = "upload",
    project: str = "",
    channel: str = "",
    participants: list[str] | None = None,
    name: str | None = None,
    status: str = "done",
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
        project=project,
        channel=channel,
        participants=participants or [],
        status=status,
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
    if Path(src).resolve() != dest.resolve():  # no-op when re-processing from audio.mp3
        shutil.copyfile(src, dest)
    return dest


def load_qa(meeting: Meeting) -> list[dict]:
    """Return the meeting's Q&A history (list of {"q", "a", "at"}), oldest first."""
    path = meeting.dir / QA_NAME
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def append_qa(meeting: Meeting, question: str, answer: str, now: datetime | None = None) -> None:
    """Append one question/answer pair to the meeting's Q&A history."""
    now = now or datetime.now()
    entry = {"q": question, "a": answer, "at": now.isoformat(timespec="seconds")}
    path = ensure_parent(meeting.dir / QA_NAME)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _snippet(text: str, needle: str, width: int = 160) -> str:
    """Return a short excerpt of *text* around the first case-insensitive *needle*."""
    i = text.lower().find(needle.lower())
    if i < 0:
        return text[:width].strip()
    start = max(0, i - width // 2)
    excerpt = text[start : start + width].strip()
    return ("…" if start else "") + excerpt + ("…" if start + width < len(text) else "")


def search(query: str) -> list[tuple[Meeting, str]]:
    """Find meetings whose title/transcript/summary contain *query*.

    Returns (meeting, snippet) pairs, newest first.
    """
    needle = query.strip().lower()
    if not needle:
        return []
    results = []
    for meeting in list_meetings():
        transcript = meeting.transcript_text()
        summary = meeting.summary_text()
        hay = f"{meeting.title}\n{transcript}\n{summary}".lower()
        if needle in hay:
            body = transcript if needle in transcript.lower() else (summary or meeting.title)
            results.append((meeting, _snippet(body, needle)))
    return results


def corpus(limit: int = 50, excerpt: int = 2000) -> str:
    """Build a compact, labelled corpus of recent meetings for cross-meeting Q&A.

    Prefers each meeting's summary (short); falls back to a transcript excerpt.
    Each block is headed with the title, date, and id so the model can cite it.
    """
    blocks = []
    for meeting in list_meetings()[:limit]:
        body = meeting.summary_text().strip() or meeting.transcript_text()[:excerpt].strip()
        if not body:
            continue
        label = meeting.title or meeting.name
        header = f"### {label} ({meeting.created_at[:10]}, id={meeting.name})"
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


def delete_meeting(name: str) -> bool:
    """Delete a meeting's folder and everything in it. Returns True if removed.

    Guarded to the meetings root so a crafted name can't escape and delete
    arbitrary paths.
    """
    root = meetings_root().resolve()
    target = (root / name).resolve()
    if target.parent != root or not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
