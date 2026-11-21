"""Command-line interface for RichMP3."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from . import __version__
from .config import (
    AUDIO_FORMATS,
    MODES,
    ZIP_METHODS,
    Settings,
    config_path_default,
    default_convert_workers,
    finalize,
    load_config,
)
from .downloader import DownloadError
from .models import Stage
from .pipeline import Pipeline
from .ui import UIContext, build_ui, print_dry_run, print_summary
from .utils import Log, parse_rate

EXAMPLES = """\
examples:
  richmp3 "https://www.youtube.com/playlist?list=..."
  richmp3 -b 32 -r 22050 --no-zip URL1 URL2
  richmp3 --format opus -b 24 -o ~/Music URL
  richmp3 --dry-run URL          show what would be created
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="richmp3",
        description=(
            "Download the lowest-bandwidth audio from YouTube, SoundCloud, "
            "Archive.org and 1000+ other sites, convert it to compact mono "
            "audio with FFmpeg, and archive playlists as ZIP files."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "urls", nargs="*", help="playlist, channel or track URL(s)"
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="output directory (default: ./downloads)",
    )
    parser.add_argument(
        "-b", "--bitrate", type=int, default=None,
        help="target bitrate in kbps, 8-128 (default: 24)",
    )
    parser.add_argument(
        "-r", "--sample-rate", type=int, default=None,
        help=(
            "sample rate in Hz, 8000-44100 "
            "(default: 11025 for MP3, 12000 for Opus; snapped to a legal value)"
        ),
    )
    parser.add_argument(
        "-f", "--format", dest="audio_format", choices=AUDIO_FORMATS, default=None,
        help="output container/codec (default: mp3)",
    )
    parser.add_argument(
        "--mode", choices=MODES, default=None,
        help="bitrate mode for MP3: abr (default) or cbr",
    )
    voice_group = parser.add_mutually_exclusive_group()
    voice_group.add_argument(
        "--voice-filter", dest="voice_filter", action="store_true", default=None,
        help="high-pass/low-pass filter at <=16 kHz for clearer voice (default)",
    )
    voice_group.add_argument(
        "--no-voice-filter", dest="voice_filter", action="store_false",
        help="disable the voice-clarity filter",
    )
    parser.add_argument(
        "-w", "--workers", dest="download_workers", type=int, default=None,
        help="parallel download workers (default: 4)",
    )
    parser.add_argument(
        "--convert-workers", type=int, default=None,
        help="parallel FFmpeg encoders (default: half the CPU cores, max 4)",
    )

    playlist_group = parser.add_mutually_exclusive_group()
    playlist_group.add_argument(
        "--playlist", dest="playlist", action="store_true", default=None,
        help="treat URLs as playlists (default)",
    )
    playlist_group.add_argument(
        "--no-playlist", dest="playlist", action="store_false",
        help="download only the single video behind a playlist URL",
    )

    zip_group = parser.add_mutually_exclusive_group()
    zip_group.add_argument(
        "--zip", dest="zip_output", action="store_true", default=None,
        help="archive each finished playlist into a .zip (default)",
    )
    zip_group.add_argument(
        "--no-zip", dest="zip_output", action="store_false",
        help="do not create ZIP archives",
    )
    parser.add_argument(
        "--zip-method", choices=ZIP_METHODS, default=None,
        help="ZIP compression: stored (fast, default) or deflate",
    )

    parser.add_argument("--cookies", default=None, help="cookies.txt for restricted media")
    parser.add_argument("--limit-rate", default=None, help="download speed limit, e.g. 500k or 1M")
    parser.add_argument(
        "--js-runtime", choices=("auto", "deno", "node", "bun", "quickjs"), default=None,
        help="JavaScript runtime for YouTube extraction (default: auto-detect)",
    )
    parser.add_argument(
        "--remote-components", action="store_true", default=None,
        help="allow yt-dlp's EJS challenge solver from GitHub (better YouTube formats)",
    )
    parser.add_argument(
        "--retries", type=int, default=None,
        help="retries per track (default: 3)",
    )
    parser.add_argument(
        "--number-width", type=int, default=None,
        help="zero-padded playlist prefix width (default: auto, min 4)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", default=None,
        help="re-download tracks even when the output file exists",
    )
    folder_group = parser.add_mutually_exclusive_group()
    folder_group.add_argument(
        "--remove-folder", dest="keep_folder", action="store_false", default=None,
        help="after a successful ZIP, delete the source folder (default)",
    )
    folder_group.add_argument(
        "--keep-folder", dest="keep_folder", action="store_true",
        help="keep the source folder after a successful ZIP",
    )
    parser.add_argument(
        "--fragments", dest="concurrent_fragments", type=int, default=None,
        help="parallel fragments for HLS/DASH downloads (default: 8)",
    )
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="network timeout in seconds (default: 30)",
    )
    ui_group = parser.add_mutually_exclusive_group()
    ui_group.add_argument(
        "--ui", dest="no_ui", action="store_false", default=None,
        help="force the live dashboard even when the output is not a terminal",
    )
    ui_group.add_argument(
        "--no-ui", dest="no_ui", action="store_true",
        help="plain line output (no live dashboard)",
    )
    parser.add_argument("--log", dest="log_file", default=None, help="write a detailed log here")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="resolve URLs and show planned files without downloading",
    )
    parser.add_argument(
        "--config", default=None,
        help="TOML config file (default: ./richmp3.toml or ~/.config/richmp3/config.toml)",
    )
    interaction_group = parser.add_mutually_exclusive_group()
    interaction_group.add_argument(
        "--wizard",
        action="store_true",
        help="choose speech compression and phone download settings interactively",
    )
    interaction_group.add_argument(
        "--settings",
        action="store_true",
        help="change and save default settings without starting a download",
    )
    interaction_group.add_argument(
        "--update",
        action="store_true",
        help="check GitHub and fast-forward this clean checkout",
    )
    parser.add_argument("--version", action="version", version=f"richmp3 {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(highlight=False)

    if args.update:
        from .updater import update_from_github

        result = update_from_github()
        console.print(result.message)
        return 0 if result.ok else 1

    if args.settings:
        from .interactive import save_settings_interactively

        try:
            save_settings_interactively(
                config_path=Path(args.config) if args.config else None,
            )
        except (OSError, ValueError) as exc:
            console.print(f"تعذر حفظ الإعدادات: {exc}")
            return 1
        return 0

    wizard_settings: dict[str, object] = {}
    if args.wizard:
        from .interactive import configure_interactively

        try:
            result = configure_interactively()
        except KeyboardInterrupt:
            console.print("\nتم إلغاء الإعداد.")
            return 130
        except EOFError:
            console.print("\nانتهى الإدخال قبل إدخال الروابط.")
            return 130
        if result is None:
            return 0
        wizard_urls, wizard_settings = result
        args.urls = wizard_urls
    elif not args.urls:
        parser.error("provide at least one URL, or use --wizard")

    try:
        config_file = Path(args.config) if args.config else config_path_default()
        config: dict[str, Any] = {}
        if config_file:
            if not config_file.is_file():
                parser.error(f"config file not found: {config_file}")
            config = load_config(config_file)
        config.update(wizard_settings)
        settings = _build_settings(args, config)
        settings, notices = finalize(settings)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))

    try:
        log = Log(settings.log_file)
    except OSError as exc:
        console.print(Text(f"✗ Cannot write log file: {exc}", style="bold red"))
        return 2
    log.info(f"richmp3 {__version__} starting: {args.urls}")

    for notice in notices:
        console.print(Text(f"! {notice}", style="yellow"))

    if not settings.dry_run:
        _print_banner(console, settings)

    context = UIContext()
    ui = build_ui(console, settings, context)
    pipeline: Pipeline | None = None
    try:
        if not settings.dry_run:
            _require_ffmpeg(console)
        pipeline = Pipeline(settings, log, context, ui)
    except DownloadError as exc:
        console.print(Text(f"✗ {exc}", style="bold red"))
        return 2
    except RuntimeError as exc:
        console.print(Text(f"✗ {exc}", style="bold red"))
        return 2

    try:
        ui.start()
        pipeline.run(args.urls)
    except KeyboardInterrupt:  # second interrupt during cleanup
        pipeline.cancel()
        context.cancelled = True
        console.print()
        console.print(Text("Interrupted.", style="yellow"))
    finally:
        ui.stop()
        if settings.dry_run:
            print_dry_run(console, settings, context)
        else:
            print_summary(console, context, settings)

    if context.cancelled:
        return 130

    failures = any(
        playlist.error
        or playlist.zip_error
        or any(track.stage is Stage.FAILED for track in playlist.tracks)
        for playlist in context.playlists
    )
    if failures or not context.playlists:
        return 1
    return 0


