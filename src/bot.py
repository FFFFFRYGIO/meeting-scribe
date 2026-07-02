"""Discord bot that records voice meetings and answers questions about them.

Usage in Discord (mention the bot):

    @Scribe                      → joins your current voice channel and records
    @Scribe stop                 → stops, transcribes, summarises, posts the summary
    @Scribe question <text>      → answers using the most recent meeting
    @Scribe question <date> <text>
                                 → answers using the meeting matching <date>/name

Only the summary and Q&A use Claude; joining, recording, mixing, transcription,
storage, and meeting lookup are all deterministic.

Recording uses py-cord voice sinks: each speaker is captured to a separate WAV
track, which we mix down to a single audio file before transcribing. Requires
``DISCORD_BOT_TOKEN`` (and ``ANTHROPIC_API_KEY`` for the AI steps).
"""

from __future__ import annotations

import asyncio
import io
import os
import traceback

import discord
from discord.sinks import WaveSink
from pydub import AudioSegment

import ai
import store
from process import should_summarize, summarize_meeting
from settings import load_settings
from transcribe import transcribe

# guild_id -> active recording context
_active: dict[int, dict] = {}

# Shown when live recording can't start (Discord DAVE E2EE — see _start_recording).
_RECORDING_UNAVAILABLE = (
    "⚠️ Live voice recording is temporarily unavailable: Discord now enforces "
    "end-to-end encryption (DAVE) on voice, and audio reception isn't supported "
    "by the bot library yet (py-cord issue #3139).\n"
    "Meanwhile you can still: record the call with another tool and upload it in "
    "the web UI, and ask me about saved meetings with "
    "`@me question <date> <question>`."
)


def _intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True  # needed to read the text after the mention
    intents.voice_states = True
    intents.members = True
    return intents


bot = discord.Bot(intents=_intents())


@bot.event
async def on_ready() -> None:
    print(f"Discord bot logged in as {bot.user} (id={bot.user.id})")


@bot.event
async def on_message(message: discord.Message) -> None:
    # Ignore our own messages and anything that doesn't mention us.
    if message.author.bot or bot.user not in message.mentions:
        return

    command = _strip_mention(message.content).strip()
    lowered = command.lower()

    try:
        if lowered.startswith(("help", "pomoc", "commands", "komendy")):
            await _handle_help(message)
        elif lowered.startswith(("askall", "ask-all", "askeverything")):
            await _handle_ask_all(message, command)
        elif lowered.startswith(("question", "ask", "pytanie")):
            await _handle_question(message, command)
        elif lowered.startswith(("search", "szukaj")):
            await _handle_search(message, command)
        elif lowered.startswith(("list", "meetings", "lista", "spotkania")):
            await _handle_list(message)
        elif lowered.startswith(("stop", "leave", "koniec")):
            await _stop_recording(message)
        else:
            await _start_recording(message)
    except Exception:  # noqa: BLE001 — surface failures to the channel, keep the bot alive
        traceback.print_exc()
        await message.channel.send("⚠️ Something went wrong handling that. Check the logs.")


def _strip_mention(content: str) -> str:
    """Remove the leading @bot mention(s) from a message's raw content."""
    for token in (f"<@{bot.user.id}>", f"<@!{bot.user.id}>"):
        content = content.replace(token, "")
    return content


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
async def _start_recording(message: discord.Message) -> None:
    voice_state = message.author.voice
    if voice_state is None or voice_state.channel is None:
        await message.channel.send(
            "Join a voice channel first, then mention me to start recording."
        )
        return
    if message.guild.id in _active:
        await message.channel.send(
            "I'm already recording in this server. Mention me with `stop` to finish."
        )
        return

    channel = voice_state.channel
    vc = await channel.connect()

    # Discord enforced DAVE end-to-end encryption on voice (March 2026); voice
    # *reception* is not yet supported by py-cord (issue #3139). start_recording
    # currently raises, so fail gracefully instead of crashing — this path will
    # start working unchanged once upstream ships DAVE receive support.
    try:
        sink = WaveSink()
        vc.start_recording(sink, _on_recording_finished, message.guild.id)
    except Exception as exc:  # noqa: BLE001
        # Expected while Discord DAVE receive is unsupported (py-cord #3139).
        # Log one concise line instead of a scary full traceback.
        print(f"Voice recording unavailable (DAVE / py-cord #3139): {type(exc).__name__}: {exc}")
        try:
            await vc.disconnect()
        except Exception:  # noqa: BLE001
            pass
        await message.channel.send(_RECORDING_UNAVAILABLE)
        return

    meeting = store.create_meeting(
        source="discord",
        channel=channel.name,
        title=f"{channel.name} — {message.guild.name}",
    )
    _active[message.guild.id] = {
        "vc": vc,
        "meeting": meeting,
        "text_channel": message.channel,
        "guild": message.guild,
    }
    await message.channel.send(
        f"🔴 Recording in **{channel.name}**. Mention me with `stop` when you're done."
    )


