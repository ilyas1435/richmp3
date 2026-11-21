"""Rich terminal UI: live dashboard, plain fallback and final summary."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import Settings
from .models import Playlist, Stage, Track
from .utils import format_bytes, format_duration, format_eta, format_speed, shorten

# A deliberately small, high-contrast palette: cyan for motion, magenta for
# encoding, green for success, amber for cleanup/archive.
STAGE_STYLES = {
    Stage.QUEUED: "grey54",
    Stage.FETCHING: "bright_blue",
    Stage.DOWNLOADING: "bright_cyan",
    Stage.CONVERTING: "bright_magenta",
    Stage.CLEANING: "gold1",
    Stage.ZIPPING: "gold1",
    Stage.COMPLETED: "bright_green",
    Stage.FAILED: "bold bright_red",
    Stage.SKIPPED: "grey58",
    Stage.CANCELLED: "bright_yellow",
}

_MESSAGE_STYLES = {
    "info": "grey62",
    "warning": "bright_yellow",
    "error": "bright_red",
    "success": "bright_green",
}

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_BAR_FULL = "━"
_BAR_EMPTY = "─"


@dataclass
class UIContext:
    """Mutable state shared between the pipeline and the dashboard."""

    playlists: list[Playlist] = field(default_factory=list)
    messages: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=5))
    started_at: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    finished: bool = False


class BaseUI:
    def start(self) -> None:  # pragma: no cover - trivial
        pass

    def stop(self) -> None:  # pragma: no cover - trivial
        pass

    def refresh(self) -> None:  # pragma: no cover - trivial
        pass

    def notify(self, message: str, level: str = "info") -> None:  # pragma: no cover
        pass


class PlainUI(BaseUI):
    """Line-oriented output for pipes, CI and ``--no-ui``."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def notify(self, message: str, level: str = "info") -> None:
        style = {
            "info": "grey70",
            "warning": "bright_yellow",
            "error": "bright_red",
            "success": "bright_green",
        }.get(level, "grey70")
        self.console.print(message, style=style, highlight=False, markup=False)


def build_ui(console: Console, settings: Settings, context: UIContext) -> BaseUI:
    if settings.no_ui or (not console.is_terminal and not settings.force_ui):
        return PlainUI(console)
    return Dashboard(console, settings, context)


