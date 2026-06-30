"""Tests for the pipeline entry point in main.py.

The two heavy steps (extract_audio, transcribe) are mocked; we only verify
that main routes video vs. audio inputs and wires up the right paths.
"""

from __future__ import annotations

from unittest import mock

import pytest

import config
import main


def _run_main(argv, monkeypatch):
    """Run main.main() with patched argv and mocked pipeline steps."""
    monkeypatch.setattr("sys.argv", ["main.py", *argv])
    with (
        mock.patch.object(main, "extract_audio") as extract,
        mock.patch.object(main, "transcribe") as trans,
    ):
        main.main()
    return extract, trans


def test_video_input_extracts_then_transcribes(tmp_path, monkeypatch):
    video = tmp_path / "recording.mp4"
    video.write_bytes(b"fake")

    extract, trans = _run_main([str(video)], monkeypatch)

    # Video is extracted to an .mp3 first.
    extract.assert_called_once()
    assert extract.call_args.args[0] == video
    intermediate_audio = extract.call_args.args[1]
    assert intermediate_audio.suffix == ".mp3"
    assert intermediate_audio.stem == "recording"

    # Then the extracted audio is transcribed (not the video).
    assert trans.call_args.args[0] == intermediate_audio


def test_audio_input_transcribes_directly_without_extraction(tmp_path, monkeypatch):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")

    extract, trans = _run_main([str(audio)], monkeypatch)

    extract.assert_not_called()
    # The audio file itself is transcribed.
    assert trans.call_args.args[0] == audio


def test_default_transcript_uses_timestamped_results_folder(tmp_path, monkeypatch):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")

    _extract, trans = _run_main([str(audio)], monkeypatch)

    transcript = trans.call_args.args[1]
    assert transcript.parent.parent == config.RESULTS_DIR
    assert transcript.parent.name.startswith("meeting-")
    assert transcript.name == "voice.txt"


def test_explicit_name_and_transcript_override(tmp_path, monkeypatch):
    video = tmp_path / "rec.mp4"
    video.write_bytes(b"fake")
    out = tmp_path / "notes.txt"

    extract, trans = _run_main(
        [str(video), "--name", "standup", "--transcript", str(out)], monkeypatch
    )

    # Intermediate audio lands in results/standup/ ...
    assert extract.call_args.args[1] == config.RESULTS_DIR / "standup" / "rec.mp3"
    # ... but the transcript honours the explicit override.
    assert trans.call_args.args[1] == out


def test_unsupported_extension_is_rejected(tmp_path, monkeypatch):
    bogus = tmp_path / "file.txt"
    bogus.write_text("nope", encoding="utf-8")

    # argparse .error() raises SystemExit after our ValueError is caught.
    with pytest.raises(SystemExit):
        _run_main([str(bogus)], monkeypatch)


def test_missing_input_is_rejected(tmp_path, monkeypatch):
    missing = tmp_path / "ghost.mp4"
    with pytest.raises(SystemExit):
        _run_main([str(missing)], monkeypatch)
