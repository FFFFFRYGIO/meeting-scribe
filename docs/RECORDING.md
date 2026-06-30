# Recording Discord meetings & the DAVE limitation

## What changed

In **March 2026** Discord enforced **DAVE** — end-to-end encryption for voice and
video — on all non-Stage voice calls. Bots can still *connect* and *play* audio,
but **receiving (recording) audio requires implementing DAVE**, and the Python
libraries don't yet:

- **py-cord** — voice reception is being reworked for DAVE; tracked in
  [issue #3139](https://github.com/Pycord-Development/pycord/issues/3139) (in
  progress). Calling `start_recording` currently fails.
- **discord.py** — no DAVE support yet
  ([issue #9948](https://github.com/Rapptz/discord.py/issues/9948)).

So Meeting Scribe's `@bot` record command currently replies that recording is
unavailable instead of crashing. The code path is kept and will start working
unchanged once py-cord ships DAVE receive.

## Ways to record today

Ranked by practicality. All of them feed the same pipeline — once you have an
audio/video file, upload it in the web UI and you get the transcript, summary,
and Q&A.

1. **Record with another tool, then upload.** Any recorder works (OS audio
   capture, OBS, a phone). **[Craig](https://craig.chat/)** is a Discord bot that
   already implements DAVE and records each speaker to a separate track — record
   with Craig, download the audio, upload it here. Zero changes needed on our side.

2. **Use a Stage channel.** Discord's E2EE enforcement is for
   [*non-Stage* voice calls](https://support.discord.com/hc/en-us/articles/38749827197591-A-V-E2EE-Enforcement-for-Non-Stage-Voice-Calls)
   — **Stage channels are not E2EE**. A bot can receive audio in a Stage without
   DAVE. This is a possible path to "our bot records" once we confirm a py-cord
   version with a working (non-DAVE) receive in Stage channels. Not enabled yet.

3. **Wait for py-cord DAVE support** ([#3139](https://github.com/Pycord-Development/pycord/issues/3139)).
   When it lands, bump the dependency and live recording works with no code change.

## Not supported

Automating a **user account** (self-bot) to capture decrypted audio violates
Discord's Terms of Service and is intentionally not implemented.
