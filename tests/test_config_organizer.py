from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import os

from richmp3.config import (
    Settings,
    default_output_directory,
    finalize,
    max_mp3_bitrate,
    snap_sample_rate,
)
from richmp3.models import Track
from richmp3.organizer import (
    cleanup_raw,
    mark_skipped,
    number_width,
    output_path_for,
    make_layout,
    prepare_layout,
    should_skip,
    track_filename,
)
from richmp3.models import Stage


class ConfigTests(unittest.TestCase):
    def test_track_stage_progress_is_not_overall_weighted_progress(self) -> None:
        track = Track(
            index=1,
            url="u",
            title="speech",
            stage=Stage.DOWNLOADING,
            download_fraction=1.0,
        )
        self.assertEqual(track.stage_progress, 1.0)
        self.assertEqual(track.progress, 0.62)

        track.stage = Stage.CONVERTING
        track.convert_fraction = 0.03
        self.assertAlmostEqual(track.stage_progress, 0.03)
        self.assertAlmostEqual(track.progress, 0.6299)

    def test_snap_mp3_11000_to_11025(self) -> None:
        self.assertEqual(snap_sample_rate(11000, "mp3"), 11025)

    def test_snap_opus_11025_to_12000(self) -> None:
        self.assertEqual(snap_sample_rate(11025, "opus"), 12000)

    def test_snap_bounds(self) -> None:
        self.assertEqual(snap_sample_rate(100, "mp3"), 8000)
        self.assertEqual(snap_sample_rate(96000, "mp3"), 44100)

    def test_finalize_reports_snapped_rate(self) -> None:
        settings, notices = finalize(Settings(sample_rate=11000))
        self.assertEqual(settings.sample_rate, 11025)
        self.assertTrue(any("11025" in notice for notice in notices))

    def test_mp3_bitrate_ceiling(self) -> None:
        self.assertEqual(max_mp3_bitrate(11025), 64)
        self.assertEqual(max_mp3_bitrate(22050), 160)
        settings, notices = finalize(
            Settings(bitrate=128, sample_rate=11025, mode="abr")
        )
        self.assertEqual(settings.bitrate, 64)
        self.assertTrue(notices)

    def test_finalize_clamps_workers_and_bitrate(self) -> None:
        settings, _ = finalize(
            Settings(
                bitrate=999,
                sample_rate=44100,
                download_workers=0,
                convert_workers=99,
                retries=-2,
            )
        )
        self.assertEqual(settings.bitrate, 128)
        self.assertEqual(settings.download_workers, 1)
        self.assertEqual(settings.convert_workers, 8)
        self.assertEqual(settings.retries, 0)

    def test_extension(self) -> None:
        self.assertEqual(finalize(Settings(audio_format="mp3"))[0].extension, "mp3")
        self.assertEqual(finalize(Settings(audio_format="opus"))[0].extension, "opus")

    def test_mode_label(self) -> None:
        self.assertEqual(Settings().mode_label, "VBR")
        self.assertEqual(Settings().encoding_label, "VBR Q7")
        self.assertEqual(Settings(mode="abr").mode_label, "ABR")
        self.assertEqual(Settings(mode="cbr").mode_label, "CBR")
        self.assertEqual(Settings(audio_format="opus", mode="cbr").mode_label, "VBR")

    def test_vbr_quality_is_clamped(self) -> None:
        settings, notices = finalize(Settings(vbr_quality=12))
        self.assertEqual(settings.vbr_quality, 9)
        self.assertTrue(any("VBR quality" in notice for notice in notices))

    def test_termux_default_uses_android_download_folder(self) -> None:
        with patch.dict(
            os.environ,
            {"PREFIX": "/data/data/com.termux/files/usr", "TERMUX_VERSION": "0.118"},
        ):
            self.assertEqual(
                default_output_directory(),
                Path.home() / "storage" / "shared" / "Download",
            )

    def test_termux_requires_shared_storage_permission_for_default_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {"PREFIX": "/data/data/com.termux/files/usr", "TERMUX_VERSION": "0.118"},
                ),
                patch("richmp3.config.Path.home", return_value=Path(tmp)),
            ):
                with self.assertRaisesRegex(ValueError, "termux-setup-storage"):
                    finalize(Settings())


class OrganizerTests(unittest.TestCase):
    def test_number_width(self) -> None:
        self.assertEqual(number_width(9), 4)
        self.assertEqual(number_width(12000), 5)
        self.assertEqual(number_width(9, configured=3), 3)

    def test_track_filename_sequence(self) -> None:
        settings = Settings()
        track = Track(index=1, url="u", title="عنوان الأغنية")
        name = track_filename(track, total=12, settings=settings)
        self.assertEqual(name, "0001 - عنوان الأغنية.mp3")
        track.index = 10
        self.assertTrue(track_filename(track, total=12, settings=settings).startswith("0010 - "))

    def test_track_filename_explicit_width(self) -> None:
        settings = Settings()
        track = Track(index=7, url="u", title="x")
        self.assertTrue(track_filename(track, total=7, settings=settings, width=2).startswith("07 - "))

    def test_layout_and_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(output=Path(tmp))
            layout = make_layout(settings, "قائمة/تجريبية")
            prepare_layout(layout)
            self.assertTrue(layout.playlist_dir.is_dir())
            self.assertTrue(layout.temp_dir.is_dir())
            track = Track(index=1, url="u", title="Yalla")
            path = output_path_for(track, layout, 1, settings)
            self.assertEqual(path.parent, layout.playlist_dir)
            self.assertTrue(path.name.startswith("0001 - "))

    def test_skip_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.mp3"
            self.assertFalse(should_skip(path, Settings()))
            path.write_bytes(b"")
            self.assertFalse(should_skip(path, Settings()))  # empty is not complete
            path.write_bytes(b"data")
            self.assertTrue(should_skip(path, Settings()))
            self.assertFalse(should_skip(path, Settings(overwrite=True)))

    def test_mark_skipped(self) -> None:
        track = Track(index=1, url="u", title="t")
        path = Path("/tmp/x.mp3")
        mark_skipped(track, path)
        self.assertIs(track.stage, Stage.SKIPPED)
        self.assertEqual(track.progress, 1.0)
        self.assertEqual(track.output_path, path)

    def test_cleanup_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw-0001.webm"
            raw.write_bytes(b"x")
            part = Path(str(raw) + ".part")
            part.write_bytes(b"x")
            ytdl = Path(str(raw) + ".ytdl")
            ytdl.write_bytes(b"x")
            cleanup_raw(raw, 1)
            self.assertFalse(raw.exists())
            self.assertFalse(part.exists())
            self.assertFalse(ytdl.exists())


if __name__ == "__main__":
    unittest.main()
