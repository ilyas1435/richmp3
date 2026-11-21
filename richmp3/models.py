"""Shared data models for the RichMP3 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Stage(str, Enum):
    """Lifecycle stage of a single track."""

    QUEUED = "Queued"
    FETCHING = "Fetching Metadata"
    DOWNLOADING = "Downloading"
    CONVERTING = "Converting"
    CLEANING = "Cleaning Up"
    ZIPPING = "Zipping"
    COMPLETED = "Completed"
    FAILED = "Failed"
    SKIPPED = "Skipped"
    CANCELLED = "Cancelled"

    @property
    def terminal(self) -> bool:
        return self in _TERMINAL_STAGES


_TERMINAL_STAGES = frozenset(
    {
        Stage.COMPLETED,
        Stage.FAILED,
        Stage.SKIPPED,
        Stage.CANCELLED,
    }
)

# Fraction of the per-track work contributed by each stage.  Used to build a
# truthful overall percentage instead of a coarse "items done" counter.
_START_PROGRESS = {
    Stage.QUEUED: 0.0,
    Stage.FETCHING: 0.02,
    Stage.DOWNLOADING: 0.05,
    Stage.CONVERTING: 0.62,
    Stage.CLEANING: 0.95,
}

_DOWNLOAD_WEIGHT = 0.57
_CONVERT_WEIGHT = 0.33


@dataclass
class Track:
    """One audio item inside a playlist (or a standalone URL)."""

    index: int
    url: str
    title: str
    duration: float | None = None
    uploader: str | None = None

    stage: Stage = Stage.QUEUED
    download_fraction: float = 0.0
    convert_fraction: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    convert_speed: float | None = None
    eta: float | None = None

    original_bytes: int = 0
    final_bytes: int = 0

    attempts: int = 0
    error: str | None = None
    raw_path: Path | None = None
    output_path: Path | None = None

    @property
    def progress(self) -> float:
        """Overall completion of this track, from 0.0 to 1.0."""
        if self.stage in _TERMINAL_STAGES:
            return 1.0
        if self.stage is Stage.DOWNLOADING:
            return _START_PROGRESS[Stage.DOWNLOADING] + _DOWNLOAD_WEIGHT * self.download_fraction
        if self.stage is Stage.CONVERTING:
            return _START_PROGRESS[Stage.CONVERTING] + _CONVERT_WEIGHT * self.convert_fraction
        return _START_PROGRESS.get(self.stage, 0.0)

    @property
    def stage_label(self) -> str:
        label = self.stage.value
        if self.attempts > 1 and not self.stage.terminal:
            label = f"{label} (retry {self.attempts - 1})"
        return label


@dataclass
class Playlist:
    """A resolved playlist (or a single track) plus its output locations."""

    url: str
    title: str = "Resolving..."
    uploader: str | None = None
    tracks: list[Track] = field(default_factory=list)

    directory: Path | None = None
    zip_path: Path | None = None
    stage: Stage = Stage.QUEUED
    zip_fraction: float = 0.0
    folder_removed: bool = False
    error: str | None = None
    zip_error: str | None = None

    @property
    def original_bytes(self) -> int:
        """Total bytes downloaded before conversion (skipped files excluded)."""
        return sum(t.original_bytes for t in self.tracks if t.stage is Stage.COMPLETED)

    @property
    def final_bytes(self) -> int:
        """Total bytes of finished output files."""
        return sum(t.final_bytes for t in self.tracks if t.stage is Stage.COMPLETED)

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_bytes - self.final_bytes)

    @property
    def saved_fraction(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return self.saved_bytes / self.original_bytes

    @property
    def completed(self) -> int:
        return sum(1 for t in self.tracks if t.stage is Stage.COMPLETED)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tracks if t.stage is Stage.FAILED)

    @property
    def skipped(self) -> int:
        return sum(1 for t in self.tracks if t.stage is Stage.SKIPPED)

    @property
    def finished(self) -> int:
        return sum(1 for t in self.tracks if t.stage.terminal)

    @property
    def progress(self) -> float:
        if not self.tracks:
            return 0.0
        return sum(t.progress for t in self.tracks) / len(self.tracks)
