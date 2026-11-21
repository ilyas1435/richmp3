"""Small terminal wizard for speech-friendly, MP3-player-compatible settings."""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import tomllib
from pathlib import Path
from typing import Callable

from .config import (
    config_path_default,
    default_convert_workers,
    default_output_directory,
)

Input = Callable[[str], str]
Output = Callable[[str], object]


def configure_interactively(
    input_fn: Input = input,
    output_fn: Output = print,
) -> tuple[list[str], dict[str, object]] | None:
    """Ask for an MP3 quality profile, phone workload, and URLs.

    Return ``None`` when the user cancels at the confirmation step.
    """
    settings = collect_settings(input_fn, output_fn)
    if settings is None:
        return None

    urls_text = input_fn(
        "\nPaste one URL or multiple URLs separated by spaces: "
    ).strip()
    try:
        urls = shlex.split(urls_text)
    except ValueError:
        output_fn("Could not parse URLs. Check the quotation marks.")
        return None
    if not urls:
        output_fn("No URL was entered.")
        return None

    _print_summary(settings, output_fn)
    if not _yes_no(input_fn, "Start downloading with these settings? [Y/n]: ", default=True):
        output_fn("Cancelled. No files were changed.")
        return None
    return urls, settings


def save_settings_interactively(
    input_fn: Input = input,
    output_fn: Output = print,
    config_path: Path | None = None,
) -> Path | None:
    """Collect settings and save them as future defaults without downloading."""
    settings = collect_settings(input_fn, output_fn)
    if settings is None:
        return None
    _print_summary(settings, output_fn)
    path = config_path or config_path_default()
    if path is None:
        path = Path.home() / ".config" / "richmp3" / "config.toml"
    if not _yes_no(input_fn, f"Save these settings to {path}? [Y/n]: ", default=True):
        output_fn("Settings were not changed.")
        return None
    write_settings(path, settings)
    output_fn("Settings saved. Run 'richmp3 settings' to change them later.")
    return path


def collect_settings(
    input_fn: Input = input,
    output_fn: Output = print,
) -> dict[str, object] | None:
    """Prompt for speech quality, phone workload, output, and archive settings."""
    output_fn("\nQuick audio setup")
    output_fn("All presets create mono MP3 for broad MP3-player compatibility.")
    output_fn("\nMP3 encoding mode:")
    output_fn("  1) VBR — quality-based, compact (recommended)")
    output_fn("  2) ABR — target average bitrate")
    output_fn("  3) CBR — fixed bitrate")
    mode_choice = _choice(input_fn, "Choose mode [1]: ", {"1", "2", "3"}, "1")
    mode = {"1": "vbr", "2": "abr", "3": "cbr"}[mode_choice]

    if mode == "vbr":
        output_fn("\nVBR quality (lower number means clearer audio and larger files):")
        output_fn("  1) Smallest speech files — Q8")
        output_fn("  2) Balanced lectures — Q7 (recommended)")
        output_fn("  3) Clearer speech — Q5")
        output_fn("  4) Custom")
        quality = _choice(input_fn, "Choose VBR quality [2]: ", {"1", "2", "3", "4"}, "2")
        vbr_presets = {"1": 8, "2": 7, "3": 5}
        vbr_quality = (
            _number(input_fn, "VBR quality [7] (0-9): ", 7, 0, 9)
            if quality == "4"
            else vbr_presets[quality]
        )
        bitrate = 24
        sample_rate = {"1": 11025, "2": 11025, "3": 16000}.get(quality, 11025)
        if quality == "4":
            sample_rate = int(_choice(
                input_fn,
                "Sample rate in Hz (8000/11025/12000/16000/22050) [11025]: ",
                {"8000", "11025", "12000", "16000", "22050"},
                "11025",
            ))
    else:
        output_fn("\nAudio quality and file size:")
        output_fn("  1) Smallest — 16 kbps, 11025 Hz (less clear speech)")
        output_fn("  2) Balanced for lectures — 24 kbps, 11025 Hz (recommended)")
        output_fn("  3) Clearer speech — 32 kbps, 16000 Hz")
        output_fn("  4) Custom")
        quality = _choice(input_fn, "Choose quality [2]: ", {"1", "2", "3", "4"}, "2")
        profiles = {"1": (16, 11025), "2": (24, 11025), "3": (32, 16000)}
        if quality == "4":
            bitrate = _number(input_fn, "Target bitrate in kbps [24]: ", 24, 8, 64)
            sample_rate = int(_choice(
                input_fn,
                "Sample rate in Hz (8000/11025/12000/16000/22050) [11025]: ",
                {"8000", "11025", "12000", "16000", "22050"},
                "11025",
            ))
        else:
            bitrate, sample_rate = profiles[quality]
        vbr_quality = 7

    output_fn("\nPhone speed and battery use:")
    output_fn("  1) Battery saver — 1 download, 1 encoder, 2 fragments")
    output_fn("  2) Balanced — 4 downloads, up to 4 encoders, 8 fragments")
    output_fn("  3) Maximum speed — 8 downloads, up to 8 encoders, 16 fragments")
    output_fn("Maximum speed uses more battery and can make the phone warmer.")
    speed = _choice(input_fn, "Choose speed [3]: ", {"1", "2", "3"}, "3")
    balanced_encoders = min(4, default_convert_workers())
    max_encoders = default_convert_workers()
    workloads = {
        "1": (1, 1, 2),
        "2": (4, balanced_encoders, 8),
        "3": (8, max_encoders, 16),
    }
    download_workers, convert_workers, fragments = workloads[speed]

    output_fn("\nAudio language:")
    output_fn("Use 'original' by default, or enter a code from 'richmp3 languages URL'.")
    audio_language = input_fn("Preferred audio language [original]: ").strip() or "original"

    default_output = default_output_directory()
    output_text = input_fn(
        f"\nOutput folder [Download folder: {default_output}]: "
    ).strip()
    output_path = str(Path(output_text).expanduser()) if output_text else str(default_output)
    zip_output = _yes_no(
        input_fn,
        "Create a ZIP? Choose no for MP3-player files [n]: ",
        default=False,
    )
    return {
        "format": "mp3",
        "audio_language": audio_language,
        "mode": mode,
        "vbr_quality": vbr_quality,
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "voice_filter": True,
        "download_workers": download_workers,
        "convert_workers": convert_workers,
        "concurrent_fragments": fragments,
        "output": output_path,
        "zip": zip_output,
    }