async def _stop_recording(message: discord.Message) -> None:
    ctx = _active.get(message.guild.id)
    if ctx is None:
        await message.channel.send("I'm not recording anything right now.")
        return
    await message.channel.send("⏳ Stopping and processing the recording...")
    ctx["vc"].stop_recording()  # triggers _on_recording_finished


async def _on_recording_finished(sink: WaveSink, guild_id: int) -> None:
    """Called by py-cord once recording stops: mix → transcribe → summarise → post."""
    ctx = _active.pop(guild_id, None)
    if ctx is None:
        return
    text_channel: discord.abc.Messageable = ctx["text_channel"]
    meeting: store.Meeting = ctx["meeting"]
    guild: discord.Guild = ctx["guild"]

    try:
        await sink.vc.disconnect()
    except Exception:  # noqa: BLE001
        pass

    # Resolve participant display names for the metadata.
    participants = []
    for user_id in sink.audio_data:
        member = guild.get_member(user_id)
        participants.append(member.display_name if member else str(user_id))

    if not sink.audio_data:
        await text_channel.send("No audio was captured, so there's nothing to transcribe.")
        return

    settings = load_settings()
    try:
        # Mixing, transcription, and the AI calls all block — keep the event loop free.
        await asyncio.to_thread(_render_and_summarise, sink, meeting, participants, settings)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        await text_channel.send("⚠️ Failed to process the recording. Check the logs.")
        return

    summary = meeting.summary_text() or "(empty summary)"
    await text_channel.send(f"✅ **Meeting summary — {meeting.title}**")
    for chunk in _chunks(summary, 1900):  # Discord's 2000-char message limit
        await text_channel.send(chunk)
    hint = f"@{bot.user.name} question {meeting.created_at[:10]} <your question>"
    await text_channel.send(f"Ask me anything about it: `{hint}`")


def _render_and_summarise(sink: WaveSink, meeting: store.Meeting, participants, settings) -> None:
    """Blocking work: mix per-speaker tracks, transcribe, summarise, persist."""
    mixed = _mix_tracks(sink)
    mixed.export(meeting.audio_path, format="mp3")
    meeting.update(
        participants=participants,
        duration_seconds=round(mixed.duration_seconds, 1),
    )
    transcribe(
        meeting.audio_path,
        meeting.transcript_path,
        model_size=settings.whisper_model,
        language=settings.language,
    )
    if should_summarize(settings):
        summarize_meeting(meeting, settings)


def _mix_tracks(sink: WaveSink) -> AudioSegment:
    """Overlay every speaker's WAV track into one audio segment."""
    segments = []
    for audio in sink.audio_data.values():
        audio.file.seek(0)
        segments.append(AudioSegment.from_file(io.BytesIO(audio.file.read()), format="wav"))
    mixed = segments[0]
    for segment in segments[1:]:
        mixed = mixed.overlay(segment)
    return mixed


