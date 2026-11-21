"""Output directory layout, sequential naming and cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .models import Stage, Track
from .utils import safe_unlink, sanitize_filename


@dataclass(frozen=True)
class Layout:
    """Paths used for one playlist."""

    playlist_dir: Path
    temp_dir: Path
    zip_path: Path


def number_width(total: int, configured: int = 0) -> int:
    """Zero-padding width for sequential prefixes (minimum 4)."""
    if configured:
        return configured
    return max(4, len(str(max(total, 1))))


def track_filename(track: Track, total: int, settings: Settings, width: int | None = None) -> str:
    digits = width if width is not None else number_width(total, settings.number_width)
    title = sanitize_filename(track.title or f"Track {track.index}", max_bytes=170)
    return f"{track.index:0{digits}d} - {title}.{settings.extension}"


def make_layout(settings: Settings, playlist_title: str) -> Layout:
    """Build the playlist folder, a sibling temp folder and zip destination."""
    base = Path(settings.output).expanduser().resolve()
    folder = sanitize_filename(playlist_title or "playlist", max_bytes=120, fallback="playlist")
    playlist_dir = base / folder
    temp_dir = base / f".{folder}.part"
    return Layout(
        playlist_dir=playlist_dir,
        temp_dir=temp_dir,
        zip_path=base / f"{folder}.zip",
    )


def prepare_layout(layout: Layout) -> None:
    layout.playlist_dir.mkdir(parents=True, exist_ok=True)
    layout.temp_dir.mkdir(parents=True, exist_ok=True)


def output_path_for(
    track: Track,
    layout: Layout,
    total: int,
    settings: Settings,
    width: int | None = None,
) -> Path:
    return layout.playlist_dir / track_filename(track, total, settings, width)


def should_skip(path: Path, settings: Settings) -> bool:
    if settings.overwrite:
        return False
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def mark_skipped(track: Track, path: Path) -> None:
    track.output_path = path
    track.stage = Stage.SKIPPED
    track.download_fraction = 1.0
    track.convert_fraction = 1.0
    try:
        track.final_bytes = path.stat().st_size
    except OSError:
        track.final_bytes = 0
    # Unknown source size: count the existing file as both sides so a skipped
    # run never reports fictional savings.
    track.original_bytes = track.final_bytes


def cleanup_raw(raw: Path | None, index: int | None = None) -> None:
    """Delete a raw download plus yt-dlp sidecar/partial files."""
    if not raw:
        return
    raw = Path(raw)
    candidates: list[Path] = [raw]
    if index is not None:
        candidates.extend(raw.parent.glob(f"raw-{index:04d}*"))
    candidates.extend(
        [
            raw.with_suffix(raw.suffix + ".part"),
            raw.with_suffix(raw.suffix + ".ytdl"),
            Path(str(raw) + ".part"),
        ]
    )
    for path in candidates:
        safe_unlink(path)


def cleanup_temp_dir(temp_dir: Path) -> None:
    """Remove the temp folder, including leftover partial files."""
    if not temp_dir.exists():
        return
    for child in temp_dir.iterdir():
        if child.is_dir():
            for nested in child.rglob("*"):
                safe_unlink(nested)
            try:
                child.rmdir()
            except OSError:
                pass
        else:
            safe_unlink(child)
    try:
        temp_dir.rmdir()
    except OSError:
        pass


def remove_folder(folder: Path) -> bool:
    """Delete a finished playlist folder after a successful archive.

    Returns ``True`` when the folder is gone.  Failures are ignored: the ZIP is
    already valid, so leaving a folder behind is better than aborting the run.
    """
    import shutil

    folder = Path(folder)
    try:
        shutil.rmtree(folder)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return not folder.exists()
