"""Extract the audio track from a video file (MP4 -> MP3).

Used as a library::

    from extract_audio import extract_audio
    extract_audio("data/meeting/video.mp4", "data/meeting/audio.mp3")

Used from the command line::

    uv run extract-audio data/meeting/video.mp4 data/meeting/audio.mp3
"""

from __future__ import annotations

import argparse
from pathlib import Path

from moviepy import VideoFileClip

from config import ensure_parent


def extract_audio(
    video_path: str | Path,
    audio_path: str | Path,
    *,
    codec: str = "mp3",
    bitrate: str = "192k",
) -> Path:
    """Write the audio track of *video_path* to *audio_path*.

    Returns the path of the created audio file.
    """
    video_path = Path(video_path)
    audio_path = ensure_parent(Path(audio_path))

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    print(f"Extracting audio from {video_path} ...")
    video = VideoFileClip(str(video_path))
    try:
        if video.audio is None:
            raise ValueError(f"No audio track found in {video_path}")
        video.audio.write_audiofile(str(audio_path), codec=codec, bitrate=bitrate)
    finally:
        video.close()

    print(f"Saved audio: {audio_path}")
    return audio_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the audio track from a video file (MP4 -> MP3).",
    )
    parser.add_argument("video", type=Path, help="Path to the input video file")
    parser.add_argument("audio", type=Path, help="Path to the output audio file")
    parser.add_argument("--bitrate", default="192k", help="Output bitrate (default: 192k)")
    parser.add_argument("--codec", default="mp3", help="Audio codec (default: mp3)")
    args = parser.parse_args()

    extract_audio(args.video, args.audio, codec=args.codec, bitrate=args.bitrate)


if __name__ == "__main__":
    main()
