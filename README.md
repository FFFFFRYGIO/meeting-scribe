# Meeting Scribe

Turn meetings into searchable, summarised, queryable notes. A Discord bot joins
your voice channel, records the call, and once it's over **transcribes it,
posts an AI summary back to the channel**, and lets anyone ask questions about
it — in Discord or from a small web UI.

```
Discord voice ──► record ──► mix ──► transcribe ──► summary  ──► posted to channel + web UI
   (bot joins)    (py-cord)  (pydub)  (faster-whisper)  (Claude)        ▲
                                                                        └── ask questions anytime
```

Design principle: **as little AI as possible**. Recording, mixing,
transcription, storage, and meeting lookup are all deterministic and local.
Claude is used only for two things — writing the **summary** and answering
**questions** — and exactly *what* it extracts is configurable from the UI
without touching code.

## Features

- 🎥 **Laptop recorder** — a zero-install browser page (`/recorder`) run on the
  laptop that's in the call captures the meeting tab audio + mic and uploads it to
  the server, which transcribes & summarises it. Works for Google Meet, Zoom, etc.
  See [docs/RECORDER.md](docs/RECORDER.md).
- 🎙️ **Discord recording** — mention the bot to make it join your voice channel
  and record; mention `stop` to finish. *(Currently blocked upstream by Discord's
  DAVE encryption — see [docs/RECORDING.md](docs/RECORDING.md).)*
- 📝 **Automatic summaries** — after a meeting, the bot posts a structured
  summary to the channel and saves it.
- ❓ **Q&A** — ask about any meeting from Discord (`@bot question <date> ...`) or
  the web UI; answers are grounded strictly in the transcript.
- 🎛️ **Tunable extraction** — edit the summary sections, instructions, model, and
  language from the **Settings** page. Add a "Risks" section, change the tone,
  switch language — the next summary follows.
- ⬆️ **Upload** — drop a video/audio file into the web UI; it's processed in the
  **background** so the page never blocks on long recordings (the meeting shows a
  live "processing" status and refreshes when ready).
- 🌐 **Web UI** — browse meetings, read transcripts and summaries, ask questions,
  and **delete** meetings you no longer need.
- 🔒 **Local transcription** — speech-to-text runs locally via `faster-whisper`
  (no API key, model downloaded once). Defaults to the most accurate **`large-v3`**
  model with **int8** compute (light/fast on CPU); change the size or set a fixed
  language in **Settings**. Only summary/Q&A call out to Claude.

## Architecture

| Piece | File | Role |
|---|---|---|
| Web UI | `src/web.py` + `src/templates/` | FastAPI app: meetings list, detail, ask, upload, settings |
| Discord bot | `src/bot.py` | py-cord voice recording + mention commands |
| Service runner | `app.py` | Runs the web server and (if configured) the bot in one process |
| Meeting store | `src/store.py` | Filesystem store — one folder per meeting under `results/` |
| AI | `src/ai.py` | Claude summary + Q&A (the only LLM calls) |
| Settings | `src/settings.py` | Editable extraction config, persisted to `data/settings.json` |
| Pipeline | `src/process.py` | transcribe → summarise, shared by upload and the bot |
| Steps | `src/extract_audio.py`, `src/transcribe.py` | the original MP4→MP3 and MP3→TXT building blocks |

Each meeting lives in `results/<name>/` with `metadata.json`, `audio.mp3`,
`transcript.txt`, and `summary.md`.

## Requirements

