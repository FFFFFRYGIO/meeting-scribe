"""Web UI for Meeting Scribe (FastAPI).

A small server that lets you browse recorded meetings, read their transcript and
AI summary, ask questions about a meeting, upload a recording for processing, and
tune what gets extracted — all without touching Discord. It runs on port 8000
(the Coolify deployment target).
"""

from __future__ import annotations

import base64
import html
import os
import re
import secrets
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import markdown as _markdown
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import ai
import store
from process import process_meeting, summarize_meeting
from settings import ExtractionSettings, Section, load_settings, save_settings

# Model to retry with when the configured (heavier) one fails to transcribe.
_FALLBACK_MODEL = "medium"

_TS = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s?(.*)$")


def _ts_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.split(":")]
    return (
        parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]
    )


def render_transcript_html(text: str) -> str:
    """Render a transcript to HTML, turning ``[m:ss]`` prefixes into seek links."""
    lines = []
    for line in (text or "").splitlines():
        m = _TS.match(line)
        if m:
            secs = _ts_to_seconds(m.group(1))
            anchor = f'<a href="#" class="ts" data-s="{secs}">[{m.group(1)}]</a>'
            lines.append(f"{anchor} {html.escape(m.group(2))}")
        else:
            lines.append(html.escape(line))
    return "<br>".join(lines)


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Render Markdown summaries/answers to HTML in templates via `{{ text | md }}`.
templates.env.filters["md"] = lambda text: _markdown.markdown(text or "", extensions=["nl2br"])
# Render a transcript with clickable timestamps via `{{ text | ts_transcript }}`.
templates.env.filters["ts_transcript"] = render_transcript_html


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Re-enqueue any meeting left "processing" by a restart (redeploy/crash),
    # so background work self-heals instead of getting stuck forever.
    for meeting in store.list_meetings():
        if meeting.status == "processing":
            threading.Thread(target=_run_pipeline, args=(meeting.name,), daemon=True).start()
    yield


app = FastAPI(title="Meeting Scribe", lifespan=_lifespan)

