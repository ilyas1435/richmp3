"""Concurrent download -> convert -> clean -> archive orchestrator."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from .archive import Archiver
from .config import Settings
from .converter import Converter
from .downloader import Downloader
from .models import Playlist, Stage, Track
from .organizer import (
    Layout,
    cleanup_raw,
    cleanup_temp_dir,
    make_layout,
    mark_skipped,
    number_width,
    output_path_for,
    prepare_layout,
    remove_folder,
    should_skip,
)
from .ui import BaseUI, UIContext
from .utils import Cancelled, Log


class Pipeline:
    def __init__(self, settings: Settings, log: Log, context: UIContext, ui: BaseUI) -> None:
        self.settings = settings
        self.log = log
        self.context = context
        self.ui = ui

        self.cancel_event = threading.Event()
        self.downloader = Downloader(settings, log)
        self.archiver = Archiver(log)
        self._converter: Converter | None = None

    # -- public API -----------------------------------------------------------

    def run(self, urls: list[str]) -> None:
        self.context.started_at = time.monotonic()
        try:
            for url in urls:
                if self.cancel_event.is_set():
                    break
                try:
                    self._process_url(url)
                except (KeyboardInterrupt, Cancelled):
                    raise
                except Exception as exc:
                    # A bug in one playlist must not abort the remaining URLs.
                    self.log.error(f"Unexpected error for {url}: {exc}")
                    self.ui.notify(f"Unexpected error for {url}: {exc}", "error")
                    if self.context.playlists:
                        playlist = self.context.playlists[-1]
                        playlist.error = playlist.error or str(exc)
                        if not playlist.stage.terminal:
                            playlist.stage = Stage.FAILED
        except KeyboardInterrupt:
            self.cancel_event.set()
            self.context.cancelled = True
            for playlist in self.context.playlists:
                if not playlist.stage.terminal:
                    playlist.stage = Stage.CANCELLED
            self.log.warning("Interrupted by user")
            self.ui.notify("Interrupted — cleaning up safely…", "warning")
        except Cancelled:
            self.context.cancelled = True
        finally:
            self.context.finished = True
            self.ui.refresh()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.context.cancelled = True

    # -- playlist level -------------------------------------------------------

    def _process_url(self, url: str) -> None:
        playlist = Playlist(url=url, title="Resolving…", stage=Stage.FETCHING)
        self.context.playlists.append(playlist)
        self.ui.refresh()
        self.ui.notify(f"Resolving {url}", "info")

        try:
            resolved = self.downloader.resolve(url)
        except Cancelled:
            playlist.stage = Stage.CANCELLED
            raise
        except Exception as exc:
            playlist.stage = Stage.FAILED
            playlist.error = str(exc)
            playlist.title = url
            self.log.error(f"Failed to resolve {url}: {exc}")
            self.ui.notify(f"Could not resolve {url}: {exc}", "error")
            return

        playlist.title = resolved.title
        playlist.uploader = resolved.uploader
        playlist.tracks = resolved.tracks
        playlist.stage = Stage.QUEUED
        self.context.finished = False
        self.ui.refresh()

        if self.settings.dry_run:
            self._plan_only(playlist)
            return

        layout = make_layout(self.settings, playlist.title)
        playlist.directory = layout.playlist_dir
        playlist.zip_path = layout.zip_path
        prepare_layout(layout)

        try:
            self._run_tracks(playlist, layout)
        finally:
            try:
                self._maybe_zip(playlist, layout)
            finally:
                cleanup_temp_dir(layout.temp_dir)
                try:
                    if layout.playlist_dir.is_dir() and not any(layout.playlist_dir.iterdir()):
                        layout.playlist_dir.rmdir()
                except OSError:
                    pass
                if playlist.stage not in (Stage.CANCELLED, Stage.FAILED, Stage.ZIPPING):
                    playlist.stage = Stage.COMPLETED
                self.ui.refresh()

    def _plan_only(self, playlist: Playlist) -> None:
        layout = make_layout(self.settings, playlist.title)
        playlist.directory = layout.playlist_dir
        playlist.zip_path = layout.zip_path
        width = number_width(len(playlist.tracks), self.settings.number_width)
        for track in playlist.tracks:
            track.output_path = output_path_for(
                track, layout, len(playlist.tracks), self.settings, width
            )
        playlist.stage = Stage.COMPLETED

    def _run_tracks(self, playlist: Playlist, layout: Layout) -> None:
        """Run downloads and encodes as two independent worker pools.

        A download worker hands each finished file straight to the encoder pool
        and immediately picks up the next track, so encoding never blocks
        downloading (and vice versa).  Only the final ZIP waits for both pools.
        """
        width = number_width(len(playlist.tracks), self.settings.number_width)
        downloads = ThreadPoolExecutor(
            max_workers=self.settings.download_workers,
            thread_name_prefix="richmp3-dl",
        )
        encodes = ThreadPoolExecutor(
            max_workers=self.settings.convert_workers,
            thread_name_prefix="richmp3-enc",
        )
        download_futures = {
            downloads.submit(self._download_track, track, playlist, layout, width): track
            for track in playlist.tracks
        }
        encode_futures: dict[Future, Track] = {}
        cancelled = False
        try:
            for future in as_completed(download_futures):
                track = download_futures[future]
                try:
                    raw = future.result()
                except Cancelled:
                    cancelled = True
                    continue
                except Exception as exc:  # defensive: _download_track handles errors
                    track.stage = Stage.FAILED
                    track.error = str(exc)
                    self.log.error(f"Unexpected download failure on {track.title}: {exc}")
                    continue
                if raw is not None:
                    encode_futures[
                        encodes.submit(
                            self._encode_track,
                            track,
                            layout,
                            raw,
                            len(playlist.tracks),
                            width,
                        )
                    ] = track

            for future in as_completed(encode_futures):
                track = encode_futures[future]
                try:
                    future.result()
                except Cancelled:
                    cancelled = True
                except Exception as exc:  # defensive: _encode_track handles errors
                    track.stage = Stage.FAILED
                    track.error = str(exc)
                    self.log.error(f"Unexpected encode failure on {track.title}: {exc}")
        except KeyboardInterrupt:
            self.cancel_event.set()
            cancelled = True
            for future in download_futures:
                future.cancel()
            for future in encode_futures:
                future.cancel()
            raise
        finally:
            downloads.shutdown(wait=True, cancel_futures=True)
            encodes.shutdown(wait=True, cancel_futures=True)
            if cancelled or self.cancel_event.is_set():
                for track in playlist.tracks:
                    if not track.stage.terminal:
                        track.stage = Stage.CANCELLED
                playlist.stage = Stage.CANCELLED
                self.context.cancelled = True

    # -- download stage -------------------------------------------------------

    def _download_track(
        self, track: Track, playlist: Playlist, layout: Layout, width: int
    ) -> Path | None:
        """Download one track and hand the raw file to the encoder pool."""
        total = len(playlist.tracks)
        target = output_path_for(track, layout, total, self.settings, width)
        track.output_path = target

        if should_skip(target, self.settings):
            mark_skipped(track, target)
            self.log.info(f"Skipping existing file: {target.name}")
            self.ui.refresh()
            return None

        attempts = self.settings.retries + 1
        for attempt in range(1, attempts + 1):
            if self.cancel_event.is_set():
                track.stage = Stage.CANCELLED
                return None
            track.attempts = attempt
            track.error = None
            track.download_fraction = 0.0
            track.downloaded_bytes = 0
            track.total_bytes = None
            track.speed = None
            track.eta = None
            try:
                track.stage = Stage.FETCHING
                self.ui.refresh()
                raw = self.downloader.download(
                    track,
                    layout.temp_dir,
                    on_progress=self._download_callback(track),
                    cancel_event=self.cancel_event,
                )
                track.original_bytes = raw.stat().st_size
                if self.cancel_event.is_set():
                    raise Cancelled()
                return raw
            except Cancelled:
                track.stage = Stage.CANCELLED
                return None
            except Exception as exc:
                if self.cancel_event.is_set():
                    track.stage = Stage.CANCELLED
                    return None
                track.error = str(exc)
                self.log.warning(
                    f"Download attempt {attempt}/{attempts} failed for {track.title}: {exc}"
                )
                if attempt < attempts:
                    track.stage = Stage.QUEUED
                    self.ui.notify(
                        f"Retrying {track.title} ({attempt}/{attempts - 1}) — {exc}",
                        "warning",
                    )
                    self._wait_before_retry(attempt)
                    continue
                track.stage = Stage.FAILED
                self.ui.notify(f"Failed {track.title}: {exc}", "error")
                self.ui.refresh()
                return None
        return None

    # -- encode stage ---------------------------------------------------------

    def _encode_track(
        self, track: Track, layout: Layout, raw: Path, total: int, width: int
    ) -> None:
        """Convert an already-downloaded file; runs in the encoder pool."""
        target = output_path_for(track, layout, total, self.settings, width)
        track.output_path = target
        attempts = self.settings.retries + 1
        for attempt in range(1, attempts + 1):
            if self.cancel_event.is_set():
                track.stage = Stage.CANCELLED
                cleanup_raw(raw, track.index)
                return

            track.stage = Stage.CONVERTING
            track.convert_fraction = 0.0
            track.convert_speed = None
            track.error = None
            self.ui.refresh()
            try:
                self.converter.convert(
                    raw,
                    target,
                    track.duration,
                    on_progress=self._convert_callback(track),
                    cancel_event=self.cancel_event,
                )
                track.final_bytes = target.stat().st_size

                track.stage = Stage.CLEANING
                self.ui.refresh()
                cleanup_raw(raw, track.index)
                track.stage = Stage.COMPLETED
                self.log.info(f"Completed {target.name}")
                self.ui.notify(f"Completed {track.title}", "success")
                return
            except Cancelled:
                track.stage = Stage.CANCELLED
                cleanup_raw(raw, track.index)
                return
            except Exception as exc:
                if self.cancel_event.is_set():
                    track.stage = Stage.CANCELLED
                    cleanup_raw(raw, track.index)
                    return
                track.error = str(exc)
                self.log.warning(
                    f"Encode attempt {attempt}/{attempts} failed for {track.title}: {exc}"
                )
                if attempt < attempts:
                    self.ui.notify(
                        f"Retrying encode {track.title} ({attempt}/{attempts - 1}) — {exc}",
                        "warning",
                    )
                    self._wait_before_retry(attempt)
                    continue
                cleanup_raw(raw, track.index)
                track.stage = Stage.FAILED
                self.ui.notify(f"Failed {track.title}: {exc}", "error")
                self.ui.refresh()
                return

    def _wait_before_retry(self, attempt: int) -> None:
        deadline = time.monotonic() + min(10.0, 2.0 ** (attempt - 1))
        while time.monotonic() < deadline:
            if self.cancel_event.is_set():
                raise Cancelled()
            time.sleep(0.2)

    # -- callbacks ------------------------------------------------------------

    def _download_callback(self, track: Track):
        def callback(
            fraction: float,
            downloaded: int,
            total: int | None,
            speed: float | None,
            eta: float | None,
        ) -> None:
            if track.stage in (Stage.QUEUED, Stage.FETCHING):
                track.stage = Stage.DOWNLOADING
            track.download_fraction = max(track.download_fraction, fraction)
            track.downloaded_bytes = downloaded
            if total:
                track.total_bytes = total
            track.speed = speed
            track.eta = eta

        return callback

    def _convert_callback(self, track: Track):
        def callback(fraction: float | None, speed: float | None) -> None:
            if fraction is not None:
                track.convert_fraction = max(track.convert_fraction, fraction)
            if speed is not None:
                track.convert_speed = speed

        return callback

    # -- archive --------------------------------------------------------------

    def _maybe_zip(self, playlist: Playlist, layout: Layout) -> bool:
        """Create the archive and, on success, drop the source folder.

        Returns ``True`` only when a ZIP was written and verified.
        """
        if self.settings.dry_run or not self.settings.zip_output:
            return False
        if self.cancel_event.is_set():
            return False
        available = playlist.completed + playlist.skipped
        if not available:
            self.log.info(f"Nothing to archive for {playlist.title}")
            return False
        if not layout.playlist_dir.is_dir() or not any(layout.playlist_dir.iterdir()):
            return False

        playlist.stage = Stage.ZIPPING
        playlist.zip_fraction = 0.0
        self.ui.notify(f"Archiving {playlist.title}…", "info")
        self.ui.refresh()
        try:
            self.archiver.create(
                layout.playlist_dir,
                layout.zip_path,
                method=self.settings.zip_method,
                on_progress=self._zip_callback(playlist),
                cancel_event=self.cancel_event,
            )
        except Cancelled:
            playlist.stage = Stage.CANCELLED
            self.context.cancelled = True
            return False
        except Exception as exc:
            playlist.zip_error = str(exc)
            playlist.stage = Stage.COMPLETED
            self.log.error(f"Archive failed for {playlist.title}: {exc}")
            self.ui.notify(f"Archive failed: {exc}", "error")
            return False

        playlist.stage = Stage.COMPLETED
        if self.settings.keep_folder:
            self.ui.notify(f"Archive ready: {layout.zip_path.name}", "success")
            return True

        # ZIP is safely on disk: remove the duplicate source tree.
        if remove_folder(layout.playlist_dir):
            playlist.folder_removed = True
            self.log.info(f"Removed source folder {layout.playlist_dir}")
            self.ui.notify(
                f"Archive ready: {layout.zip_path.name} · source folder removed",
                "success",
            )
        else:
            self.ui.notify(
                f"Archive ready: {layout.zip_path.name} · could not remove source folder",
                "warning",
            )
        return True

    def _zip_callback(self, playlist: Playlist):
        def callback(fraction: float) -> None:
            playlist.zip_fraction = fraction

        return callback

    # -- lazy converter -------------------------------------------------------

    @property
    def converter(self) -> Converter:
        if self._converter is None:
            self._converter = Converter(self.settings, self.log)
        return self._converter
