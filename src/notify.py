"""Wait for a file to appear, then beep until a key is pressed.

This is the Python port of the original ``wait-for-audio.ps1`` helper. It is
handy when a long transcription is running in another terminal: point it at the
output file and it will alert you when the job is done.

Used from the command line::

    uv run wait-for-file results/meeting/audio.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _beep(frequency: int = 880, duration_ms: int = 400) -> None:
    """Emit a beep, falling back to the terminal bell off Windows."""
    try:
        import winsound  # type: ignore[import-not-found]

        winsound.Beep(frequency, duration_ms)
    except (ImportError, RuntimeError):
        sys.stdout.write("\a")
        sys.stdout.flush()
        time.sleep(duration_ms / 1000)


def _key_pressed() -> bool:
    """Return True if a key is waiting in the input buffer (Windows only)."""
    try:
        import msvcrt  # type: ignore[import-not-found]

        if msvcrt.kbhit():
            msvcrt.getch()
            return True
    except ImportError:
        pass
    return False


def wait_for_file(
    target: str | Path,
    *,
    poll_seconds: int = 15,
    beep: bool = True,
) -> Path:
    """Block until *target* exists, then beep until a key is pressed."""
    target = Path(target)

    print(f"Waiting for {target} ...")
    while not target.exists():
        print(f"  still working... {time.strftime('%H:%M:%S')}")
        time.sleep(poll_seconds)

    print(f"\nDONE! {target} is ready.")
    if beep:
        print("Beeping until you press a key...")
        while not _key_pressed():
            _beep()
            time.sleep(0.3)
        print("Stopped beeping. Enjoy your transcript!")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wait for a file to appear, then beep until a key is pressed.",
    )
    parser.add_argument("target", type=Path, help="File to wait for")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=15,
        help="How often to check for the file (default: 15)",
    )
    parser.add_argument(
        "--no-beep",
        action="store_true",
        help="Do not beep once the file appears",
    )
    args = parser.parse_args()

    wait_for_file(args.target, poll_seconds=args.poll_seconds, beep=not args.no_beep)


if __name__ == "__main__":
    main()
