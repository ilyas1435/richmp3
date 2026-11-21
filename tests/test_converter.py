from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from richmp3.config import Settings, finalize
from richmp3.converter import ConversionError, Converter
from richmp3.utils import Log, format_speed


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class CommandTests(unittest.TestCase):
    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def setUp(self) -> None:
        self.converter = Converter(Settings(), Log())

    def test_mp3_abr_command(self) -> None:
        cmd = self.converter.build_command(Path("in.webm"), Path("out.mp3.part"))
        joined = " ".join(cmd)
        self.assertIn("libmp3lame", joined)
        self.assertIn("-ac 1", joined)
        self.assertIn("-ar 11025", joined)
        self.assertIn("-b:a 24k", joined)
        self.assertIn("-abr 1", joined)
        self.assertIn("-compression_level 5", joined)
        self.assertIn("-af highpass=f=100,lowpass=f=5000", joined)
        self.assertEqual(cmd[-1], "out.mp3.part")

    def test_voice_filter_can_be_disabled(self) -> None:
        settings, _ = finalize(Settings(voice_filter=False))
        converter = Converter(settings, Log())
        self.assertNotIn("-af", converter.build_command(Path("a"), Path("b")))

    def test_voice_filter_skipped_for_music_rates(self) -> None:
        settings, _ = finalize(Settings(sample_rate=22050))
        converter = Converter(settings, Log())
        self.assertNotIn("-af", converter.build_command(Path("a"), Path("b")))

    def test_mp3_cbr_has_no_abr_flag(self) -> None:
        settings, _ = finalize(Settings(mode="cbr"))
        converter = Converter(settings, Log())
        self.assertNotIn("-abr", converter.build_command(Path("a"), Path("b")))

    def test_opus_command(self) -> None:
        settings, _ = finalize(Settings(audio_format="opus", bitrate=24))
        converter = Converter(settings, Log())
        cmd = converter.build_command(Path("a"), Path("b.opus.part"))
        joined = " ".join(cmd)
        self.assertIn("libopus", joined)
        self.assertIn("-ar 12000", joined)
        self.assertIn("-f ogg", joined)
        self.assertIn("-vbr on", joined)
        self.assertIn("-af highpass=f=100,lowpass=f=5000", joined)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class ConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.source = self.dir / "source.wav"
        subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-ac",
                "2",
                "-ar",
                "44100",
                str(self.source),
            ],
            check=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_mp3_conversion_is_mono_and_low_rate(self) -> None:
        settings, _ = finalize(Settings(bitrate=24, sample_rate=11025))
        converter = Converter(settings, Log())
        target = self.dir / "out.mp3"
        progress: list[float] = []
        converter.convert(
            self.source,
            target,
            duration=2.0,
            on_progress=lambda fraction, speed: progress.append(fraction)
            if fraction is not None
            else None,
        )
        self.assertTrue(target.is_file())
        self.assertGreater(target.stat().st_size, 100)
        self.assertEqual(progress[-1], 1.0)
        self.assertFalse((self.dir / "out.mp3.part").exists())

        if FFPROBE:
            probe = subprocess.run(
                [
                    FFPROBE,
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=channels,sample_rate,codec_name",
                    "-of",
                    "default=nw=1",
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("codec_name=mp3", probe)
            self.assertIn("channels=1", probe)
            self.assertIn("sample_rate=11025", probe)

    def test_opus_conversion(self) -> None:
        settings, _ = finalize(Settings(audio_format="opus", bitrate=24, sample_rate=8000))
        converter = Converter(settings, Log())
        target = self.dir / "out.opus"
        try:
            converter.convert(self.source, target, duration=2.0)
        except ConversionError as exc:
            self.skipTest(f"libopus unavailable in this ffmpeg build: {exc}")
        self.assertTrue(target.is_file())
        self.assertGreater(target.stat().st_size, 100)

    def test_probe_duration(self) -> None:
        converter = Converter(Settings(), Log())
        duration = converter.probe_duration(self.source)
        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration or 0, 2.0, delta=0.2)

    def test_missing_source_errors(self) -> None:
        converter = Converter(Settings(), Log())
        with self.assertRaises(ConversionError):
            converter.convert(self.dir / "nope.wav", self.dir / "out.mp3", 1.0)


class SpeedFormattingTests(unittest.TestCase):
    def test_format_speed(self) -> None:
        self.assertEqual(format_speed(None), "")
        self.assertEqual(format_speed(0), "")
        self.assertTrue(format_speed(1024).endswith("/s"))


if __name__ == "__main__":
    unittest.main()