# --------------------------------------------------------------------------- #
# Q&A
# --------------------------------------------------------------------------- #
async def _handle_help(message: discord.Message) -> None:
    me = f"@{bot.user.name}"
    await message.channel.send(
        "**Meeting Scribe — commands** (mention me):\n"
        f"• `{me}` — join your voice channel and record  ⚠️ *live recording is "
        "currently unavailable (Discord DAVE encryption); upload recordings in the "
        "web UI instead*\n"
        f"• `{me} stop` — stop recording, then post the summary\n"
        f"• `{me} list` — list recent meetings with their ids\n"
        f"• `{me} search <text>` — find meetings mentioning some text\n"
        f"• `{me} question <your question>` — ask about the most recent meeting\n"
        f"• `{me} question <id-or-date> <your question>` — ask about a specific "
        "meeting (use the id from `list`; an id is unique, a date may match several)\n"
        f"• `{me} askall <your question>` — answer across all meetings, with citations\n"
        f"• `{me} help` — show this help"
    )


async def _handle_list(message: discord.Message) -> None:
    meetings = store.list_meetings()
    if not meetings:
        await message.channel.send("No meetings yet. Upload one in the web UI.")
        return
    lines = ["**Recent meetings** (use the id to ask about a specific one):"]
    for m in meetings[:10]:
        when = m.created_at[:16].replace("T", " ")
        flag = "" if m.status == "done" else f" [{m.status}]"
        lines.append(f"• `{m.name}` — {m.title or '(no title)'} ({when}){flag}")
    for chunk in _chunks("\n".join(lines), 1900):
        await message.channel.send(chunk)


async def _handle_question(message: discord.Message, command: str) -> None:
    # Drop the leading verb (question/ask/pytanie).
    _, _, rest = command.partition(" ")
    rest = rest.strip()
    if not rest:
        await message.channel.send("Ask me something, e.g. `@me question what were the decisions?`")
        return
    if not store.list_meetings():
        await message.channel.send("There are no meetings yet. Upload one in the web UI.")
        return

    # Treat the first token as a meeting selector only if it actually matches one.
    first, _, remainder = rest.partition(" ")
    remainder = remainder.strip()
    matches = store.find_meetings(first) if first else []
    if remainder and matches:
        if len(matches) > 1:
            listing = "\n".join(f"• `{m.name}` — {m.title or '(no title)'}" for m in matches[:10])
            await message.channel.send(
                "That matches several meetings — repeat your question with the exact "
                f"id:\n{listing}"
            )
            return
        meeting, question = matches[0], remainder
    else:
        meeting, question = store.list_meetings()[0], rest

    if not meeting.transcript_text().strip():
        await message.channel.send("That meeting doesn't have a transcript yet.")
        return

    transcript = meeting.transcript_text()
    history = store.load_qa(meeting)[-6:]  # recent turns for follow-up context
    async with message.channel.typing():
        answer = await asyncio.to_thread(lambda: ai.answer(question, transcript, history=history))
    store.append_qa(meeting, question, answer)

    header = f"**{meeting.title or meeting.name}** ({meeting.created_at[:10]})\n"
    for chunk in _chunks(header + answer, 1900):
        await message.channel.send(chunk)


async def _handle_ask_all(message: discord.Message, command: str) -> None:
    _, _, rest = command.partition(" ")
    rest = rest.strip()
    if not rest:
        await message.channel.send("Usage: `@me askall <question>`")
        return
    corpus = store.corpus()
    if not corpus.strip():
        await message.channel.send("There are no meetings yet.")
        return
    async with message.channel.typing():
        answer = await asyncio.to_thread(ai.ask_across, rest, corpus)
    for chunk in _chunks(answer, 1900):
        await message.channel.send(chunk)


async def _handle_search(message: discord.Message, command: str) -> None:
    _, _, rest = command.partition(" ")
    rest = rest.strip()
    if not rest:
        await message.channel.send("Usage: `@me search <text>`")
        return
    results = store.search(rest)[:8]
    if not results:
        await message.channel.send(f"No meetings match “{rest}”.")
        return
    lines = [f"**{len(results)} match(es) for “{rest}”:**"]
    for meeting, _snippet in results:
        lines.append(f"• `{meeting.name}` — {meeting.title or '(no title)'}")
    for chunk in _chunks("\n".join(lines), 1900):
        await message.channel.send(chunk)


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def run() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set")
    bot.run(token)


if __name__ == "__main__":
    run()
