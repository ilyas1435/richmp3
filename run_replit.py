"""Interactive Replit launcher; the existing CLI handles all downloads."""

import shlex
import subprocess
import sys


def main() -> None:
    print("RichMP3 — enter a URL, or use :settings / :update / :menu.")
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
        command = line.lower()
        if command in {":settings", ":s", "settings"}:
            from richmp3.cli import main as richmp3_main

            result = richmp3_main(["--settings"])
            if result:
                print(f"RichMP3 exited with code {result}.")
            continue
        if command in {":update", "update"}:
            from richmp3.cli import main as richmp3_main

            result = richmp3_main(["--update"])
            if result:
                print(f"RichMP3 exited with code {result}.")
            continue
        if command in {":menu", "menu", "wizard"}:
            from richmp3.cli import main as richmp3_main

            result = richmp3_main(["--wizard"])
            if result:
                print(f"RichMP3 exited with code {result}.")
            continue
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
