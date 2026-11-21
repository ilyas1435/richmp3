"""yt-dlp wrapper: playlist resolution, format choice and downloading."""

from __future__ import annotations

import importlib.util
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .config import Settings
from .models import Playlist, Track
from .utils import Cancelled, Log, parse_rate

ProgressCallback = Callable[[float, int, int | None, float | None, float | None], None]

# Strictly prefer the lowest-bandwidth audio stream.  m4a (AAC) and webm (Opus)
# are tried first because FFmpeg demuxes/decodes them fastest; the
# language_preference filter keeps the original track instead of an AI dub
# (YouTube sets 10 for original, 5 for default, -1 for dubs).  `worst`/`best`
# is only a last resort for sites that expose a single progressive file.
_FORMAT_SELECTOR = (
    "worstaudio[ext=m4a][language_preference>0]/"
    "worstaudio[ext=webm][language_preference>0]/"
    "worstaudio[language_preference>0]/"
    "worstaudio[ext=m4a]/"
    "worstaudio[ext=webm]/"
    "worstaudio/worst/best"
)


class DownloadError(RuntimeError):
    pass


class _YdlLogger:
    """Route yt-dlp chatter into our log instead of the terminal."""

    def __init__(self, log: Log) -> None:
        self.log = log

    def debug(self, message: str) -> None:
        if message.startswith("[debug] "):
            self.log.debug(message[8:])

    def info(self, message: str) -> None:
        self.log.debug(message)

    def warning(self, message: str) -> None:
        self.log.warning(message)

    def error(self, message: str) -> None:
        self.log.error(message)


