"""Turn a recording into a stored, summarised meeting.

This is the shared backbone behind both the web upload form and the Discord bot:
given a meeting folder and a media file, it transcribes (extracting audio first
if the input is a video), then asks Claude for a summary, writing both into the
meeting. Each step is skippable/observable so callers can report progress.
"""

from __future__ import annotations

from pathlib import Path

from ai import summarize
from config import classify_media
from extract_audio import extract_audio
from settings import ExtractionSettings, load_settings
from store import Meeting, import_audio, save_summary, save_transcript
from transcribe import transcribe


def transcribe_meeting(
    meeting: Meeting,
    media: Path,
    settings: ExtractionSettings | None = None,
) -> str:
    """Transcribe *media* into the meeting and return the transcript text.

    A video input is converted to audio first; an audio input is transcribed
    directly. The (audio) recording is stored alongside as the meeting's audio.
    """
    settings = settings or load_settings()
    media = Path(media)

    if classify_media(media) == "video":
        audio = meeting.dir / "extracted.mp3"
        extract_audio(media, audio)
        source_audio = audio
    else:
        source_audio = media

    import_audio(meeting, source_audio)
    transcribe(
        source_audio,
        meeting.transcript_path,
        model_size=settings.whisper_model,
        language=settings.language,
    )
    return meeting.transcript_text()


def summarize_meeting(
    meeting: Meeting,
    settings: ExtractionSettings | None = None,
) -> str:
    """Summarise the meeting's transcript and store the summary; return it."""
    settings = settings or load_settings()
    summary = summarize(meeting.transcript_text(), settings, title=meeting.title)
    save_summary(meeting, summary)
    return summary


def process_meeting(
    meeting: Meeting,
    media: Path,
    settings: ExtractionSettings | None = None,
) -> Meeting:
    """Full pipeline: transcribe *media*, then summarise, into *meeting*."""
    settings = settings or load_settings()
    transcribe_meeting(meeting, media, settings)
    summarize_meeting(meeting, settings)
    return meeting


def save_and_process_transcript(
    meeting: Meeting,
    transcript: str,
    settings: ExtractionSettings | None = None,
) -> Meeting:
    """Store an already-produced transcript, then summarise it.

    Used when transcription happened elsewhere (e.g. per-speaker tracks already
    transcribed) and only the summary step remains.
    """
    settings = settings or load_settings()
    save_transcript(meeting, transcript)
    summarize_meeting(meeting, settings)
    return meeting
