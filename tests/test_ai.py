"""Tests for the Claude summarisation / Q&A layer.

The Anthropic client is faked, so no network or API key is needed — we only
verify that the right prompt is assembled and the response text is returned.
"""

from __future__ import annotations

from unittest import mock

import ai
from settings import ExtractionSettings, Section


class _FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeStream:
    def __init__(self, recorder, kwargs):
        self._recorder = recorder
        self._kwargs = kwargs

    def __enter__(self):
        self._recorder.append(self._kwargs)
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return _FakeMessage("FAKE RESPONSE")


def _fake_client(recorder):
    client = mock.Mock()
    client.messages.stream.side_effect = lambda **kwargs: _FakeStream(recorder, kwargs)
    return client


def test_summarize_builds_section_prompt(monkeypatch):
    recorder = []
    monkeypatch.setattr(ai, "_client", lambda: _fake_client(recorder))
    settings = ExtractionSettings(sections=[Section("Risks", "List the risks")])

    out = ai.summarize("Alice: ship Friday.", settings, title="Standup")

    assert out == "FAKE RESPONSE"
    kwargs = recorder[0]
    assert kwargs["model"] == settings.claude_model
    # Section heading + its instructions made it into the prompt.
    user_text = kwargs["messages"][0]["content"][0]["text"]
    assert "## Risks" in user_text and "List the risks" in user_text
    # Transcript is sent as a separate, cached block.
    transcript_block = kwargs["messages"][0]["content"][1]
    assert transcript_block["text"] == "Alice: ship Friday."
    assert transcript_block["cache_control"] == {"type": "ephemeral"}


def test_summarize_empty_transcript_short_circuits(monkeypatch):
    monkeypatch.setattr(ai, "_client", lambda: (_ for _ in ()).throw(AssertionError("called")))
    assert "No transcript" in ai.summarize("   ")


def test_answer_grounds_in_transcript(monkeypatch):
    recorder = []
    monkeypatch.setattr(ai, "_client", lambda: _fake_client(recorder))

    out = ai.answer("Who owns the docs?", "Bob: I'll write the docs.")

    assert out == "FAKE RESPONSE"
    content = recorder[0]["messages"][0]["content"]
    assert content[1]["text"] == "Bob: I'll write the docs."
    assert "Who owns the docs?" in content[2]["text"]


def test_answer_without_transcript(monkeypatch):
    monkeypatch.setattr(ai, "_client", lambda: (_ for _ in ()).throw(AssertionError("called")))
    assert "don't have a transcript" in ai.answer("q?", "")
