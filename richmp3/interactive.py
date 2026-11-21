"""Small terminal wizard for speech-friendly, MP3-player-compatible settings."""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
from pathlib import Path
import tomllib
from typing import Callable

from .config import config_path_default

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
        "\nالصق رابطًا واحدًا أو عدة روابط (افصل بينها بمسافات): "
    ).strip()
    try:
        urls = shlex.split(urls_text)
    except ValueError:
        output_fn("تعذر قراءة الروابط؛ راجع علامات الاقتباس.")
        return None
    if not urls:
        output_fn("لم يتم إدخال أي رابط.")
        return None

    _print_summary(settings, output_fn)
    if not _yes_no(input_fn, "بدء التنزيل بهذه الإعدادات؟ [نعم]: ", default=True):
        output_fn("أُلغي التشغيل دون تغيير أي ملفات.")
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
    if not _yes_no(input_fn, f"حفظ الإعدادات في {path}؟ [نعم]: ", default=True):
        output_fn("لم يتم تغيير الإعدادات.")
        return None
    write_settings(path, settings)
    output_fn(f"تم حفظ الإعدادات. غيّرها لاحقًا بالأمر: python -m richmp3 --settings")
    return path


def collect_settings(
    input_fn: Input = input,
    output_fn: Output = print,
) -> dict[str, object] | None:
    """Prompt for speech quality, phone workload, output, and archive settings."""
    output_fn("\nإعداد سريع للصوتيات والمحاضرات")
    output_fn("كل الخيارات تحفظ MP3 أحادي القناة لتوافق أفضل مع مشغلات MP3.")
    output_fn("\nجودة الصوت وحجم الملف:")
    output_fn("  1) أصغر حجم — 16 kbps، 11025 Hz (الصوت أقل وضوحًا)")
    output_fn("  2) متوازن للمحاضرات — 24 kbps، 11025 Hz (موصى به)")
    output_fn("  3) أوضح — 32 kbps، 16000 Hz")
    output_fn("  4) تحديد يدوي")
    quality = _choice(input_fn, "اختيار الجودة [2]: ", {"1", "2", "3", "4"}, "2")
    profiles = {
        "1": (16, 11025),
        "2": (24, 11025),
        "3": (32, 16000),
    }
    if quality == "4":
        bitrate = _number(input_fn, "معدل الضغط kbps [24]: ", 24, 8, 64)
        sample_rate = _choice(
            input_fn,
            "معدل العينة Hz (8000/11025/12000/16000/22050) [11025]: ",
            {"8000", "11025", "12000", "16000", "22050"},
            "11025",
        )
        bitrate_rate = (bitrate, int(sample_rate))
    else:
        bitrate_rate = profiles[quality]

    output_fn("\nسرعة التنزيل واستهلاك الهاتف:")
    output_fn("  1) توفير البطارية — تنزيل واحد، جزآن متوازيان")
    output_fn("  2) متوازن — تنزيلان، 4 أجزاء (موصى به)")
    output_fn("  3) أسرع على Wi-Fi — 3 تنزيلات، 8 أجزاء")
    speed = _choice(input_fn, "اختيار السرعة [2]: ", {"1", "2", "3"}, "2")
    workloads = {
        "1": (1, 1, 2),
        "2": (2, 1, 4),
        "3": (3, 1, 8),
    }
    download_workers, convert_workers, fragments = workloads[speed]

    default_output = Path.home() / "RichMP3"
    output_text = input_fn(
        f"\nمجلد الحفظ [تخزين Termux الداخلي الأسرع: {default_output}]: "
    ).strip()
    output_path = str(Path(output_text).expanduser()) if output_text else str(default_output)
    zip_output = _yes_no(
        input_fn,
        "إنشاء ZIP؟ اختر لا لتشغيل ملفات MP3 مباشرة [لا]: ",
        default=False,
    )
    bitrate, sample_rate = bitrate_rate
    return {
        "format": "mp3",
        "mode": "cbr",
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
    output_fn(
        f"\nالمقترح: MP3 أحادي، CBR {settings['bitrate']} kbps، "
        f"{settings['sample_rate']} Hz، {settings['download_workers']} تنزيل، "
        f"{settings['convert_workers']} تحويل، "
        f"ZIP {'نعم' if settings['zip'] else 'لا'}."
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
        if value in {"y", "yes", "نعم", "ن"}:
            return True
        if value in {"n", "no", "لا", "ل"}:
            return False