def _require_ffmpeg(console: Console) -> None:
    import shutil

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg was not found on PATH. Install it (Termux: pkg install ffmpeg)"
        )


def _print_banner(console: Console, settings: Settings) -> None:
    line = Text()
    line.append("RichMP3", style="bold cyan")
    line.append(f" {__version__}", style="dim")
    line.append("  ·  ", style="grey50")
    line.append(
        f"{settings.audio_format.upper()} {settings.mode_label} "
        f"{settings.bitrate} kbps  ·  {settings.sample_rate} Hz  ·  mono",
        style="white",
    )
    line.append(f"  ·  {settings.download_workers}↓ {settings.convert_workers}⚙", style="dim")
    console.print(line)


# ---------------------------------------------------------------------------
# Argument/config merging
# ---------------------------------------------------------------------------


def _build_settings(args: argparse.Namespace, config: dict[str, Any]) -> Settings:
    def pick(*values: Any, default: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return default

    cfg = config
    audio_format = str(pick(args.audio_format, cfg.get("format"), default="mp3")).lower()
    if audio_format not in AUDIO_FORMATS:
        raise ValueError(f"format must be one of {', '.join(AUDIO_FORMATS)}")

    mode = str(pick(args.mode, cfg.get("mode"), default="abr")).lower()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")

    zip_method = str(pick(args.zip_method, cfg.get("zip_method"), default="stored")).lower()
    if zip_method not in ZIP_METHODS:
        raise ValueError(f"zip_method must be one of {', '.join(ZIP_METHODS)}")

    settings = Settings(
        output=Path(
            str(pick(args.output, cfg.get("output"), default="downloads"))
        ).expanduser(),
        bitrate=_as_int(pick(args.bitrate, cfg.get("bitrate"), default=24), "bitrate"),
        sample_rate=_as_int(
            pick(
                args.sample_rate,
                cfg.get("sample_rate"),
                default=12000 if audio_format == "opus" else 11025,
            ),
            "sample_rate",
        ),
        audio_format=audio_format,
        mode=mode,
        voice_filter=_as_bool(
            pick(args.voice_filter, cfg.get("voice_filter"), default=True),
            "voice_filter",
        ),
        download_workers=_as_int(
            pick(args.download_workers, cfg.get("download_workers"), default=4), "workers"
        ),
        convert_workers=_as_int(
            pick(args.convert_workers, cfg.get("convert_workers"), default=default_convert_workers()),
            "convert_workers",
        ),
        playlist=_as_bool(pick(args.playlist, cfg.get("playlist"), default=True), "playlist"),
        zip_output=_as_bool(
            pick(args.zip_output, cfg.get("zip"), default=True), "zip"
        ),
        zip_method=zip_method,
        cookies=_as_path(pick(args.cookies, cfg.get("cookies"), default=None)),
        limit_rate=pick(args.limit_rate, cfg.get("limit_rate"), default=None),
        js_runtime=str(pick(args.js_runtime, cfg.get("js_runtime"), default="auto")).lower(),
        remote_components=_as_bool(
            pick(args.remote_components, cfg.get("remote_components"), default=False),
            "remote_components",
        ),
        retries=_as_int(pick(args.retries, cfg.get("retries"), default=3), "retries"),
        number_width=_as_int(
            pick(args.number_width, cfg.get("number_width"), default=0), "number_width"
        ),
        overwrite=_as_bool(
            pick(args.overwrite, cfg.get("overwrite"), default=False), "overwrite"
        ),
        keep_folder=_as_bool(
            pick(args.keep_folder, cfg.get("keep_folder"), default=False), "keep_folder"
        ),
        no_ui=_as_bool(pick(args.no_ui, cfg.get("no_ui"), default=False), "no_ui"),
        force_ui=args.no_ui is False,
        log_file=_as_path(pick(args.log_file, cfg.get("log_file"), default=None)),
        dry_run=bool(args.dry_run),
        timeout=_as_float(pick(args.timeout, cfg.get("timeout"), default=30.0), "timeout"),
        concurrent_fragments=_as_int(
            pick(args.concurrent_fragments, cfg.get("concurrent_fragments"), default=8), "fragments"
        ),
    )
    if settings.limit_rate:
        parse_rate(settings.limit_rate)  # fail fast on malformed values
    if settings.cookies and not settings.cookies.is_file():
        raise ValueError(f"cookies file not found: {settings.cookies}")
    if settings.js_runtime not in (None, "auto", "deno", "node", "bun", "quickjs"):
        raise ValueError(
            "js_runtime must be auto, deno, node, bun or quickjs"
        )
    return settings


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{name} must be true or false in the config file")


def _as_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()
