#!/usr/bin/env bash
# Start the audio + display stack the Google Meet bot needs, then run the app.
# Failures here are non-fatal: the web UI, uploads, and Discord Q&A work without
# them; only live Meet recording needs the browser/audio stack.
set -u

# --- PulseAudio: a null sink whose monitor we record for Meet audio ----------
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/pulse-runtime}"
mkdir -p "$XDG_RUNTIME_DIR"
# In containers we run as root; --system lets PulseAudio start anyway.
pulseaudio --system --daemonize --exit-idle-time=-1 --disallow-exit >/dev/null 2>&1 || \
  pulseaudio --daemonize --exit-idle-time=-1 >/dev/null 2>&1 || true
sleep 1
pactl load-module module-null-sink sink_name=meet sink_properties=device.description=meet >/dev/null 2>&1 || true
pactl set-default-sink meet >/dev/null 2>&1 || true

# --- Virtual display for the headful Chromium the Meet bot drives -------------
rm -f /tmp/.X99-lock >/dev/null 2>&1 || true
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 &
export DISPLAY=:99

exec uv run --no-dev python app.py
