# Roadmap — planned improvements

Ideas we agreed to build. The **quick wins** below are already shipped; the rest
are queued. Rough order within each group is by value/effort.

## ✅ Done
- **In-page audio player** on the meeting page (`/meeting/{name}/audio`).
- **Timestamps in transcripts** (`[m:ss]`), clickable to seek the player.
- **Auto-generated meeting titles** (Claude) when no title is given on upload.
- **Export & copy** — download summary (`.md`) / transcript (`.txt`) + copy buttons.
- **Automatic model fallback** — if the configured Whisper model fails (e.g. OOM),
  retry transcription with `medium`.
- **Two-pass transcription** — fast `small` preview (transcript + summary shown
  immediately), then a background `large-v3` refine that replaces both.
- **Search across meetings** — header search box + `/search`, plus `@bot search`.
- **Threaded Q&A history** — questions/answers persisted per meeting, shown as a
  conversation; follow-ups keep prior context (UI + Discord).
- **Rename meetings** from the UI.
- **Ask across all meetings** — `/ask` (nav "Ask all") + `@bot askall`; Claude
  answers from every meeting's summary with citations.

## 🟡 Next up (bigger, high value)
- **Speaker diarization** — label "who said what" (pyannote / whisperx). Heavier
  dependency and more CPU; biggest quality jump for multi-person meetings.
- **Extraction templates** — presets of summary sections (standup / sales call /
  interview) selectable per meeting, on top of the current tunable settings.
- **Q&A citations** — answers that cite transcript timestamps/quotes.
- **Email the summary** — send the summary to participants via the connected Gmail
  after processing.

## 🔵 Recording ("bot records live") — blocked by Discord DAVE
See [RECORDING.md](RECORDING.md) for the full DAVE situation.
- **Stage-channel recording** — Stage channels are exempt from E2EE; switch the bot
  to record Stage channels (the only ToS-compliant "our bot records" path today).
- **Watch py-cord #3139** — auto-notify when DAVE voice receive is merged/released,
  then just bump the dependency (recording code is already in place).

## ⚙️ Ops / hardening
- **Real background job queue** — replace in-process threads/BackgroundTasks so
  work survives restarts natively and heavy transcription doesn't starve the web
  (also cap Whisper `cpu_threads` so the UI stays responsive under load).
- **Chunked / map-reduce summaries** — for very long meetings that exceed the model
  context window, summarise in chunks then combine.
- **Pagination** on the meetings list once there are many.
- **Rotate secrets** — the Anthropic key, Discord bot token, and Coolify tokens
  were shared in plaintext during setup; rotate them and store only in env/secrets.
- **Meeting management** — rename/edit title, tags/folders, favourites.
