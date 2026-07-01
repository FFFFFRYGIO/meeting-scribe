"""Join a Google Meet call in a headless browser and record its audio.

Google Meet has no simple bot/recording API, so — like commercial meeting bots —
we drive a real Chromium via Playwright: it opens the Meet link as a guest, mutes
mic/camera, asks to join, and once admitted we capture the browser's audio output
with ffmpeg from a PulseAudio virtual sink. The resulting audio file is then fed
into the normal transcribe → summarise pipeline.

Requirements (provided by the Docker image / entrypoint):
  * Chromium + Playwright browsers (`playwright install chromium`)
  * A running X server (Xvfb) — Meet audio needs a headful browser
  * PulseAudio with a null sink whose monitor we record (env MEET_AUDIO_DEVICE)
  * ffmpeg on PATH

This is best-effort automation: Meet's UI changes and a host must admit the bot.
On trouble it writes screenshots + a log to *artifacts_dir* to help tune selectors.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

# Pulse monitor source ffmpeg records (the null sink's monitor).
AUDIO_DEVICE = os.environ.get("MEET_AUDIO_DEVICE", "meet.monitor")

StatusFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def _start_ffmpeg(out_audio: Path) -> subprocess.Popen:
    """Start ffmpeg capturing the Pulse monitor into *out_audio* (mp3)."""
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "pulse",
        "-i",
        AUDIO_DEVICE,
        "-ac",
        "2",
        "-ar",
        "44100",
        "-b:a",
        "192k",
        str(out_audio),
    ]
    return subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _stop_ffmpeg(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.communicate(input=b"q", timeout=10)  # ffmpeg quits cleanly on 'q'
    except Exception:  # noqa: BLE001
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()


def _click_first(page, names: list[str], timeout: int = 4000) -> bool:
    """Click the first button matching any of *names* (regex, case-insensitive)."""
    for name in names:
        try:
            btn = page.get_by_role("button", name=re.compile(name, re.I)).first
            btn.wait_for(state="visible", timeout=timeout)
            btn.click()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _prejoin(page, bot_name: str, status: StatusFn) -> None:
    """Fill the guest name, mute mic/camera, and ask to join."""
    status("Opening the meeting…")
    # Dismiss any "continue without signing in" / cookie dialogs.
    _click_first(
        page, ["Continue without", "Got it", "Dismiss", "I agree", "Accept all"], timeout=3000
    )

    # Guest name field.
    for selector in ('input[placeholder*="name" i]', 'input[aria-label*="name" i]'):
        try:
            page.fill(selector, bot_name, timeout=3000)
            break
        except Exception:  # noqa: BLE001
            continue

    # Turn mic and camera off if they're on (labels toggle between on/off).
    _click_first(page, ["Turn off microphone"], timeout=2000)
    _click_first(page, ["Turn off camera"], timeout=2000)

    status("Asking to join…")
    if not _click_first(page, ["Ask to join", "Join now", "Join"], timeout=8000):
        raise RuntimeError("Could not find the join button on the Meet page")


def _wait_admitted(page, timeout_s: int) -> None:
    """Wait until we're in the call (the in-call toolbar appears)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for name in [
            "Leave call",
            "Turn off microphone",
            "Turn on microphone",
            "Chat with everyone",
        ]:
            try:
                if page.get_by_role("button", name=re.compile(name, re.I)).first.is_visible():
                    return
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)
    raise RuntimeError("Timed out waiting to be admitted to the meeting")


def _still_in_call(page) -> bool:
    try:
        return page.get_by_role("button", name=re.compile("Leave call", re.I)).first.is_visible()
    except Exception:  # noqa: BLE001
        return False


def record_meet(
    meeting_url: str,
    out_audio: Path,
    *,
    bot_name: str = "Meeting Scribe",
    max_seconds: int = 7200,
    admit_timeout_s: int = 300,
    stop_event=None,
    on_status: StatusFn | None = None,
    artifacts_dir: Path | None = None,
) -> Path:
    """Join *meeting_url*, record the call's audio to *out_audio*, and return it.

    Stops when *stop_event* is set, when the call ends, or after *max_seconds*.
    """
    from playwright.sync_api import sync_playwright  # imported lazily (heavy dep)

    status = on_status or _noop
    out_audio = Path(out_audio)
    proc = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,  # audio needs a headful browser (under Xvfb)
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        # Deny mic/cam so Meet joins listen-only and never prompts.
        context = browser.new_context(permissions=[])
        page = context.new_page()
        try:
            page.goto(meeting_url, wait_until="load", timeout=60000)
            _prejoin(page, bot_name, status)
            status("Waiting to be admitted…")
            _wait_admitted(page, admit_timeout_s)

            status("Recording…")
            proc = _start_ffmpeg(out_audio)
            deadline = time.monotonic() + max_seconds
            while time.monotonic() < deadline:
                if stop_event is not None and stop_event.is_set():
                    break
                if not _still_in_call(page):
                    break
                time.sleep(3)
        except Exception:
            if artifacts_dir is not None:
                _dump_debug(page, artifacts_dir)
            raise
        finally:
            _stop_ffmpeg(proc)
            _click_first(page, ["Leave call"], timeout=3000)
            context.close()
            browser.close()

    if not out_audio.exists() or out_audio.stat().st_size == 0:
        raise RuntimeError("No audio was captured from the meeting")
    status("Left the meeting.")
    return out_audio


def _dump_debug(page, artifacts_dir: Path) -> None:
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(artifacts_dir / "meet-debug.png"), full_page=True)
        (artifacts_dir / "meet-debug.html").write_text(page.content(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
