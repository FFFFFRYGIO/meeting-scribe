# Recording Google Meet calls

Meeting Scribe can send a bot into a Google Meet call, record it, and then run the
usual transcribe → summarise → Q&A pipeline — the thing the Discord bot was meant
to do, but for Meet.

## How it works

Google Meet has no simple API for a bot to join and record, so (like Recall.ai and
similar products) we drive a real browser:

1. A headful **Chromium** (Playwright) opens the Meet link as a guest.
2. It sets the bot's display name, mutes mic/camera, and clicks **Ask to join**.
3. A **host must admit** the bot.
4. Once in, **ffmpeg** records the browser's audio from a **PulseAudio** null sink.
5. On stop / call end / time limit, the audio is transcribed and summarised like any
   other recording.

The Docker image ships everything needed: Chromium, Xvfb (virtual display — Meet
audio needs a headful browser), PulseAudio, and ffmpeg. `docker-entrypoint.sh`
starts the audio sink and display before the app.

## Using it

1. In the web UI, open **Record Meet**.
2. Paste the Meet link, pick a project, set the bot name and a max duration.
3. **Join & record.** The meeting page shows the live stage (joining → recording).
4. In Google Meet, **admit the bot** when it knocks.
5. Click **Stop & process** on the meeting page when the call is over (or it stops
   at the time limit / when the call ends), then the transcript + summary appear.

## Caveats & tuning

- **Best-effort.** Google Meet's UI changes and can detect automation; the join
  flow (selectors in `src/meet_bot.py`) may need occasional tuning. On failure the
  bot saves `meet-debug.png` + `meet-debug.html` into the meeting folder to help.
- **A host must admit the bot** — guest join isn't automatic.
- **Terms of service.** Automating a browser into Google Meet is a grey area under
  Google's terms; use it on meetings you're entitled to record, and get consent.
- **Resources.** Chromium + Xvfb + PulseAudio plus `large-v3` transcription is
  heavy — give the server enough CPU/RAM, or use a smaller Whisper model in Settings.
- **Audio stack.** If no audio is captured, check the container's PulseAudio null
  sink (`MEET_AUDIO_DEVICE`, default `meet.monitor`) and that `docker-entrypoint.sh`
  started PulseAudio and Xvfb.

## Config

- `MEET_BOT_NAME`, `MEET_MAX_MINUTES` in `src/config.py`.
- `MEET_AUDIO_DEVICE` env — the Pulse monitor ffmpeg records.