class Dashboard(BaseUI):
    def __init__(self, console: Console, settings: Settings, context: UIContext) -> None:
        self.console = console
        self.settings = settings
        self.context = context
        self._live: Live | None = None
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._render_lock = threading.Lock()
        self._frame = 0

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=8,
            auto_refresh=False,
            transient=False,
        )
        self._live.start(refresh=True)
        self._thread = threading.Thread(target=self._tick, name="ui-ticker", daemon=True)
        self._thread.start()

    def _tick(self) -> None:
        while not self._halt.wait(0.15):
            self._frame += 1
            self.refresh()

    def refresh(self) -> None:
        if not self._live:
            return
        try:
            with self._render_lock:
                self._live.update(self._render(), refresh=True)
        except Exception:  # never let rendering take the run down
            pass

    def stop(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        if self._live:
            try:
                with self._render_lock:
                    self._live.update(self._render())
                    self._live.stop()
            except Exception:
                pass
            self._live = None

    def notify(self, message: str, level: str = "info") -> None:
        with self._lock:
            self.context.messages.append((level, message))

    # -- aggregate maths ------------------------------------------------------

    def _all_tracks(self) -> list[Track]:
        return [track for playlist in self.context.playlists for track in playlist.tracks]

    def _overall(self) -> float:
        tracks = self._all_tracks()
        if not tracks:
            return 0.0
        return sum(track.progress for track in tracks) / len(tracks)

    def _eta(self, overall: float) -> float | None:
        elapsed = time.monotonic() - self.context.started_at
        if overall <= 0.02 or elapsed <= 1:
            return None
        return elapsed * (1.0 - overall) / overall

    # -- rendering ------------------------------------------------------------

    def _render(self) -> RenderableType:
        settings = self.settings
        tracks = self._all_tracks()
        overall = self._overall()
        elapsed = time.monotonic() - self.context.started_at
        eta = None if self.context.finished else self._eta(overall)
        current = self.context.playlists[-1] if self.context.playlists else None
        narrow = self.console.width < 74
        spinner = _SPINNER[self._frame % len(_SPINNER)]

        completed = sum(1 for t in tracks if t.stage is Stage.COMPLETED)
        failed = sum(1 for t in tracks if t.stage is Stage.FAILED)
        active = [track for track in tracks if not track.stage.terminal]

        # Header ------------------------------------------------------------
        header = Text(no_wrap=True, overflow="ellipsis")
        header.append("◆ ", style="bright_cyan")
        header.append("RichMP3", style="bold bright_cyan")
        if current:
            header.append("  ", style="grey50")
            header.append(
                shorten(current.title, max(12, self.console.width - 40)),
                style="bold bright_white",
            )
        else:
            header.append("  starting", style="dim")

        # Configuration strip ----------------------------------------------
        config = Text(no_wrap=True, overflow="ellipsis")
        config.append(settings.audio_format.upper(), style="bold bright_yellow")
        config.append(f" {settings.mode_label} ", style="bright_magenta")
        config.append(f"{settings.bitrate}k", style="bright_white")
        config.append(" · ", style="grey42")
        config.append(f"{settings.sample_rate} Hz", style="bright_white")
        config.append(" · mono", style="grey62")
        config.append(" · ", style="grey42")
        config.append(f"{settings.download_workers}↓", style="bright_cyan")
        config.append(f" {settings.convert_workers}⚙", style="bright_magenta")
        if not narrow:
            config.append(f" · {settings.concurrent_fragments} frag", style="grey54")

        # Overall progress ---------------------------------------------------
        bar_row = Text(no_wrap=True)
        bar_row.append("Overall ", style="bold bright_white")
        bar_row.append_text(_bar(overall, 24 if not narrow else 14, "bright_cyan"))
        bar_row.append(
            f" {overall * 100:5.1f}%",
            style="bold bright_green" if overall >= 0.9999 else "bold bright_white",
        )
        bar_row.append(
            f"   {sum(1 for t in tracks if t.stage.terminal)}/{len(tracks)}",
            style="grey62",
        )
        if tracks and not narrow:
            bar_row.append(
                f" · {completed} done"
                + (f" · {failed} failed" if failed else "")
                + (f" · {len(active)} active" if active else ""),
                style="grey54",
            )

        # Track table --------------------------------------------------------
        table = Table(
            box=None,
            show_header=not narrow,
            expand=True,
            pad_edge=False,
            padding=(0, 1, 0, 0),
            header_style="bold grey50",
        )
        table.add_column("#", width=4, no_wrap=True, justify="right")
        table.add_column("TITLE", ratio=1, no_wrap=True, overflow="ellipsis")
        table.add_column("STAGE", width=17 if not narrow else 13, no_wrap=True)
        if not narrow:
            table.add_column("PROGRESS", width=14, no_wrap=True)
        table.add_column("%", width=5, justify="right", no_wrap=True)
        if not narrow:
            table.add_column("DETAIL", width=23, no_wrap=True)

        budget = max(3, min(16, self.console.height - 12))
        visible = active[:budget]
        for offset, track in enumerate(visible):
            table.add_row(*self._row(track, spinner if offset == 0 else " "))

        if len(active) > budget:
            filler = [""] * (1 if not narrow else 0)
            table.add_row(
                Text("…", style="grey54"),
                Text(f"{len(active) - budget} more queued", style="grey54 italic"),
                *filler,
            )
        if not active:
            if current and current.stage is Stage.ZIPPING:
                table.add_row(
                    Text("ZIP", style="bold gold1"),
                    Text(
                        shorten(current.zip_path.name if current.zip_path else "archive", 40),
                        style="gold1",
                    ),
                    Text("Zipping", style="bold gold1"),
                    *([""] * (3 if not narrow else 1)),
                )
            elif self.context.finished:
                if failed:
                    table.add_row(
                        Text("!", style="bright_red"),
                        Text(f"Finished with {failed} failed item(s)", style="bright_red"),
                        *([""] * (4 if not narrow else 2)),
                    )
                else:
                    table.add_row(
                        Text("✓", style="bright_green"),
                        Text("All work finished", style="bold bright_green"),
                        *([""] * (4 if not narrow else 2)),
                    )
            else:
                table.add_row(
                    Text("…", style="grey54"),
                    Text("Waiting…", style="grey54"),
                    *([""] * (4 if not narrow else 2)),
                )

        # Footer -------------------------------------------------------------
        status = Text(no_wrap=True, overflow="ellipsis")
        if self.context.cancelled:
            status.append("Cancelling…", style="bold bright_yellow")
        else:
            status.append(f"{spinner} ", style="bright_cyan")
            status.append(f"Elapsed {format_duration(elapsed)}", style="grey70")
            status.append(f"  ·  ETA {format_eta(eta)}", style="grey70")
            if failed:
                status.append(f"  ·  {failed} failed", style="bright_red")
            if current and current.stage is Stage.ZIPPING:
                status.append("  ·  Zipping ", style="gold1")
                status.append_text(_bar(current.zip_fraction, 10, "gold1"))
                status.append(f" {current.zip_fraction * 100:.0f}%", style="gold1")

        message = Text(no_wrap=True, overflow="ellipsis")
        if self.context.messages:
            level, text = self.context.messages[-1]
            style = _MESSAGE_STYLES.get(level, "grey62")
            message.append(shorten(text, max(8, self.console.width - 2)), style=style)

        return Group(
            header,
            config,
            Text(""),
            bar_row,
            Text(""),
            table,
            Text(""),
            status,
            message if self.context.messages else Text(""),
        )

    def _row(self, track: Track, spinner: str) -> list[RenderableType]:
        width = self.console.width
        narrow = width < 74
        style = STAGE_STYLES.get(track.stage, "bright_white")

        idx = Text(f"{spinner}{track.index:03d}", style="grey46")
        reserved = 32 if narrow else 74
        title_style = "bright_white"
        if track.stage is Stage.COMPLETED:
            title_style = "green"
        elif track.stage is Stage.FAILED:
            title_style = "bright_red"
        elif track.stage is Stage.SKIPPED:
            title_style = "grey58"
        title = Text(
            shorten(track.title, max(8, width - reserved)),
            style=title_style,
            no_wrap=True,
        )

        stage = Text(track.stage_label, style=f"bold {style}", no_wrap=True)
        percent = Text(
            f"{track.stage_progress * 100:3.0f}%", style=style, justify="right"
        )

        if narrow:
            return [idx, title, stage, percent]
        detail = Text(self._detail(track), style="grey54", no_wrap=True)
        return [idx, title, stage, _bar(track.stage_progress, 12, style), percent, detail]

    def _detail(self, track: Track) -> str:
        if track.stage is Stage.DOWNLOADING:
            total = format_bytes(track.total_bytes) if track.total_bytes else "?"
            done = format_bytes(track.downloaded_bytes)
            speed = format_speed(track.speed)
            return f"{done}/{total} {speed}".strip()
        if track.stage is Stage.CONVERTING:
            if track.convert_speed:
                return f"{track.convert_speed:.1f}x encode"
            return "encoding…"
        if track.stage is Stage.FAILED:
            return shorten(track.error or "error", 40)
        if track.stage is Stage.CLEANING:
            return "removing raw file"
        if track.stage is Stage.COMPLETED:
            return format_bytes(track.final_bytes) if track.final_bytes else "saved"
        if track.stage is Stage.SKIPPED:
            return "already exists"
        return format_duration(track.duration) if track.duration else ""


def _bar(fraction: float, width: int = 20, style: str = "bright_cyan") -> Text:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    bar = Text()
    bar.append(_BAR_FULL * filled, style=style)
    bar.append(_BAR_EMPTY * (width - filled), style="grey30")
    return bar


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------


def _mb(value: int | float) -> str:
    return f"{float(value) / (1024 * 1024):.2f} MB"


def _minutes(seconds: float) -> str:
    return f"{max(0.0, seconds) / 60.0:.1f} min"


def print_summary(console: Console, context: UIContext, settings: Settings) -> None:
    console.print()

    original = sum(playlist.original_bytes for playlist in context.playlists)
    final = sum(playlist.final_bytes for playlist in context.playlists)
    saved = max(0, original - final)
    percent = (saved / original * 100.0) if original > 0 else 0.0
    elapsed = max(0.0, time.monotonic() - context.started_at)
    finished = sum(
        1
        for playlist in context.playlists
        for track in playlist.tracks
        if track.stage in (Stage.COMPLETED, Stage.SKIPPED)
    )
    total = sum(len(playlist.tracks) for playlist in context.playlists)

    # Headline numbers ------------------------------------------------------
    stats = Table.grid(expand=True, padding=(0, 2))
    stats.add_column(ratio=1)
    stats.add_column(ratio=1)
    stats.add_column(ratio=1)
    stats.add_column(ratio=1)

    stats.add_row(
        Text("Original", style="grey54"),
        Text("Final", style="grey54"),
        Text("Saved", style="grey54"),
        Text("Elapsed", style="grey54"),
    )
    stats.add_row(
        Text(_mb(original), style="bright_white"),
        Text(_mb(final), style="bold bright_cyan"),
        Text(f"{_mb(saved)} ({percent:.1f}%)", style="bold bright_green"),
        Text(_minutes(elapsed), style="bold bright_yellow"),
    )

    subtitle = Text(
        f"{finished}/{total} files ready"
        + (f" · {total - finished} not converted" if total > finished else ""),
        style="grey58",
    )
    console.print(
        Panel(
            Group(stats, Text(""), subtitle),
            title="[bold bright_cyan]Run summary[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        )
    )

    # Per-playlist detail ---------------------------------------------------
    table = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold grey62",
        expand=False,
        pad_edge=False,
        padding=(0, 1, 0, 0),
    )
    table.add_column("Playlist", style="bright_white", overflow="fold")
    table.add_column("Done", justify="right", style="bright_green")
    table.add_column("Skipped", justify="right", style="grey58")
    table.add_column("Failed", justify="right", style="bright_red")
    table.add_column("Output", style="grey62", overflow="fold")

    for playlist in context.playlists:
        destination = Text()
        if playlist.directory and playlist.directory.exists():
            destination.append(str(playlist.directory), style="grey62")
        if playlist.zip_path and playlist.zip_path.exists():
            if destination.plain:
                destination.append("\n")
            destination.append(str(playlist.zip_path), style="bright_cyan")
        if playlist.folder_removed:
            if destination.plain:
                destination.append("\n")
            destination.append("source folder removed", style="bright_green")
        if not destination.plain:
            destination.append("—", style="grey54")
        if playlist.error:
            destination = Text(shorten(playlist.error, 80), style="bright_red")
        elif playlist.zip_error:
            destination.append(f"\nzip: {shorten(playlist.zip_error, 60)}", style="bright_red")
        table.add_row(
            Text(playlist.title),
            str(playlist.completed),
            str(playlist.skipped),
            str(playlist.failed) if playlist.failed else "0",
            destination,
        )
    console.print(table)

    failures = [
        (playlist.title, track)
        for playlist in context.playlists
        for track in playlist.tracks
        if track.stage is Stage.FAILED
    ]
    if failures:
        console.print(Text("Failed items", style="bold bright_red"))
        for _playlist_title, track in failures:
            line = Text("  ✗ ", style="bright_red")
            line.append(shorten(track.title, 60), style="bright_white")
            line.append(f"  ({shorten(track.error or 'unknown error', 70)})", style="grey58")
            console.print(line)
            console.print(Text(f"    {track.url}", style="grey46"))

    if context.cancelled:
        console.print(Text("Run cancelled — completed files were kept.", style="bright_yellow"))
    elif failures:
        console.print(Text(f"Finished with {len(failures)} failure(s).", style="bright_yellow"))
    else:
        console.print(Text("All done.", style="bold bright_green"))


def print_dry_run(console: Console, settings: Settings, context: UIContext) -> None:
    """Show exactly what a real run would create, touching nothing."""
    console.print()
    table = Table(
        title="Dry run — planned output",
        box=box.ROUNDED,
        title_style="bold bright_cyan",
        header_style="bold grey62",
        border_style="grey42",
        expand=True,
    )
    table.add_column("#", justify="right", width=5, style="grey54")
    table.add_column("Title", ratio=1, overflow="fold", style="bright_white")
    table.add_column("Planned file", ratio=1, overflow="fold", style="bright_cyan")
    table.add_column("Length", justify="right", style="grey54")

    for playlist in context.playlists:
        if playlist.error:
            console.print(Text(f"✗ {playlist.title}: {playlist.error}", style="bright_red"))
            continue
        table.add_row(
            Text(""),
            Text(playlist.title, style="bold bright_white"),
            Text(str(playlist.directory or ""), style="grey54"),
            Text(""),
        )
        for track in playlist.tracks:
            table.add_row(
                str(track.index),
                Text(track.title, style="bright_white"),
                Text(track.output_path.name if track.output_path else "—"),
                Text(format_duration(track.duration)),
            )
    console.print(table)
    console.print(
        Text(
            f"{settings.audio_format.upper()} · {settings.mode_label} "
            f"{settings.bitrate} kbps · {settings.sample_rate} Hz · mono · "
            f"zip {settings.zip_method if settings.zip_output else 'off'}"
            f" · folder {'kept' if settings.keep_folder else 'removed after zip'}",
            style="grey58",
        )
    )
