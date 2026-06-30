"""Shared paths and defaults for Meeting Scribe.

Keeping these in one place means every script agrees on where the input
recordings live (``data/``) and where the generated files go (``results/``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Project root = one level up from this file (src/config.py).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# Top-level data / results directories. Both are kept in git via .gitkeep,
# while their contents (recordings, transcripts) are ignored.
DATA_DIR: Path = PROJECT_ROOT / "data"
RESULTS_DIR: Path = PROJECT_ROOT / "results"

# Defaults for the transcription step.
DEFAULT_MODEL: str = "small"  # faster-whisper model size
DEFAULT_LANGUAGE: str | None = None  # None = auto-detect

# Prefix used when generating a default run name.
RUN_NAME_PREFIX: str = "meeting"
# Timestamp format used in default run names; filesystem-safe on every OS.
RUN_NAME_TIMESTAMP_FORMAT: str = "%Y-%m-%d_%H-%M-%S"

# Recognised input file types. Used by main.py to decide whether an input
# needs audio extraction first (video) or can be transcribed directly (audio).
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".wmv", ".flv"}
)
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
)


def classify_media(path: str | Path) -> str:
    """Return ``"video"`` or ``"audio"`` based on a file's extension.

    Raises ``ValueError`` for unrecognised extensions so callers can give the
    user a clear message instead of failing deep inside FFmpeg.
    """
    suffix = Path(path).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    supported = ", ".join(sorted(VIDEO_EXTENSIONS | AUDIO_EXTENSIONS))
    raise ValueError(f"Unsupported file type '{suffix or path}'. Supported extensions: {supported}")


def default_run_name(now: datetime | None = None) -> str:
    """Return a timestamped run name, e.g. ``meeting-2026-06-30_14-30-00``.

    Used as the default folder name under both ``data/`` and ``results/`` so
    each run gets its own isolated input/output folders.
    """
    now = now or datetime.now()
    return f"{RUN_NAME_PREFIX}-{now.strftime(RUN_NAME_TIMESTAMP_FORMAT)}"


def ensure_parent(path: Path) -> Path:
    """Create the parent directory of *path* if it does not exist yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
