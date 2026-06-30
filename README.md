# Meeting Scribe

Turn meeting recordings into searchable text. Meeting Scribe takes a video
recording, extracts its audio track, and transcribes it to plain text — all
**locally**, with no API key or internet connection required (the speech model
is downloaded once on first use).

```
video (MP4)  ──►  audio (MP3)  ──►  transcript (TXT)
   extract_audio        transcribe
```

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — Python package & environment manager
- **Python 3.10+** (pinned to the version in [.python-version](.python-version))
- **[FFmpeg](https://ffmpeg.org/)** on your `PATH` — required by both audio
  extraction and transcription

Python dependencies (installed automatically by `uv sync`):

- [`moviepy`](https://pypi.org/project/moviepy/) — extract audio from video
- [`faster-whisper`](https://pypi.org/project/faster-whisper/) — local speech-to-text

## Project layout

```
meeting scribe/
├── pyproject.toml          # project + dependencies (uv)
├── uv.lock                 # locked dependency versions
├── .python-version         # pinned Python version
├── main.py                 # full pipeline entry point
├── README.md
├── data/                   # input recordings (contents git-ignored)
│   └── <name>/video.mp4
├── results/                # generated transcripts (contents git-ignored)
│   └── <name>/audio.txt
└── src/
    ├── config.py            # shared paths & defaults
    ├── extract_audio.py     # MP4 -> MP3
    ├── transcribe.py        # MP3 -> TXT
    └── notify.py            # wait-for-file + beep helper
```

Recordings and transcripts live under `data/` and `results/`. Those folders are
kept in git via `.gitkeep`, but their contents are ignored so large media files
never get committed.

## Setup

```bash
# Install FFmpeg first (see https://ffmpeg.org/download.html)

# Create the virtual environment and install dependencies (incl. dev tools)
uv sync

# (optional) Install the git pre-commit hooks
uv run pre-commit install
```

## Usage

### Run the full pipeline

Just hand `main.py` a file — **you don't say whether it's video or audio**. The
script detects the type from the extension and runs the right steps:

- a **video** (`.mp4`, `.mov`, `.mkv`, `.webm`, …) → extract audio → transcribe
- an **audio** file (`.mp3`, `.wav`, `.m4a`, `.flac`, …) → transcribe directly

```bash
# Video: audio is extracted automatically, then transcribed
uv run python main.py data/meeting/video.mp4

# Audio: transcribed directly, no extraction step
uv run python main.py data/meeting/audio.mp3 --language pl
```

By default the outputs go to a **timestamped** folder under `results/`, e.g.
`results/meeting-2026-06-30_14-30-05/<filename>.txt`, so runs never overwrite
each other. Override the folder name or any path:

```bash
# Use a fixed folder name instead of a timestamp
uv run python main.py recording.mp4 --name standup

# Pick the transcript location and a larger model
uv run python main.py recording.mp4 --transcript results/notes.txt --model medium
```

An unknown extension (or a missing file) is reported with a clear error before
any work starts.

### Run a single step

Each function is also a standalone command (defined in `pyproject.toml`):

```bash
# 1. Extract audio from video (MP4 -> MP3)
uv run extract-audio data/meeting/video.mp4 data/meeting/audio.mp3

# 2. Transcribe audio to text (MP3 -> TXT)
uv run transcribe data/meeting/audio.mp3 results/meeting/audio.txt --language pl --model small

# Optional: beep when a long job finishes (waits for the file to appear)
uv run wait-for-file results/meeting/audio.txt
```

You can also invoke the modules directly:

```bash
uv run python -m extract_audio data/meeting/video.mp4 data/meeting/audio.mp3
uv run python -m transcribe data/meeting/audio.mp3 results/meeting/audio.txt
```

## Model sizes

`faster-whisper` supports several model sizes — larger is more accurate but
slower and heavier: `tiny`, `base`, `small` (default), `medium`, `large-v3`.
Choose with `--model`. The model is downloaded and cached on first use.

## Development

Dev tooling (pytest, ruff, pre-commit) is installed by `uv sync`.

```bash
# Run the unit tests (no media files or FFmpeg required — heavy steps are mocked)
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Run all pre-commit hooks against the whole tree
uv run pre-commit run --all-files
```

The test suite lives in [`tests/`](tests/) and covers the run-name generation,
audio extraction, transcription, the notify helper, and the `main.py` path
wiring.
