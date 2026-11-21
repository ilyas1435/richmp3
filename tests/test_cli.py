from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from richmp3.cli import _build_settings, build_parser
from richmp3.config import config_path_default, finalize, load_config
from richmp3.downloader import _FORMAT_SELECTOR


class CliSettingsTests(unittest.TestCase):
    def parse(self, argv: list[str]):
        return build_parser().parse_args(argv)

    def test_defaults(self) -> None:
        settings, notices = finalize(_build_settings(self.parse(["URL"]), {}))
        self.assertEqual(settings.audio_format, "mp3")
        self.assertEqual(settings.bitrate, 24)
        self.assertEqual(settings.sample_rate, 11025)
        self.assertEqual(settings.download_workers, 4)
        self.assertTrue(settings.playlist)
        self.assertTrue(settings.zip_output)
        self.assertEqual(settings.mode_label, "ABR")
        self.assertTrue(settings.voice_filter)
        self.assertEqual(settings.js_runtime, "auto")
        self.assertFalse(settings.keep_folder)
        self.assertEqual(settings.concurrent_fragments, 8)
        self.assertFalse(notices)

    def test_wizard_flag_does_not_require_url(self) -> None:
        args = self.parse(["--wizard"])
        self.assertTrue(args.wizard)
        self.assertEqual(args.urls, [])

    def test_settings_and_update_commands_need_no_url(self) -> None:
        self.assertTrue(self.parse(["--settings"]).settings)
        self.assertTrue(self.parse(["--update"]).update)

    def test_flags_override(self) -> None:
        settings, _ = finalize(
            _build_settings(
                self.parse(
                    [
                        "-b", "32", "-r", "22050", "-f", "mp3", "--mode", "cbr",
                        "--no-playlist", "--no-zip", "--overwrite", "-w", "2",
                        "--convert-workers", "1", "--no-ui", "URL",
                    ]
                ),
                {},
            )
        )
        self.assertEqual(settings.bitrate, 32)
        self.assertEqual(settings.sample_rate, 22050)
        self.assertEqual(settings.mode_label, "CBR")
        self.assertFalse(settings.playlist)
        self.assertFalse(settings.zip_output)
        self.assertTrue(settings.overwrite)
        self.assertEqual(settings.download_workers, 2)
        self.assertEqual(settings.convert_workers, 1)
        self.assertTrue(settings.no_ui)
        self.assertFalse(settings.force_ui)

    def test_voice_filter_flags(self) -> None:
        settings, _ = finalize(_build_settings(self.parse(["URL"]), {}))
        self.assertTrue(settings.voice_filter)
        settings, _ = finalize(_build_settings(self.parse(["--no-voice-filter", "URL"]), {}))
        self.assertFalse(settings.voice_filter)
        settings, _ = finalize(_build_settings(self.parse(["URL"]), {"voice_filter": False}))
        self.assertFalse(settings.voice_filter)

    def test_keep_folder_flags(self) -> None:
        settings, _ = finalize(_build_settings(self.parse(["--keep-folder", "URL"]), {}))
        self.assertTrue(settings.keep_folder)
        settings, _ = finalize(_build_settings(self.parse(["--remove-folder", "URL"]), {}))
        self.assertFalse(settings.keep_folder)
        settings, _ = finalize(_build_settings(self.parse(["URL"]), {"keep_folder": True}))
        self.assertTrue(settings.keep_folder)

    def test_ui_force_flag(self) -> None:
        settings, _ = finalize(_build_settings(self.parse(["--ui", "URL"]), {}))
        self.assertFalse(settings.no_ui)
        self.assertTrue(settings.force_ui)

    def test_config_values_and_cli_precedence(self) -> None:
        config = {"format": "opus", "bitrate": 16, "zip": False, "download_workers": 6}
        settings, _ = finalize(_build_settings(self.parse(["-b", "48", "URL"]), config))
        self.assertEqual(settings.audio_format, "opus")
        self.assertEqual(settings.bitrate, 48)
        self.assertEqual(settings.sample_rate, 12000)
        self.assertFalse(settings.zip_output)
        self.assertEqual(settings.download_workers, 6)
        self.assertEqual(settings.mode_label, "VBR")

    def test_invalid_config_bool(self) -> None:
        with self.assertRaises(ValueError):
            _build_settings(self.parse(["URL"]), {"zip": "yes"})

    def test_missing_cookies_file(self) -> None:
        with self.assertRaises(ValueError):
            _build_settings(self.parse(["--cookies", "/nope/cookies.txt", "URL"]), {})

    def test_invalid_limit_rate(self) -> None:
        with self.assertRaises(ValueError):
            _build_settings(self.parse(["--limit-rate", "fast", "URL"]), {})

    def test_invalid_js_runtime_from_config(self) -> None:
        with self.assertRaises(ValueError):
            _build_settings(self.parse(["URL"]), {"js_runtime": "v8"})

    def test_config_file_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "richmp3.toml"
            path.write_text(
                'bitrate = 32\nformat = "opus"\nzip = false\nunknown = "ignored"\n',
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config["bitrate"], 32)
            self.assertEqual(config["format"], "opus")
            self.assertNotIn("unknown", config)

    def test_implicit_config_is_optional(self) -> None:
        path = config_path_default()
        self.assertTrue(path is None or path.is_file())

    def test_format_selector_is_strict_worstaudio(self) -> None:
        self.assertIn("worstaudio", _FORMAT_SELECTOR)
        self.assertIn("language_preference>0", _FORMAT_SELECTOR)
        self.assertIn("worstaudio[ext=m4a]", _FORMAT_SELECTOR)
        self.assertIn("worstaudio[ext=webm]", _FORMAT_SELECTOR)
        self.assertNotIn("bestaudio", _FORMAT_SELECTOR)
        self.assertTrue(_FORMAT_SELECTOR.startswith("worstaudio[ext=m4a]"))
        self.assertTrue(_FORMAT_SELECTOR.endswith("/worst/best"))


if __name__ == "__main__":
    unittest.main()
