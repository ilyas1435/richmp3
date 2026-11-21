"""Interactive Replit launcher; the existing CLI handles all downloads."""

import shlex
import subprocess
import sys


def main() -> None:
    print("RichMP3 — enter a URL and optional command-line flags.")
    print("Example: --no-zip https://example.org/audio.mp3")
    print("Type --help for options, or quit to exit.", flush=True)
    while True:
        try:
            line = input("\nRichMP3> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTo run directly in Shell: python -m richmp3 --help")
            return
        if line.lower() in {"quit", "exit"}:
            return
        if not line:
            continue
        try:
            args = shlex.split(line)
        except ValueError as exc:
            print(f"Invalid arguments: {exc}")
            continue
        try:
            result = subprocess.run([sys.executable, "-m", "richmp3", *args])
        except KeyboardInterrupt:
            print("\nDownload interrupted.")
            continue
        if result.returncode:
            print(f"RichMP3 exited with code {result.returncode}.")


if __name__ == "__main__":
    main()
