"""Web UI for Meeting Scribe (FastAPI).

A small server that lets you browse recorded meetings, read their transcript and
AI summary, ask questions about a meeting, upload a recording for processing, and
tune what gets extracted — all without touching Discord. It runs on port 8000
(the Coolify deployment target).
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Annotated

import markdown as _markdown
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import ai
import store
from process import process_meeting
from settings import ExtractionSettings, Section, load_settings, save_settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Render Markdown summaries/answers to HTML in templates via `{{ text | md }}`.
templates.env.filters["md"] = lambda text: _markdown.markdown(text or "", extensions=["nl2br"])

app = FastAPI(title="Meeting Scribe")

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


def _process_upload(meeting_name: str, media: Path) -> None:
    """Background job: transcribe + summarise, updating the meeting's status.

    Long recordings can take minutes, so this runs after the upload response is
    sent (Starlette runs sync background tasks in a threadpool).
    """
    meeting = store.get_meeting(meeting_name)
    if meeting is None:
        return
    try:
        process_meeting(meeting, media)
        meeting.update(status="done", error="")
    except Exception as exc:  # noqa: BLE001 — record the failure for the UI
        meeting.update(status="error", error=str(exc))
    finally:
        media.unlink(missing_ok=True)


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
    meeting = store.create_meeting(
        title=title or (file.filename or "Upload"), source="upload", status="processing"
    )

    media = meeting.dir / f"source{suffix}"
    with media.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    background_tasks.add_task(_process_upload, meeting.name, media)
    return RedirectResponse(url=f"/meeting/{meeting.name}", status_code=303)


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