class Downloader:
    def __init__(self, settings: Settings, log: Log) -> None:
        if importlib.util.find_spec("yt_dlp") is None:
            raise DownloadError(
                "yt-dlp is not installed. Run: python -m pip install yt-dlp"
            )

        self.settings = settings
        self.log = log
        self._ratelimit = parse_rate(settings.limit_rate)

    # -- option helpers -------------------------------------------------------

    def _common_options(self) -> dict:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _YdlLogger(self.log),
            "socket_timeout": self.settings.timeout,
            "retries": self.settings.retries,
            "fragment_retries": self.settings.retries,
            "extractor_retries": 2,
            "concurrent_fragment_downloads": self.settings.concurrent_fragments,
            # Larger read buffer = fewer Python-level write calls on FUSE-backed
            # phone storage, which is where downloads actually bottleneck.
            "buffersize": 1024 * 1024,
            "format_sort": ["lang"],
        }
        if self.settings.cookies:
            options["cookiefile"] = str(self.settings.cookies)
        if self._ratelimit:
            options["ratelimit"] = self._ratelimit
        runtime = self._resolve_js_runtime()
        if runtime:
            options["js_runtimes"] = {runtime: {}}
        if self.settings.remote_components:
            options["remote_components"] = {"ejs:github"}
        return options

    def _resolve_js_runtime(self) -> str | None:
        """Pick an installed JavaScript runtime so YouTube exposes all formats."""
        configured = self.settings.js_runtime
        if not configured:
            return None
        if configured != "auto":
            return configured
        import shutil

        for name in ("deno", "node", "bun", "quickjs"):
            if shutil.which(name):
                return name
        return None

    # -- metadata -------------------------------------------------------------

    @contextmanager
    def open_playlist(self, url: str) -> Iterator[tuple[str, str | None, Iterator[dict], int | None]]:
        """Open a URL and yield playlist metadata without consuming entries.

        With ``extract_flat: in_playlist`` yt-dlp returns a lazy entry list, so
        the caller can start workers on the first track while the rest of the
        playlist metadata is still being produced.  The ``YoutubeDL`` instance
        stays alive for the whole ``with`` block because the lazy entries depend
        on it.
        """
        import yt_dlp

        options = self._common_options()
        options.update(
            {
                "noplaylist": not self.settings.playlist,
                "extract_flat": "in_playlist",
                "skip_download": True,
            }
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except Exception as exc:  # yt-dlp raises a wide variety of errors
                    raise DownloadError(_clean_error(exc)) from exc

                if not info:
                    raise DownloadError("No media information returned for this URL")

                if info.get("_type") in ("playlist", "multi_video"):
                    title = str(info.get("title") or info.get("id") or "Playlist")
                    uploader = info.get("uploader") or info.get("channel")
                    entries = info.get("entries")
                    if entries is None:
                        raise DownloadError("The playlist returned no entries")
                    expected = info.get("n_entries") or info.get("playlist_count")
                    try:
                        expected_int = int(expected) if expected else None
                    except (TypeError, ValueError):
                        expected_int = None
                    self.log.info(
                        f"Streaming playlist '{title}'"
                        + (f" (~{expected_int} tracks)" if expected_int else "")
                    )
                    yield title, uploader, iter(entries), expected_int
                    return

                title = str(info.get("title") or info.get("id") or "audio")
                uploader = info.get("uploader") or info.get("channel")
                self.log.info(f"Resolved single track '{title}'")
                yield title, uploader, iter((info,)), 1
        except (Cancelled, KeyboardInterrupt):
            # Never convert a user interrupt into a download error: the
            # contextmanager re-raises body exceptions at the yield point.
            raise
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(_clean_error(exc)) from exc

    @staticmethod
    def track_from_entry(entry: dict, index: int) -> Track | None:
        """Build a :class:`Track` from a yt-dlp entry, or ``None`` if unusable."""
        if not isinstance(entry, dict):
            return None
        track_url = (
            entry.get("webpage_url")
            or entry.get("original_url")
            or entry.get("url")
        )
        if not track_url:
            return None
        return Track(
            index=index,
            url=track_url,
            title=entry.get("title") or f"Track {index}",
            duration=_as_float(entry.get("duration")),
            uploader=entry.get("uploader") or entry.get("channel"),
        )

    def resolve(self, url: str) -> Playlist:
        """Resolve a URL into a playlist of tracks without downloading media.

        Kept for dry runs and tests; real runs use :meth:`open_playlist` so the
        first track can start before the whole playlist is enumerated.
        """
        with self.open_playlist(url) as (title, uploader, entries, expected):
            tracks: list[Track] = []
            for entry in entries:
                if not entry:
                    continue
                track = self.track_from_entry(entry, len(tracks) + 1)
                if track is None:
                    continue
                tracks.append(track)

        if not tracks:
            raise DownloadError("The playlist contains no downloadable items")
        self.log.info(f"Resolved playlist '{title}' with {len(tracks)} tracks")
        return Playlist(url=url, title=title, uploader=uploader, tracks=tracks)

    # -- downloading ----------------------------------------------------------

    def download(
        self,
        track: Track,
        temp_dir: Path,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        import yt_dlp

        if cancel_event and cancel_event.is_set():
            raise Cancelled()

        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        def hook(data: dict) -> None:
            if cancel_event and cancel_event.is_set():
                raise Cancelled()
            if not on_progress:
                return
            if data.get("status") == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = int(data.get("downloaded_bytes") or 0)
                fraction = (downloaded / total) if total else 0.0
                on_progress(
                    max(0.0, min(1.0, fraction)),
                    downloaded,
                    int(total) if total else None,
                    _as_float(data.get("speed")),
                    _as_float(data.get("eta")),
                )
            elif data.get("status") == "finished":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                on_progress(
                    1.0,
                    int(total or data.get("downloaded_bytes") or 0),
                    int(total) if total else None,
                    None,
                    None,
                )

        options = self._common_options()
        options.update(
            {
                "format": _FORMAT_SELECTOR,
                "outtmpl": str(temp_dir / f"raw-{track.index:04d}.%(ext)s"),
                "noplaylist": True,
                "overwrites": True,
                "continuedl": True,
                "progress_hooks": [hook],
                "ignoreerrors": False,
            }
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(track.url, download=True)
                if not info:
                    raise DownloadError("No media information returned")
                path = _final_path(ydl, info, temp_dir, track.index)
        except Cancelled:
            _remove_partials(temp_dir, track.index)
            raise
        except Exception as exc:
            _remove_partials(temp_dir, track.index)
            raise DownloadError(_clean_error(exc)) from exc

        if cancel_event and cancel_event.is_set():
            path.unlink(missing_ok=True)
            raise Cancelled()

        if not path.is_file() or path.stat().st_size == 0:
            raise DownloadError(f"Downloaded file is missing or empty: {path.name}")

        track.raw_path = path
        track.downloaded_bytes = path.stat().st_size
        self.log.info(f"Downloaded {track.title} ({path.name})")
        return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _final_path(ydl, info: dict, temp_dir: Path, index: int) -> Path:
    requested = info.get("requested_downloads") or []
    for item in requested:
        filepath = item.get("filepath")
        if filepath:
            path = Path(filepath)
            if not path.is_absolute():
                path = Path(ydl.prepare_filename(info))
            if path.is_file():
                return path
    prepared = Path(ydl.prepare_filename(info))
    if prepared.is_file():
        return prepared
    candidates = [
        path
        for path in temp_dir.glob(f"raw-{index:04d}*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise DownloadError("Could not locate the downloaded media file")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _remove_partials(temp_dir: Path, index: int) -> None:
    for path in temp_dir.glob(f"raw-{index:04d}*"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _clean_error(exc: BaseException) -> str:
    message = str(exc)
    prefix = "ERROR: "
    if message.startswith(prefix):
        message = message[len(prefix):]
    return message.strip() or exc.__class__.__name__


def _as_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
