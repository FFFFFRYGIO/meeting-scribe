# Laptop recorder (Google Meet, Zoom, anything)

Instead of running a fragile, resource-heavy browser bot on the server, recording
happens on the **laptop of whoever is in the call**, right in their browser. The
server just receives the finished audio and runs the usual transcribe → summarise
→ Q&A pipeline. No Chromium/Xvfb/PulseAudio on the server.

## How to use it

1. On the computer that's in the meeting, open **Recorder** in the web UI
   (`/recorder`) — desktop **Chrome** or **Edge**.
2. (Optional) set a title and project; choose whether to include your microphone.
3. Click **Start recording**. In the browser's share dialog, pick the **meeting
   tab** (or the whole screen) and **enable “Share tab audio”** — without that,
   other participants aren't captured.
4. When the call ends, click **Stop & upload**. The recording uploads to the
   server and you're taken to the meeting page, which shows processing and then the
   transcript + summary.

## How it works

- The page uses `getDisplayMedia({audio:true})` to capture the shared tab/system
  audio and `getUserMedia` for the mic, mixes them with the Web Audio API, and
  records with `MediaRecorder` (audio/webm).
- On stop it POSTs the blob to `POST /api/upload` (multipart: `file`, `title`,
  `project`). The server converts it to mp3 (pydub/ffmpeg) and runs the pipeline.

## Notes

- **Tab audio capture needs desktop Chrome/Edge.** Firefox/Safari support is
  limited; Safari can't capture tab audio.
- Keep the recorder tab open while recording. If you stop the browser share, the
  recording stops and uploads automatically.
- Everyone in the call should consent to being recorded.
- `POST /api/upload` is behind the same login as the rest of the UI; the browser
  sends the session's credentials automatically.

## Programmatic upload

Any client can post a recording:

```bash
curl -u Orka:PASS -F file=@call.mp3 -F title="Sync" -F project=DroneScanner \
  https://<host>/api/upload
# → {"name": "...", "url": "/meeting/..."}
```
