"""Typed configuration and validation for RichMP3."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

BITRATE_MIN = 8
BITRATE_MAX = 128
SAMPLE_RATE_MIN = 8000
SAMPLE_RATE_MAX = 44100

# Legitimate sample rates per codec.  MP3 cannot encode 11000 Hz; it supports
# the MPEG-2.5/2/1 rates below, so user input is snapped to the nearest one.
MP3_SAMPLE_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)
OPUS_SAMPLE_RATES = (8000, 12000, 16000, 24000, 48000)

AUDIO_FORMATS = ("mp3", "opus")
MODES = ("vbr", "abr", "cbr")
ZIP_METHODS = ("stored", "deflate")

CONFIG_KEYS = frozenset(
    {
        "output",
        "bitrate",
        "vbr_quality",
        "sample_rate",
        "format",
        "mode",
        "voice_filter",
        "download_workers",
        "convert_workers",
        "playlist",
        "zip",
        "zip_method",
        "cookies",
        "limit_rate",
        "js_runtime",
        "remote_components",
        "retries",
        "number_width",
        "overwrite",
        "keep_folder",
        "no_ui",
        "log_file",
        "timeout",
        "concurrent_fragments",
        "audio_language",
    }
)


def is_termux() -> bool:
    return (
        os.environ.get("PREFIX", "").startswith("/data/data/com.termux/")
        or bool(os.environ.get("TERMUX_VERSION"))
    )


def default_output_directory() -> Path:
    """Use Android shared Downloads in Termux; use a local folder elsewhere."""
    if is_termux():
        return Path.home() / "storage" / "shared" / "Download"
    return Path("downloads")


def default_convert_workers() -> int:
    cpus = os.cpu_count() or 2
    return max(1, min(8, cpus))


def default_download_workers() -> int:
    return 8


@dataclass(frozen=True)
class Settings:
    """Immutable, fully validated run configuration."""

    output: Path = field(default_factory=default_output_directory)
    bitrate: int = 24
    vbr_quality: int = 7
    sample_rate: int = 11025
    audio_format: str = "mp3"
    mode: str = "vbr"
    voice_filter: bool = True
    audio_language: str = "original"

    download_workers: int = field(default_factory=default_download_workers)
    convert_workers: int = field(default_factory=default_convert_workers)
    playlist: bool = True
    zip_output: bool = True
    zip_method: str = "stored"

    cookies: Path | None = None
    limit_rate: str | None = None
    js_runtime: str | None = "auto"
    remote_components: bool = False
    retries: int = 3
    number_width: int = 0
    overwrite: bool = False
    keep_folder: bool = False
    no_ui: bool = False
    force_ui: bool = False
    log_file: Path | None = None
    dry_run: bool = False
    timeout: float = 30.0
    concurrent_fragments: int = 16

    @property
    def extension(self) -> str:
        return self.audio_format

    @property
    def mode_label(self) -> str:
        """Return the effective MP3 or Opus encoding mode."""
        if self.audio_format == "opus":
            return "VBR"
        return self.mode.upper()

    @property
    def encoding_label(self) -> str:
        """Describe the active quality/bitrate setting without ambiguity."""
        if self.audio_format == "opus":
            return f"VBR {self.bitrate} kbps"
        if self.mode == "vbr":
            return f"VBR Q{self.vbr_quality}"
        return f"{self.mode.upper()} {self.bitrate} kbps"

    @property
    def sample_rates(self) -> tuple[int, ...]:
        return MP3_SAMPLE_RATES if self.audio_format == "mp3" else OPUS_SAMPLE_RATES

    def with_overrides(self, **changes: Any) -> "Settings":
        return replace(self, **changes)


def snap_sample_rate(requested: int, audio_format: str) -> int:
    """Return the legal sample rate closest to ``requested``."""
    rates = MP3_SAMPLE_RATES if audio_format == "mp3" else OPUS_SAMPLE_RATES
    bounded = max(SAMPLE_RATE_MIN, min(SAMPLE_RATE_MAX, requested))
    return min(rates, key=lambda rate: (abs(rate - bounded), -rate))


def max_mp3_bitrate(sample_rate: int) -> int:
    """Highest MP3 bitrate permitted by the MPEG version implied by a rate."""
    if sample_rate <= 12000:
        return 64
    if sample_rate <= 24000:
        return 160
    return 320


def finalize(settings: Settings) -> tuple[Settings, list[str]]:
    """Clamp/snap values and return (settings, human-readable notices)."""
    notices: list[str] = []

    audio_language = str(settings.audio_language).strip()
    if not _is_valid_audio_language(audio_language):
        raise ValueError(
            "audio_language must be 'original' or a language code such as 'en' or 'ar'"
        )

    bitrate = max(BITRATE_MIN, min(BITRATE_MAX, settings.bitrate))
    if bitrate != settings.bitrate:
        notices.append(f"Bitrate {settings.bitrate} kbps clamped to {bitrate} kbps")

    sample_rate = snap_sample_rate(settings.sample_rate, settings.audio_format)
    if sample_rate != settings.sample_rate:
        notices.append(
            f"Sample rate {settings.sample_rate} Hz is not valid for "
            f"{settings.audio_format.upper()}; using {sample_rate} Hz"
        )

    if settings.audio_format == "mp3" and settings.mode != "vbr":
        legal_max = max_mp3_bitrate(sample_rate)
        if bitrate > legal_max:
            notices.append(
                f"Bitrate {bitrate} kbps exceeds the MP3 ceiling for "
                f"{sample_rate} Hz; using {legal_max} kbps"
            )
            bitrate = legal_max
    elif settings.audio_format == "opus" and settings.mode != "vbr":
        notices.append("Opus is always VBR; the MP3 mode setting is ignored")

    vbr_quality = max(0, min(9, settings.vbr_quality))
    if vbr_quality != settings.vbr_quality:
        notices.append(f"VBR quality {settings.vbr_quality} clamped to {vbr_quality}")

    workers = max(1, min(16, settings.download_workers))
    if workers != settings.download_workers:
        notices.append(f"Download workers clamped to {workers}")
    convert_workers = max(1, min(8, settings.convert_workers))
    if convert_workers != settings.convert_workers:
        notices.append(f"Conversion workers clamped to {convert_workers}")

    width = settings.number_width
    if width and not 2 <= width <= 10:
        width = max(2, min(10, width))
        notices.append(f"Number width clamped to {width}")

    retries = max(0, min(10, settings.retries))
    if retries != settings.retries:
        notices.append(f"Retries clamped to {retries}")

    fragments = max(1, min(16, settings.concurrent_fragments))
    timeout = max(5.0, min(300.0, settings.timeout))
    output = Path(settings.output).expanduser()
    if is_termux() and output == default_output_directory():
        shared_storage = Path.home() / "storage" / "shared"
        if not shared_storage.is_dir() or not os.access(shared_storage, os.W_OK):
            raise ValueError(
                "Android shared storage is not available. "
                "Run 'termux-setup-storage', grant access, and try again."
            )

    normalized = replace(
        settings,
        output=output,
        vbr_quality=vbr_quality,
        audio_language=audio_language,
        bitrate=bitrate,
        sample_rate=sample_rate,
        download_workers=workers,
        convert_workers=convert_workers,
        number_width=width,
        retries=retries,
        concurrent_fragments=fragments,
        timeout=timeout,
        cookies=Path(settings.cookies).expanduser() if settings.cookies else None,
        log_file=Path(settings.log_file).expanduser() if settings.log_file else None,
    )
    return normalized, notices


def _is_valid_audio_language(value: str) -> bool:
    if value.casefold() == "original":
        return True
    parts = value.replace("_", "-").split("-")
    return (
        1 <= len(parts) <= 3
        and 2 <= len(parts[0]) <= 3
        and parts[0].isalpha()
        and all(1 <= len(part) <= 8 and part.isalnum() for part in parts[1:])
    )


def load_config(path: Path) -> dict[str, Any]:
    """Read a TOML config file and drop unrecognised keys."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return {key: value for key, value in data.items() if key in CONFIG_KEYS}


def config_path_default() -> Path | None:
    """Locate an implicit config file, if one exists."""
    candidates = [
        Path.cwd() / "richmp3.toml",
        Path.home() / ".config" / "richmp3" / "config.toml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
