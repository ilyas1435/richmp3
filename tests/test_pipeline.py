from __future__ import annotations

import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console
import io

from richmp3.config import Settings, finalize
from richmp3.downloader import DownloadError
from richmp3.models import Playlist, Stage, Track
from richmp3.organizer import make_layout
from richmp3.pipeline import Pipeline
from richmp3.ui import PlainUI, UIContext
from richmp3.utils import Cancelled, Log


class FakeDownloader:
    """Deterministic stand-in that writes a small raw file."""

    def __init__(self, fail_first: dict[int, int] | None = None) -> None:
        self.calls: dict[int, int] = {}
        self.fail_first = dict(fail_first or {})
        self.lock = threading.Lock()
        self.cancel_on: int | None = None

    def resolve(self, url: str) -> Playlist:
        titles = ["أغنية عربية", "Second track", "Third track"]
        return Playlist(
            url=url,
            title="قائمة الاختبار",
            tracks=[
                Track(index=i + 1, url=f"{url}/{i + 1}", title=title, duration=3.0)
                for i, title in enumerate(titles)
            ],
        )

    def download(self, track, temp_dir, on_progress=None, cancel_event=None):
        with self.lock:
            self.calls[track.index] = self.calls.get(track.index, 0) + 1
            attempt = self.calls[track.index]

        if self.fail_first.get(track.index, 0) >= attempt:
            raise DownloadError("simulated network failure")

        path = Path(temp_dir) / f"raw-{track.index:04d}.wav"
        path.write_bytes(b"raw-bytes" * 100)
        if on_progress:
            on_progress(0.5, 64, 128, 1024.0, 1.0)
            on_progress(1.0, 128, 128, None, None)

        if self.cancel_on == track.index and cancel_event is not None:
            cancel_event.set()
            raise Cancelled()
        return path


