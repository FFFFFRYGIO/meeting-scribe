# Meeting Scribe — web UI + Discord bot in one image.
# Matches .python-version so `uv sync --frozen` resolves against the lockfile.
FROM python:3.14-slim

# FFmpeg is required by audio extraction, transcription, and pydub mixing.
# libopus/libsodium back py-cord's voice receive.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libopus0 \
        libsodium23 \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, locked dependency installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies + the project (editable). The editable install is what
# maps src/ modules to importable names at runtime (hatch sources=["src"]).
# README.md is required because pyproject references it as the package readme.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY main.py app.py ./
RUN uv sync --frozen --no-dev

# Persisted at runtime: settings, recordings, transcripts, summaries.
# Mount a volume here in Coolify so data survives redeploys.
RUN mkdir -p data results
VOLUME ["/app/data", "/app/results"]

# Whisper model cache — on the persisted /app/data volume so the (large) model
# is downloaded only once and survives redeploys.
ENV HF_HOME=/app/data/hf-cache

EXPOSE 8000

# Runs the web UI; starts the Discord bot too when DISCORD_BOT_TOKEN is set.
CMD ["uv", "run", "--no-dev", "python", "app.py"]