def _print_summary(settings: dict[str, object], output_fn: Output) -> None:
    mode = str(settings["mode"])
    encode_label = (
        f"VBR Q{settings['vbr_quality']}"
        if mode == "vbr"
        else f"{mode.upper()} {settings['bitrate']} kbps"
    )
    output_fn(
        f"\nSelected: mono MP3, {encode_label}, "
        f"{settings['sample_rate']} Hz, {settings['download_workers']} downloads, "
        f"{settings['convert_workers']} encoder(s), "
        f"language {settings['audio_language']}, "
        f"ZIP {'yes' if settings['zip'] else 'no'}."
    )


def write_settings(path: Path, settings: dict[str, object]) -> None:
    """Atomically update top-level TOML keys while retaining unrelated content."""
    path = Path(path).expanduser()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing:
        tomllib.loads(existing)  # refuse to overwrite an already-invalid file

    replacements = {key: f"{key} = {_toml_value(value)}" for key, value in settings.items()}
    seen: set[str] = set()
    output_lines: list[str] = []
    in_table = False
    first_table_line: int | None = None
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_table = True
            if first_table_line is None:
                first_table_line = len(output_lines)
        match = None if in_table else re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line)
        key = match.group(1) if match else None
        if key in replacements:
            output_lines.append(replacements[key])
            seen.add(key)
        else:
            output_lines.append(line)
    missing = [replacements[key] for key in replacements if key not in seen]
    if first_table_line is None:
        output_lines.extend(missing)
    elif missing:
        output_lines[first_table_line:first_table_line] = missing + [""]
    content = "\n".join(output_lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"Unsupported TOML setting value: {type(value).__name__}")


def _choice(
    input_fn: Input, prompt: str, choices: set[str], default: str
) -> str:
    while True:
        value = input_fn(prompt).strip() or default
        if value in choices:
            return value


def _number(
    input_fn: Input, prompt: str, default: int, minimum: int, maximum: int
) -> int:
    while True:
        value = input_fn(prompt).strip()
        if not value:
            return default
        try:
            number = int(value)
        except ValueError:
            continue
        if minimum <= number <= maximum:
            return number


def _yes_no(input_fn: Input, prompt: str, default: bool) -> bool:
    while True:
        value = input_fn(prompt).strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
