"""Transcribe an audio file into text (MP3 -> TXT).

Transcription runs locally with `faster-whisper`, so no API key or network
connection is required. The first run downloads the chosen model.

Used as a library::

    from transcribe import transcribe
    transcribe("data/meeting/audio.mp3", "results/meeting/audio.txt")

Used from the command line::

    uv run transcribe data/meeting/audio.mp3 results/meeting/audio.txt
    uv run transcribe data/meeting/audio.mp3 results/meeting/audio.txt --model medium --language pl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from faster_whisper import WhisperModel

from config import DEFAULT_LANGUAGE, DEFAULT_MODEL, ensure_parent


def transcribe(
    audio_path: str | Path,
    output_path: str | Path,
    *,
    model_size: str = DEFAULT_MODEL,
    language: str | None = DEFAULT_LANGUAGE,
    device: str = "auto",
    compute_type: str = "default",
) -> Path:
    """Transcribe *audio_path* and write the text to *output_path*.

    Returns the path of the created transcript file.
    """
    audio_path = Path(audio_path)
    output_path = ensure_parent(Path(output_path))

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    print(f"Loading model '{model_size}' (device={device}) ...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print(f"Transcribing {audio_path} ...")
    segments, info = model.transcribe(str(audio_path), language=language)
    print(f"Detected language: {info.language} (probability {info.language_probability:.2f})")

    with output_path.open("w", encoding="utf-8") as fh:
        for segment in segments:
            line = segment.text.strip()
            print(line)
            fh.write(line + "\n")

    print(f"Saved transcript: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe an audio file into text (MP3 -> TXT).",
    )
    parser.add_argument("audio", type=Path, help="Path to the input audio file")
    parser.add_argument("output", type=Path, help="Path to the output text file")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="faster-whisper model size: tiny, base, small, medium, large-v3 "
        f"(default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help="Language code, e.g. 'pl' or 'en' (default: auto-detect)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Computation device: auto, cpu, cuda (default: auto)",
    )
    parser.add_argument(
        "--compute-type",
        default="default",
        help="Precision, e.g. int8, float16, float32 (default: default)",
    )
    args = parser.parse_args()

    transcribe(
        args.audio,
        args.output,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
    )


if __name__ == "__main__":
    main()
