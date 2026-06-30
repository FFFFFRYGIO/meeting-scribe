"""Meeting Scribe — full pipeline entry point.

Give it a single file and it figures out the rest:

    * a **video** (e.g. ``.mp4``)  ->  extract audio  ->  transcribe  ->  text
    * an **audio** file (e.g. ``.mp3``)  ->  transcribe  ->  text

You don't tell it which kind of file you have — it decides from the extension.

Examples::

    # Video: audio is extracted automatically, then transcribed
    uv run python main.py data/meeting/video.mp4

    # Audio: transcribed directly, no extraction step
    uv run python main.py data/meeting/audio.mp3 --language pl

    # Choose where the transcript goes / which model to use
    uv run python main.py recording.mp4 --transcript results/notes.txt --model medium

The individual steps are also available as standalone commands:
``extract-audio``, ``transcribe`` and ``wait-for-file``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from config import (
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    RESULTS_DIR,
    classify_media,
    default_run_name,
)
from extract_audio import extract_audio
from transcribe import transcribe


def run(
    input_file: Path,
    *,
    name: str | None = None,
    audio: Path | None = None,
    transcript: Path | None = None,
    model: str = DEFAULT_MODEL,
    language: str | None = DEFAULT_LANGUAGE,
) -> Path:
    """Process *input_file* end-to-end and return the transcript path.

    Routing is automatic: a video is extracted to audio first, an audio file is
    transcribed directly.
    """
    input_file = Path(input_file)
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    kind = classify_media(input_file)  # "video" or "audio" (raises if unknown)

    # All generated files for a run live together under results/<name>/.
    name = name or default_run_name()
    out_dir = RESULTS_DIR / name
    transcript = transcript or (out_dir / f"{input_file.stem}.txt")

    if kind == "video":
        audio = audio or (out_dir / f"{input_file.stem}.mp3")
        print("Detected video input -> extracting audio, then transcribing.")
        extract_audio(input_file, audio)
        source_audio = audio
    else:
        print("Detected audio input -> transcribing directly.")
        source_audio = input_file

    transcribe(source_audio, transcript, model_size=model, language=language)
    print(f"\nAll done. Transcript: {transcript}")
    return transcript


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a meeting recording (video or audio) into a text "
        "transcript. The input type is detected automatically.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the input file (video, e.g. .mp4, or audio, e.g. .mp3)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Output folder name under results/ (default: meeting-<YYYY-MM-DD_HH-MM-SS>)",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        help="Override the intermediate audio path (only used for video input)",
    )
    parser.add_argument("--transcript", type=Path, help="Override the output transcript path")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"faster-whisper model size (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help="Language code, e.g. 'pl' or 'en' (default: auto-detect)",
    )
    args = parser.parse_args()

    try:
        run(
            args.input,
            name=args.name,
            audio=args.audio,
            transcript=args.transcript,
            model=args.model,
            language=args.language,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
