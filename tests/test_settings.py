"""Tests for the editable extraction settings."""

from __future__ import annotations

from settings import ExtractionSettings, Section, load_settings, save_settings


def test_load_creates_default_file_when_missing(tmp_path):
    path = tmp_path / "settings.json"
    settings = load_settings(path)

    assert path.exists()  # defaults were written out for editing
    assert settings.claude_model == "claude-opus-4-8"
    assert [s.title for s in settings.sections]  # has default sections


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = ExtractionSettings(
        language="pl",
        summary_instructions="custom",
        sections=[Section("Risks", "List risks")],
    )
    save_settings(original, path)

    loaded = load_settings(path)
    assert loaded.language == "pl"
    assert loaded.summary_instructions == "custom"
    assert [(s.title, s.instructions) for s in loaded.sections] == [("Risks", "List risks")]


def test_from_dict_ignores_unknown_keys():
    settings = ExtractionSettings.from_dict(
        {"claude_model": "x", "language": "en", "bogus": "ignored"}
    )
    assert settings.claude_model == "x"
    assert settings.language == "en"
    # Unknown key didn't blow up, and defaults filled the rest.
    assert settings.sections
