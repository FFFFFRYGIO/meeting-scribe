"""Meeting Scribe service entry point.

Runs the web UI and (if configured) the Discord bot in a single process — the
shape Coolify deploys. The web server always starts; the Discord bot starts only
when ``DISCORD_BOT_TOKEN`` is set, so the UI works on its own for upload-based
use.

    uv run python app.py          # run the whole service
    uv run python -m web          # (dev) web only, via `uvicorn web:app --reload`

Environment:
    PORT               web server port (default 8000)
    DISCORD_BOT_TOKEN  enables the Discord bot when present
    ANTHROPIC_API_KEY  required for summaries and Q&A
"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from web import app


async def _serve_web() -> None:
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    await uvicorn.Server(config).serve()


async def _serve_bot() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN not set — running web UI only (no Discord bot).")
        return
    # Import lazily so the web-only path doesn't require the voice dependencies.
    from bot import bot

    await bot.start(token)


async def _main() -> None:
    await asyncio.gather(_serve_web(), _serve_bot())


if __name__ == "__main__":
    asyncio.run(_main())