class FakeConverter:
    def convert(self, src, dst, duration, on_progress=None, cancel_event=None):
        if on_progress:
            on_progress(0.5, 2.0)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        payload = Path(src).read_bytes()
        Path(dst).write_bytes(payload[: max(1, len(payload) // 3)])
        if on_progress:
            on_progress(1.0, None)
        return dst


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.console = Console(file=io.StringIO(), width=100)
        settings, _ = finalize(
            Settings(
                output=self.root / "out",
                download_workers=2,
                convert_workers=1,
                retries=0,
                zip_output=True,
                keep_folder=True,
            )
        )
        self.settings = settings
        self.context = UIContext()
        self.pipeline = Pipeline(settings, Log(), self.context, PlainUI(self.console))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install(self, downloader: FakeDownloader) -> FakeDownloader:
        self.pipeline.downloader = downloader
        self.pipeline._converter = FakeConverter()
        return downloader

    def test_full_run_produces_numbered_files_and_zip(self) -> None:
        self._install(FakeDownloader())
        self.pipeline.run(["fake://playlist"])

        playlist = self.context.playlists[0]
        self.assertEqual(playlist.title, "قائمة الاختبار")
        self.assertEqual(playlist.completed, 3)
        self.assertEqual(playlist.failed, 0)
        self.assertIs(playlist.stage, Stage.COMPLETED)

        outputs = sorted(playlist.directory.iterdir())
        self.assertEqual(len(outputs), 3)
        self.assertEqual(outputs[0].name, "0001 - أغنية عربية.mp3")
        self.assertEqual(outputs[1].name, "0002 - Second track.mp3")
        for output in outputs:
            self.assertGreater(output.stat().st_size, 0)

        self.assertTrue(playlist.zip_path.is_file())
        with zipfile.ZipFile(playlist.zip_path) as archive:
            self.assertEqual(len(archive.namelist()), 3)

        layout = make_layout(self.settings, playlist.title)
        self.assertFalse(layout.temp_dir.exists())
        self.assertFalse(playlist.folder_removed)
        self.assertTrue(self.context.finished)

        # Savings accounting: raw downloads are larger than the MP3s.
        self.assertEqual(playlist.original_bytes, 3 * len(b"raw-bytes" * 100))
        self.assertGreater(playlist.final_bytes, 0)
        self.assertLess(playlist.final_bytes, playlist.original_bytes)
        self.assertEqual(playlist.saved_bytes, playlist.original_bytes - playlist.final_bytes)
        self.assertGreater(playlist.saved_fraction, 0.0)

    def test_zip_deletes_source_folder_by_default(self) -> None:
        self.pipeline.settings = self.settings.with_overrides(keep_folder=False)
        self._install(FakeDownloader())
        self.pipeline.run(["fake://playlist"])

        playlist = self.context.playlists[0]
        self.assertIs(playlist.stage, Stage.COMPLETED)
        self.assertTrue(playlist.folder_removed)
        self.assertFalse(playlist.directory.exists())
        self.assertTrue(playlist.zip_path.is_file())
        with zipfile.ZipFile(playlist.zip_path) as archive:
            self.assertEqual(len(archive.namelist()), 3)
        layout = make_layout(self.pipeline.settings, playlist.title)
        self.assertFalse(layout.temp_dir.exists())

    def test_one_failure_does_not_stop_the_playlist(self) -> None:
        self._install(FakeDownloader(fail_first={2: 5}))
        self.pipeline.run(["fake://playlist"])

        playlist = self.context.playlists[0]
        self.assertEqual(playlist.completed, 2)
        self.assertEqual(playlist.failed, 1)
        self.assertTrue(playlist.zip_path.is_file())
        with zipfile.ZipFile(playlist.zip_path) as archive:
            self.assertEqual(len(archive.namelist()), 2)
        self.assertIs(playlist.tracks[1].stage, Stage.FAILED)
        self.assertIn("simulated", playlist.tracks[1].error or "")

    def test_retry_recovers(self) -> None:
        self.settings = self.settings.with_overrides(retries=1)
        self.pipeline.settings = self.settings
        downloader = self._install(FakeDownloader(fail_first={2: 1}))
        self.pipeline.run(["fake://playlist"])

        playlist = self.context.playlists[0]
        self.assertEqual(playlist.completed, 3)
        self.assertEqual(playlist.tracks[1].attempts, 2)
        self.assertEqual(downloader.calls[2], 2)

    def test_encoding_starts_while_later_downloads_run(self) -> None:
        """Producer/consumer proof: track 1 encodes while track 2 still downloads."""
        second_started = threading.Event()
        release_second = threading.Event()
        encoded_first = threading.Event()

        class BlockingDownloader(FakeDownloader):
            def download(self, track, temp_dir, on_progress=None, cancel_event=None):
                if track.index == 2:
                    second_started.set()
                    if not release_second.wait(10):
                        raise DownloadError("test timeout")
                return super().download(track, temp_dir, on_progress, cancel_event)

        class ObservingConverter(FakeConverter):
            def convert(self, src, dst, duration, on_progress=None, cancel_event=None):
                result = super().convert(src, dst, duration, on_progress, cancel_event)
                if Path(src).name == "raw-0001.wav":
                    encoded_first.set()
                return result

        # One download worker: track 2 cannot start until track 1 is handed off.
        self.pipeline.settings = self.settings.with_overrides(
            download_workers=1, convert_workers=1
        )
        self.pipeline.downloader = BlockingDownloader()
        self.pipeline._converter = ObservingConverter()

        worker = threading.Thread(target=self.pipeline.run, args=(["fake://playlist"],))
        worker.start()
        try:
            self.assertTrue(
                encoded_first.wait(10),
                "encode did not start while a later download was still running",
            )
            self.assertTrue(second_started.is_set())
        finally:
            release_second.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())

    def test_cancel_stops_cleanly(self) -> None:
        downloader = self._install(FakeDownloader())
        downloader.cancel_on = 1
        self.pipeline.run(["fake://playlist"])

        self.assertTrue(self.context.cancelled)
        playlist = self.context.playlists[0]
        self.assertIs(playlist.stage, Stage.CANCELLED)
        self.assertFalse(playlist.zip_path.exists())
        layout = make_layout(self.settings, playlist.title)
        self.assertFalse(layout.temp_dir.exists())

    def test_resolve_failure_is_reported(self) -> None:
        class Broken(FakeDownloader):
            def resolve(self, url: str) -> Playlist:
                raise DownloadError("video unavailable")

        self._install(Broken())
        self.pipeline.run(["fake://missing"])
        playlist = self.context.playlists[0]
        self.assertIs(playlist.stage, Stage.FAILED)
        self.assertIn("video unavailable", playlist.error or "")


if __name__ == "__main__":
    unittest.main()
