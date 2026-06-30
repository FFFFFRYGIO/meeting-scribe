# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Meeting Scribe turns meetings into transcripts, AI summaries, and a Q&A surface.
A **Discord bot** joins a voice channel, records it, then transcribes → summarises
→ posts the summary back to the channel; a **FastAPI web UI** lets you browse
meetings, upload recordings, ask questions, and tune extraction. Speech-to-text
(`faster-whisper`) and audio (`moviepy`/`pydub`) run **locally**; **Claude**
(`claude-opus-4-8`) is used only for summaries and Q&A. **FFmpeg must be on
`PATH`** — extraction, transcription, and mixing all shell out to it.

Design rule when extending: keep it deterministic. Recording, mixing,
transcription, storage, and lookup are non-AI by design — only `src/ai.py` calls
an LLM. Don't reach for the model where plain code will do.

## Commands

```bash
uv sync                                   # install deps (incl. dev tools)
set -a; source .env; set +a               # load ANTHROPIC_API_KEY / DISCORD_BOT_TOKEN
uv run python app.py                      # full service: web UI (:8000) + Discord bot (if token set)
uv run uvicorn web:app --reload           # web UI only, with reload (dev)
uv run python main.py <file>              # original standalone CLI pipeline

uv run pytest                             # all tests (AI, Discord, FFmpeg all mocked — no key/media needed)
uv run pytest tests/test_web.py::test_ask_uses_ai_answer   # a single test
uv run ruff check . && uv run ruff format .
docker compose up --build                 # run the container locally (FFmpeg baked in)
```

## Architecture

Flat, single-purpose modules under `src/`, imported by bare name (`import store`,
`from ai import summarize`) — no package prefix (see Module resolution below).

- `config.py` — paths (`PROJECT_ROOT`, `DATA_DIR`, `RESULTS_DIR`), defaults, media
  classification, `ensure_parent`. The original building block; still used everywhere.
- `settings.py` — `ExtractionSettings` (model, whisper size, language, prompts, and
  a list of `Section`s). **This is the "tuning" surface**: the summary is composed
  from `sections`, so editing them changes what gets extracted. Persisted to
  `data/settings.json`; the web Settings page reads/writes it.
- `store.py` — filesystem meeting store. A meeting is a folder under `results/<name>/`
  with `metadata.json`, `audio.mp3`, `transcript.txt`, `summary.md`. `find_meeting()`
  does the fuzzy date/name lookup the bot uses for `question <date>`.
- `ai.py` — the **only** LLM caller. `summarize()` / `answer()` stream from Claude;
  the transcript is sent as a separate `cache_control` block so repeated Q&A on a
  meeting hits the prompt cache. Uses `claude-opus-4-8` from settings.
- `process.py` — `transcribe → summarise` pipeline shared by the web upload and the
  bot. Routes video vs audio via `classify_media`.
- `extract_audio.py` / `transcribe.py` / `notify.py` — original step functions, each
  also a CLI (`[project.scripts]`).
- `web.py` + `templates/` — FastAPI UI: list, detail, `/meeting/{name}/ask`, `/upload`,
  `/settings`, `/healthz`. Markdown rendered via a Jinja `md` filter.
- `bot.py` — py-cord bot. `on_message` reacts to @mentions: bare mention → join +
  record (`WaveSink`); `stop` → `stop_recording()` fires `_on_recording_finished`,
  which mixes per-speaker tracks (`pydub.overlay`), transcribes, summarises, and posts.
  Blocking work (mixing/transcribe/Claude) runs via `asyncio.to_thread`.
- `app.py` (repo root) — runs `uvicorn` and `bot.start()` concurrently via
  `asyncio.gather`; the bot starts only when `DISCORD_BOT_TOKEN` is set.

Data flow: a meeting (Discord or upload) → `store.create_meeting()` → audio +
`transcribe()` → `transcript.txt` → `ai.summarize()` → `summary.md`. Q&A reads
`transcript.txt` and calls `ai.answer()`.

## Module resolution (important)

`src/` is not an importable package path by default. Keep these three in sync if
files move:
- `[tool.pytest.ini_options] pythonpath = ["src", "."]` — tests
- `[tool.pyright] extraPaths = ["src", "."]` — type checkers
- `[tool.hatch.build.targets.wheel] sources = ["src"]` + `force-include` (`main.py`,
  `app.py`) + `artifacts` (`src/templates/**`) — packaging
- The Docker image runs `app.py` directly and relies on `pythonpath`/uv, not the wheel.

## Conventions & gotchas

- `from __future__ import annotations`; `str | Path` inputs coerced to `Path`.
- Secrets come from env only (`ANTHROPIC_API_KEY`, `DISCORD_BOT_TOKEN`) — never commit them.
- `data/` and `results/` contents are gitignored (kept via `.gitkeep`); `data/settings.json`
  is runtime config with a default fallback, so its absence is fine.
- Tests isolate the store by monkeypatching `store.RESULTS_DIR` and settings via the
  `path=` arg / `SETTINGS_FILE`; they mock `ai`, the Discord client, and the pipeline —
  so they need no FFmpeg, token, media, or API key.
- `pydub` needs the stdlib `audioop`, removed in Python 3.13+ — the `audioop-lts`
  dependency backports it (marker-gated).
- Claude usage follows the current SDK: `claude-opus-4-8`, streaming + `get_final_message()`
  for long transcripts. Don't reintroduce `budget_tokens`/sampling params (they 400 on this model).
- Ruff: line length 100, rules `E,F,I,UP,B`.
