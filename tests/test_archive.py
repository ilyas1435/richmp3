from __future__ import annotations

import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from richmp3.archive import ArchiveError, Archiver
from richmp3.utils import Cancelled, Log


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "playlist"
        self.root.mkdir()
        (self.root / "0001 - أغنية.mp3").write_bytes(b"a" * 4000)
        (self.root / "0002 - second.mp3").write_bytes(b"b" * 2000)
        self.archiver = Archiver(Log())
        self.progress: list[float] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stored_archive(self) -> None:
        target = Path(self.tmp.name) / "playlist.zip"
        result = self.archiver.create(
            self.root, target, method="stored", on_progress=self.progress.append
        )
        self.assertEqual(result, target)
        self.assertTrue(target.is_file())
        self.assertEqual(self.progress[-1], 1.0)
        self.assertFalse(target.with_name(target.name + ".part").exists())
        with zipfile.ZipFile(target) as archive:
            names = sorted(archive.namelist())
            self.assertEqual(names, ["0001 - أغنية.mp3", "0002 - second.mp3"])
            self.assertEqual(len(archive.read(names[0])), 4000)
            self.assertEqual(archive.getinfo(names[0]).compress_type, zipfile.ZIP_STORED)

    def test_deflate_archive(self) -> None:
        target = Path(self.tmp.name) / "deflate.zip"
        self.archiver.create(self.root, target, method="deflate")
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.getinfo("0002 - second.mp3").compress_type, zipfile.ZIP_DEFLATED)

    def test_cancel_cleans_partial(self) -> None:
        target = Path(self.tmp.name) / "cancel.zip"
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            self.archiver.create(self.root, target, cancel_event=event)
        self.assertFalse(target.exists())

    def test_empty_folder(self) -> None:
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        with self.assertRaises(ArchiveError):
            self.archiver.create(empty, Path(self.tmp.name) / "empty.zip")


if __name__ == "__main__":
    unittest.main()