- **[uv](https://docs.astral.sh/uv/)** and **Python 3.13+**
- **[FFmpeg](https://ffmpeg.org/)** on `PATH` (audio extraction, transcription, mixing)
- **`ANTHROPIC_API_KEY`** — for summaries and Q&A ([get one](https://console.anthropic.com/))
- **`DISCORD_BOT_TOKEN`** — only if you want the Discord bot ([setup guide](docs/DISCORD_SETUP.md))

## Setup

```bash
uv sync
cp .env.example .env   # then fill in ANTHROPIC_API_KEY (+ DISCORD_BOT_TOKEN)
```

## Running

Run the whole service (web UI + Discord bot if the token is set):

```bash
set -a; source .env; set +a   # load env vars
uv run python app.py          # http://localhost:8000
```

Web UI only, with auto-reload during development:

```bash
uv run uvicorn web:app --reload
```

The Discord bot starts automatically when `DISCORD_BOT_TOKEN` is present; without
it, only the web UI runs.

### Discord commands

Mention the bot, then a command:

| You type | What happens |
|---|---|
| `@Scribe help` | Shows the command list |
| `@Scribe list` | Lists recent meetings with their **ids** |
| `@Scribe question <your question>` | Answers from the **most recent** meeting |
| `@Scribe question <id-or-date> <your question>` | Answers from a **specific** meeting |
| `@Scribe` | Joins your voice channel and records *(see note below)* |
| `@Scribe stop` | Stops → transcribes → summarises → posts the summary |

**Examples:**

```text
@Scribe question what were the action items?
@Scribe question 2026-06-30 who owns the docs?
@Scribe question standup-2026-06-30_14-30-05 what did Alice commit to?
@Scribe list
```

**Choosing between two meetings on the same day.** Every meeting has a unique
**id** (it includes the time, e.g. `standup-2026-06-30_14-30-05`). A bare date
like `2026-06-30` can match several meetings — if it does, the bot replies with
the matching ids so you can repeat the question using the exact one. Run
`@Scribe list` (or open the web UI) to see ids.

> ⚠️ **Live recording note:** Discord enforced end-to-end encryption (DAVE) on
> voice in March 2026, and audio reception isn't supported by the bot library yet
> ([py-cord #3139](https://github.com/Pycord-Development/pycord/issues/3139)). Until
> that ships, `@Scribe` (record) replies that recording is unavailable — record
> with another tool and **upload the file in the web UI**, then use summaries and
> Q&A as normal. See [docs/RECORDING.md](docs/RECORDING.md).

See [docs/DISCORD_SETUP.md](docs/DISCORD_SETUP.md) to create the bot and invite it.

### Tuning what gets extracted

Open **Settings** in the web UI. The summary is built from a list of **sections**
(heading + instructions). Edit them, reorder, add new ones (e.g. "Risks",
"Sentiment"), or change the model/language. Clear a section's title to delete it.
Changes apply to the next summary and are saved to `data/settings.json`.

## Deployment (Coolify)

The repo ships a `Dockerfile` (FFmpeg + voice libs included) and a
`docker-compose.yml`.

1. In Coolify, create a service from this Git repo (Dockerfile or Compose build).
2. Set environment variables: `ANTHROPIC_API_KEY`, optional `DISCORD_BOT_TOKEN`,
   `PORT=8000`.
3. Add **persistent volumes** for `/app/data` (settings) and `/app/results`
   (recordings/transcripts/summaries) so data survives redeploys. The compose
   file already declares them.
4. Expose port **8000**. Health check: `GET /healthz`.

Build and run locally with Docker:

```bash
docker compose up --build
```

> ⚠️ Treat tokens as secrets — set them in Coolify's env/secrets, never commit
> them. If a token has been shared in plaintext, rotate it.

## The original CLI (still here)

The standalone file pipeline remains available for one-off conversions:

```bash
uv run python main.py data/meeting/video.mp4          # video → audio → transcript
uv run python main.py data/meeting/audio.mp3 --language pl
uv run extract-audio in.mp4 out.mp3                    # single step
uv run transcribe out.mp3 out.txt --model small        # single step
```

## Development

```bash
uv run pytest                 # tests (AI, Discord, and FFmpeg are mocked)
uv run pytest tests/test_web.py::test_upload_processes_and_redirects   # one test
uv run ruff check . && uv run ruff format .
uv run pre-commit run --all-files
```

Tests cover settings, the meeting store, the AI prompt assembly (Claude mocked),
the web routes, and the original CLI wiring — all without media files, FFmpeg, a
Discord token, or an API key.
