"""Claude-powered summarisation and Q&A over meeting transcripts.

This is the only place the project talks to an LLM. Everything else
(transcription, recording, storage, search) is deterministic. Summaries and
answers are driven entirely by the editable :class:`ExtractionSettings`, so the
behaviour can be tuned from the UI without code changes.

Requires ``ANTHROPIC_API_KEY`` in the environment (the Anthropic SDK reads it
automatically).
"""

from __future__ import annotations

from anthropic import Anthropic

from settings import ExtractionSettings, load_settings

# Streamed so large transcripts don't trip the SDK's non-streaming timeout.
_MAX_TOKENS = 8000


def _client() -> Anthropic:
    # Reads ANTHROPIC_API_KEY (or an `ant` profile) from the environment.
    return Anthropic()


def _sections_block(settings: ExtractionSettings) -> str:
    return "\n".join(f"## {s.title}\n{s.instructions}" for s in settings.sections)


def summarize(
    transcript: str,
    settings: ExtractionSettings | None = None,
    *,
    title: str = "",
) -> str:
    """Summarise *transcript* into Markdown shaped by *settings*.

    The output sections, their order, and the instructions for each come from
    ``settings.sections`` — edit those (in the UI) to change what is extracted.
    """
    settings = settings or load_settings()
    if not transcript.strip():
        return "_No transcript to summarise._"

    heading = f" titled '{title}'" if title else ""
    instructions = (
        f"{settings.summary_instructions}\n\n"
        f"Write the summary as Markdown with exactly these sections, in this "
        f"order. Use each section's heading verbatim:\n\n{_sections_block(settings)}\n\n"
        f"Here is the transcript of the meeting{heading}:"
    )

    client = _client()
    with client.messages.stream(
        model=settings.claude_model,
        max_tokens=_MAX_TOKENS,
        system=settings.summary_system,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instructions},
                    # Cache the transcript so a later Q&A on the same meeting is cheap.
                    {"type": "text", "text": transcript, "cache_control": {"type": "ephemeral"}},
                ],
            }
        ],
    ) as stream:
        message = stream.get_final_message()
    return _first_text(message)


def answer(
    question: str,
    transcript: str,
    settings: ExtractionSettings | None = None,
) -> str:
    """Answer *question* about a meeting, grounded only in *transcript*."""
    settings = settings or load_settings()
    if not transcript.strip():
        return "I don't have a transcript for this meeting yet."

    client = _client()
    with client.messages.stream(
        model=settings.claude_model,
        max_tokens=_MAX_TOKENS,
        system=settings.qa_system,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Meeting transcript:"},
                    {"type": "text", "text": transcript, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": f"Question: {question}"},
                ],
            }
        ],
    ) as stream:
        message = stream.get_final_message()
    return _first_text(message)


def title(transcript: str, settings: ExtractionSettings | None = None) -> str:
    """Generate a short, specific meeting title from the transcript (or "")."""
    settings = settings or load_settings()
    if not transcript.strip():
        return ""
    client = _client()
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=40,
        system=(
            "You write a concise, specific meeting title of at most 8 words. "
            "Reply with only the title — no quotes, no trailing punctuation. "
            "Use the language of the transcript."
        ),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Meeting transcript (may be truncated):"},
                    {"type": "text", "text": transcript[:8000]},
                ],
            }
        ],
    )
    return _first_text(message).strip().strip('"').strip()[:120]


def _first_text(message) -> str:
    """Pull the text out of a Claude response message."""
    parts = [block.text for block in message.content if block.type == "text"]
    return "\n".join(parts).strip()