# Paths reachable without logging in (Coolify's health check hits /healthz).
_PUBLIC_PATHS = {"/healthz"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gate the whole UI behind a single HTTP Basic account.

    Credentials come from AUTH_USERNAME / AUTH_PASSWORD so the password never
    lives in the repo. If AUTH_PASSWORD is unset, auth is disabled (local dev).
    """

    async def dispatch(self, request: Request, call_next):
        user = os.environ.get("AUTH_USERNAME", "")
        password = os.environ.get("AUTH_PASSWORD", "")
        if not password or request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                supplied_user, _, supplied_pw = base64.b64decode(header[6:]).decode().partition(":")
            except Exception:  # noqa: BLE001 — malformed header → treat as unauthorized
                supplied_user = supplied_pw = ""
            # compare_digest on both halves to avoid early-exit timing leaks
            if secrets.compare_digest(supplied_user, user) and secrets.compare_digest(
                supplied_pw, password
            ):
                return await call_next(request)

        return Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Meeting Scribe"'},
        )


app.add_middleware(BasicAuthMiddleware)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"meetings": store.list_meetings()})


@app.get("/meeting/{name}", response_class=HTMLResponse)
def meeting_detail(
    request: Request, name: str, answer: str = "", question: str = ""
) -> HTMLResponse:
    meeting = store.get_meeting(name)
    if meeting is None:
        return HTMLResponse("Meeting not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "meeting.html",
        {
            "meeting": meeting,
            "summary": meeting.summary_text(),
            "transcript": meeting.transcript_text(),
            "answer": answer,
            "question": question,
        },
    )


@app.post("/meeting/{name}/ask", response_class=HTMLResponse)
def meeting_ask(request: Request, name: str, question: Annotated[str, Form()]) -> HTMLResponse:
    meeting = store.get_meeting(name)
    if meeting is None:
        return HTMLResponse("Meeting not found", status_code=404)
    response = ai.answer(question, meeting.transcript_text())
    return templates.TemplateResponse(
        request,
        "meeting.html",
        {
            "meeting": meeting,
            "summary": meeting.summary_text(),
            "transcript": meeting.transcript_text(),
            "answer": response,
            "question": question,
        },
    )


def _locate_media(meeting: store.Meeting) -> Path | None:
    """Best source to (re)process from: the extracted audio, else the raw upload."""
    if meeting.audio_path.exists():
        return meeting.audio_path
    for src in sorted(meeting.dir.glob("source.*")):
        return src
    return None


def _run_pipeline(meeting_name: str, force: bool = False) -> None:
    """Background job: transcribe (if needed) + summarise, updating the status.

    ``force=True`` (manual Reprocess) re-transcribes from the stored audio so a
    new model/language takes effect. ``force=False`` (upload, restart recovery)
    resumes: if a transcript already exists it only (re)summarises. Long
    recordings can take minutes, so this runs off the request path.
    """
    meeting = store.get_meeting(meeting_name)
    if meeting is None:
        return

    last_pct = [-1]

    def on_progress(fraction: float) -> None:
        pct = min(100, int(fraction * 100))
        if pct != last_pct[0]:  # only persist when the integer percent changes
            last_pct[0] = pct
            meeting.update(progress=pct)

    try:
        meeting.update(progress=0)
        media = _locate_media(meeting)
        if force and media is not None:
            _process_with_fallback(meeting, media, on_progress)  # redo transcription
        elif meeting.transcript_text().strip():
            meeting.update(progress=100)  # transcription already complete → summary stage
            summarize_meeting(meeting)
        elif media is not None:
            _process_with_fallback(meeting, media, on_progress)
        else:
            meeting.update(status="error", error="Source file is missing — please re-upload.")
            return
        _autotitle(meeting)
        meeting.update(status="done", error="", progress=100)
    except Exception as exc:  # noqa: BLE001 — record the failure for the UI
        meeting.update(status="error", error=str(exc))
    finally:
        # Once we have the audio + transcript, drop the raw upload to save space.
        if meeting.audio_path.exists() and meeting.transcript_text().strip():
            for src in meeting.dir.glob("source.*"):
                src.unlink(missing_ok=True)


def _process_with_fallback(meeting: store.Meeting, media: Path, on_progress) -> None:
    """Transcribe + summarise; if the configured model fails, retry with a lighter one."""
    settings = load_settings()
    try:
        process_meeting(meeting, media, settings=settings, progress_callback=on_progress)
    except Exception as exc:  # noqa: BLE001
        if settings.whisper_model == _FALLBACK_MODEL:
            raise
        print(
            f"Transcription with '{settings.whisper_model}' failed ({exc}); "
            f"retrying with '{_FALLBACK_MODEL}'."
        )
        meeting.update(progress=0)
        process_meeting(
            meeting,
            media,
            settings=replace(settings, whisper_model=_FALLBACK_MODEL),
            progress_callback=on_progress,
        )


def _autotitle(meeting: store.Meeting) -> None:
    """Give the meeting an AI-generated title when it doesn't have one yet."""
    if meeting.title.strip():
        return
    try:
        generated = ai.title(meeting.transcript_text())
        if generated:
            meeting.update(title=generated)
    except Exception as exc:  # noqa: BLE001 — a title failure must not fail processing
        print(f"Auto-title failed: {exc}")


@app.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Accept a recording and return immediately; process it in the background.

    The file is streamed to the meeting folder, the meeting is marked
    ``processing``, and transcription/summarisation run after the response so the
    page never blocks on long recordings.
    """
    suffix = Path(file.filename or "upload").suffix or ".mp3"
    # Leave the title empty when not given so the pipeline auto-generates one.
    meeting = store.create_meeting(title=title.strip(), source="upload", status="processing")

    media = meeting.dir / f"source{suffix}"
    with media.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    background_tasks.add_task(_run_pipeline, meeting.name)
    return RedirectResponse(url=f"/meeting/{meeting.name}", status_code=303)


@app.post("/meeting/{name}/reprocess")
def meeting_reprocess(name: str, background_tasks: BackgroundTasks) -> RedirectResponse:
    """Re-run transcription/summary for a stuck or failed meeting."""
    meeting = store.get_meeting(name)
    if meeting is None:
        return RedirectResponse(url="/", status_code=303)
    meeting.update(status="processing", error="")
    background_tasks.add_task(_run_pipeline, meeting.name, True)  # force re-transcription
    return RedirectResponse(url=f"/meeting/{meeting.name}", status_code=303)


@app.get("/meeting/{name}/audio")
def meeting_audio(name: str) -> Response:
    """Serve the meeting's audio for the in-page player."""
    meeting = store.get_meeting(name)
    if meeting is None or not meeting.has_audio:
        return Response("Not found", status_code=404)
    return FileResponse(meeting.audio_path, media_type="audio/mpeg")


@app.get("/meeting/{name}/download/{kind}")
def meeting_download(name: str, kind: str) -> Response:
    """Download the transcript (.txt) or summary (.md)."""
    meeting = store.get_meeting(name)
    if meeting is None:
        return Response("Not found", status_code=404)
    if kind == "summary" and meeting.has_summary:
        return FileResponse(
            meeting.summary_path, media_type="text/markdown", filename=f"{meeting.name}-summary.md"
        )
    if kind == "transcript" and meeting.has_transcript:
        return FileResponse(
            meeting.transcript_path,
            media_type="text/plain",
            filename=f"{meeting.name}-transcript.txt",
        )
    return Response("Not found", status_code=404)


@app.post("/meeting/{name}/delete")
def meeting_delete(name: str) -> RedirectResponse:
    """Delete a meeting (folder + audio + transcript + summary) and go home."""
    store.delete_meeting(name)
    return RedirectResponse(url="/", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings.html", {"settings": load_settings(), "saved": saved}
    )


@app.post("/settings")
async def settings_save(request: Request) -> RedirectResponse:
    """Persist edited settings, including the variable-length section list."""
    form = await request.form()
    titles = form.getlist("section_title")
    instructions = form.getlist("section_instructions")
    sections = [
        Section(title=t.strip(), instructions=i.strip())
        for t, i in zip(titles, instructions, strict=False)
        if t.strip()
    ]
    defaults = ExtractionSettings()
    settings = ExtractionSettings(
        claude_model=str(form.get("claude_model", "")).strip() or defaults.claude_model,
        whisper_model=str(form.get("whisper_model", "")).strip() or defaults.whisper_model,
        language=(str(form.get("language", "")).strip() or None),
        summary_system=str(form.get("summary_system", "")).strip(),
        summary_instructions=str(form.get("summary_instructions", "")).strip(),
        sections=sections or ExtractionSettings().sections,
        qa_system=str(form.get("qa_system", "")).strip(),
    )
    save_settings(settings)
    return RedirectResponse(url="/settings?saved=1", status_code=303)
