"""Tunable extraction settings for Meeting Scribe.

Everything the AI is asked to pull out of a meeting lives here as plain data, so
it can be edited from the web UI (or by hand) without touching code. The summary
is built by composing these fields into a prompt — change the wording, add or
remove a section, and the next summary follows the new shape.

Settings are persisted as JSON under ``data/settings.json``. If the file does
not exist yet, :func:`load_settings` writes the bundled defaults so the file is
always there to edit.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import DATA_DIR, DEFAULT_LANGUAGE, DEFAULT_MODEL, ensure_parent

# Claude model used for summaries and Q&A. Opus 4.8 is the current top model.
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"

# Where the editable settings live.
SETTINGS_FILE: Path = DATA_DIR / "settings.json"


@dataclass
class Section:
    """One block the summary should contain.

    ``title`` is the heading shown in the summary; ``instructions`` tells the
    model what to put under it. Editing these is the main way to "tune what we
    extract" from a meeting.
    """

    title: str
    instructions: str


@dataclass
class ExtractionSettings:
    """All knobs that shape transcription and extraction."""

    # Claude model for summary + Q&A.
    claude_model: str = DEFAULT_CLAUDE_MODEL
    # Whether to run the Claude summary (+ auto-title) step after transcription.
    # When False, processing stops at ``transcript.txt`` — pure local extraction
    # with no Anthropic API call, so no ANTHROPIC_API_KEY is needed. Q&A still
    # requires the key when used.
    summarize: bool = True
    # faster-whisper model size for the accurate ("deep") transcription pass.
    whisper_model: str = DEFAULT_MODEL
    # Two-pass transcription: a fast preview first, then refine with whisper_model.
    two_pass: bool = True
    # Fast model used for the quick preview pass.
    preview_model: str = "small"
    # Transcription language code (e.g. "pl", "en"); None = auto-detect.
    language: str | None = DEFAULT_LANGUAGE
    # System prompt that frames the summariser's role.
    summary_system: str = (
        "You are a meticulous meeting assistant. You read raw meeting "
        "transcripts and produce clear, faithful notes. Never invent facts that "
        "are not supported by the transcript. Write in the same language the "
        "meeting was held in."
    )
    # High-level instruction prepended before the section list.
    summary_instructions: str = (
        "Summarise the following meeting transcript. Be concise but complete, "
        "and base every statement strictly on what was said."
    )
    # The sections the summary should contain, in order.
    sections: list[Section] = field(
        default_factory=lambda: [
            Section(
                "Overview",
                "2-4 sentences capturing the purpose and outcome of the meeting.",
            ),
            Section(
                "Key points",
                "The most important topics discussed, as a short bulleted list.",
            ),
            Section(
                "Decisions",
                "Concrete decisions that were made. If none, say so explicitly.",
            ),
            Section(
                "Action items",
                "Tasks to do, each with the owner and any due date mentioned. "
                "Use a bulleted list; if none, say so.",
            ),
            Section(
                "Open questions",
                "Unresolved questions or follow-ups raised during the meeting.",
            ),
        ]
    )
    # System prompt that frames the Q&A assistant.
    qa_system: str = (
        "You answer questions about a single meeting using only its transcript. "
        "If the answer is not in the transcript, say you don't know rather than "
        "guessing. Answer in the language of the question."
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionSettings:
        # Only keep keys we know about, so stale/extra fields don't break load.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        sections = [Section(**s) for s in clean.pop("sections", [])]
        settings = cls(**clean)
        if sections:
            settings.sections = sections
        return settings


def load_settings(path: Path | None = None) -> ExtractionSettings:
    """Return the saved settings, creating the file with defaults if missing.

    Resolves ``SETTINGS_FILE`` at call time (not as a default arg) so tests and
    callers that patch the module-level path are respected.
    """
    path = Path(path) if path is not None else SETTINGS_FILE
    if not path.exists():
        settings = ExtractionSettings()
        save_settings(settings, path)
        return settings
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExtractionSettings.from_dict(data)


def save_settings(settings: ExtractionSettings, path: Path | None = None) -> Path:
    """Write *settings* to *path* (default: current ``SETTINGS_FILE``) as JSON."""
    path = ensure_parent(Path(path) if path is not None else SETTINGS_FILE)
    path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
