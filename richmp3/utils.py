"""Small, dependency-free helpers shared across modules."""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import threading
import time
import unicodedata
from collections import deque
from pathlib import Path


class Cancelled(Exception):
    """Raised when the user interrupts the run."""


# ---------------------------------------------------------------------------
# Human-readable formatting
# ---------------------------------------------------------------------------


def format_bytes(num: float | None) -> str:
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return ""
    return f"{format_bytes(bytes_per_second)}/s"


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "--:--"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0 or seconds > 24 * 3600:
        return "--:--"
    return format_duration(seconds)


def shorten(text: str, width: int) -> str:
    if width <= 0:
        return ""
    text = " ".join(str(text).split())
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


# ---------------------------------------------------------------------------
# Filesystem-safe, unicode-preserving names
# ---------------------------------------------------------------------------

_INVALID_FILENAME_CHARS = '<>:"/\\|?*'
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_BIDI_CONTROLS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_WHITESPACE = re.compile(r"\s+")
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}


def _truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", "ignore")
    return truncated, True


def sanitize_filename(name: str, max_bytes: int = 180, fallback: str = "untitled") -> str:
    """Make ``name`` safe for filesystems without losing Arabic or emoji."""
    text = unicodedata.normalize("NFC", str(name))
    text = _BIDI_CONTROLS.sub("", text)
    text = _CONTROL_CHARS.sub(" ", text)
    text = "".join(" " if char in _INVALID_FILENAME_CHARS else char for char in text)
    text = _WHITESPACE.sub(" ", text).strip(" .")

    if not text:
        text = fallback

    if text.split(".")[0].upper() in _RESERVED_NAMES:
        text = f"_{text}"

    # Preserve the extension while keeping the whole component inside the byte
    # budget; UTF-8 characters must never be cut in half.
    stem, dot, suffix = text.rpartition(".")
    if dot and 0 < len(suffix) <= 8 and stem:
        keep = max_bytes - len(dot + suffix)
        if keep > 0:
            stem, was_cut = _truncate_utf8(stem, keep)
            text = f"{stem}{dot}{suffix}"
        else:
            was_cut = True
    else:
        text, was_cut = _truncate_utf8(text, max_bytes)

    if was_cut:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        room = max(8, max_bytes - len(digest) - 1)
        text, _ = _truncate_utf8(text, room)
        text = f"{text}-{digest}"

    return text.rstrip(" .") or fallback


def unique_path(path: Path) -> Path:
    """Return ``path`` or the first free ``name (n).ext`` variant."""
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}-{int(time.time())}{path.suffix}")


def safe_unlink(path: Path | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Networking helpers
# ---------------------------------------------------------------------------

_RATE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmg]?)\s*$", re.IGNORECASE)
_RATE_FACTORS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def parse_rate(value: str | int | None) -> int | None:
    """Parse ``500k`` / ``1.5M`` / ``800000`` into bytes per second."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    match = _RATE_RE.match(str(value))
    if not match:
        raise ValueError(f"Invalid rate limit: {value!r} (use e.g. 500k, 1M)")
    return int(float(match.group(1)) * _RATE_FACTORS[match.group(2).lower()])


# ---------------------------------------------------------------------------
# Process control
# ---------------------------------------------------------------------------


def terminate_process(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    """Ask a child (and its process group) to exit, then force it."""
    if proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:  # pragma: no cover - non-POSIX fallback
            proc.terminate()
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class Log:
    """Thread-safe file logger with an in-memory tail for the TUI footer."""

    def __init__(self, path: Path | None = None, keep: int = 200) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._messages: deque[str] = deque(maxlen=keep)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def _write(self, level: str, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} [{level}] {message}"
        with self._lock:
            self._messages.append(line)
            if self.path:
                try:
                    with open(self.path, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except OSError:
                    pass

    def debug(self, message: str) -> None:
        self._write("debug", message)

    def info(self, message: str) -> None:
        self._write("info", message)

    def warning(self, message: str) -> None:
        self._write("warn", message)

    def error(self, message: str) -> None:
        self._write("error", message)

    def tail(self, count: int = 3) -> list[str]:
        with self._lock:
            return list(self._messages)[-count:]
