"""Web UI for Meeting Scribe (FastAPI).

A small server that lets you browse recorded meetings, read their transcript and
AI summary, ask questions about a meeting, upload a recording for processing, and
tune what gets extracted — all without touching Discord. It runs on port 8000
(the Coolify deployment target).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import markdown as _markdown
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import ai
import store
from process import process_meeting
from settings import ExtractionSettings, Section, load_settings, save_settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Render Markdown summaries/answers to HTML in templates via `{{ text | md }}`.
templates.env.filters["md"] = lambda text: _markdown.markdown(text or "", extensions=["nl2br"])

app = FastAPI(title="Meeting Scribe")


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


@app.post("/upload")
async def upload(
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Accept a recording, process it (transcribe + summarise), store as a meeting."""
    suffix = Path(file.filename or "upload").suffix or ".mp3"
    meeting = store.create_meeting(title=title or (file.filename or "Upload"), source="upload")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        process_meeting(meeting, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(url=f"/meeting/{meeting.name}", status_code=303)


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
