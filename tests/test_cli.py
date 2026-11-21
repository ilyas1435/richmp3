from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
import tomllib

from richmp3 import __version__
from richmp3.cli import _build_settings, _normalize_command, build_parser, main
from richmp3.config import config_path_default, finalize, load_config
from richmp3.downloader import (
    DownloadError,
    _audio_format_selector,
    audio_language_options,
)


class _QuietLog:
    def info(self, _message: str) -> None:
        pass

    def debug(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass

    def error(self, _message: str) -> None:
        pass


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
        self.assertEqual(settings.audio_language, "original")
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

    def test_friendly_commands_map_to_cli_actions(self) -> None:
        self.assertEqual(_normalize_command(["update"]), ["--update"])
        self.assertEqual(_normalize_command(["settings", "--config", "my.toml"]),
                         ["--settings", "--config", "my.toml"])
        self.assertEqual(_normalize_command(["download", "URL", "-b", "24"]),
                         ["URL", "-b", "24"])
        self.assertEqual(_normalize_command(["help"]), ["--help"])
        self.assertEqual(
            _normalize_command(["languages", "URL"]),
            ["--list-audio-languages", "URL"],
        )

    def test_running_without_arguments_opens_english_menu(self) -> None:
        output = StringIO()
        with patch("builtins.input", return_value="4"), redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn("Change and save settings", output.getvalue())
        self.assertNotRegex(output.getvalue(), r"[\u0600-\u06FF]")

    def test_languages_command_displays_english_track_choices(self) -> None:
        choices = [
            {
                "language": "en",
                "label": "Original track",
                "original": True,
                "default": False,
                "format_id": "251-0",
            },
            {
                "language": "ar",
                "label": "Audio track",
                "original": False,
                "default": False,
                "format_id": "251-1",
            },
        ]
        output = StringIO()
        with (
            patch(
                "richmp3.cli.Downloader.list_audio_languages",
                return_value=choices,
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(main(["languages", "https://example.test/video"]), 0)
        self.assertIn("en: Original track (original)", output.getvalue())
        self.assertIn("ar: Audio track", output.getvalue())
        self.assertNotRegex(output.getvalue(), r"[\u0600-\u06FF]")

    def test_project_and_runtime_versions_match(self) -> None:
        with Path("pyproject.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
        self.assertEqual(__version__, config["project"]["version"])
        self.assertEqual(__version__, "1.5.0")

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

    def test_audio_language_can_be_saved_and_overridden(self) -> None:
        saved, _ = finalize(
            _build_settings(self.parse(["URL"]), {"audio_language": "ar"})
        )
        self.assertEqual(saved.audio_language, "ar")
        command_line, _ = finalize(
            _build_settings(
                self.parse(["--audio-language", "en-US", "URL"]),
                {"audio_language": "ar"},
            )
        )
        self.assertEqual(command_line.audio_language, "en-US")

    def test_invalid_audio_language_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            finalize(
                _build_settings(
                    self.parse(["--audio-language", "not a code", "URL"]), {}
                )
            )

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

    def test_default_audio_prefers_explicit_original_track(self) -> None:
        log = _QuietLog()
        select = _audio_format_selector("original", log)
        dub = {"format_id": "251-1", "language": "fr", "format_note": "French", "acodec": "opus", "vcodec": "none", "abr": 32}
        original = {"format_id": "251-0", "language": "de", "format_note": "German (original)", "acodec": "opus", "vcodec": "none", "abr": 48}
        selected = select({"formats": [dub, original]})
        self.assertEqual(selected, [original])

    def test_default_does_not_guess_when_multiple_languages_are_unmarked(self) -> None:
        select = _audio_format_selector("original", _QuietLog())
        formats = [
            {"format_id": "a", "language": "en", "acodec": "opus", "vcodec": "none"},
            {"format_id": "b", "language": "fr", "acodec": "opus", "vcodec": "none"},
        ]
        with self.assertRaisesRegex(DownloadError, "Could not identify the original"):
            select({"formats": formats})

    def test_manual_language_selects_smallest_matching_track(self) -> None:
        select = _audio_format_selector("ar", _QuietLog())
        arabic_high = {"format_id": "ar2", "language": "ar-SA", "acodec": "opus", "vcodec": "none", "abr": 48}
        arabic_low = {"format_id": "ar1", "language": "ar", "acodec": "opus", "vcodec": "none", "abr": 32}
        english = {"format_id": "en", "language": "en", "acodec": "opus", "vcodec": "none", "abr": 24}
        self.assertEqual(
            select({"formats": [arabic_high, english, arabic_low]}),
            [arabic_low],
        )

    def test_language_listing_marks_original_and_groups_formats(self) -> None:
        formats = [
            {"format_id": "251-0", "language": "en", "format_note": "English (original)", "acodec": "opus", "vcodec": "none", "language_preference": 10},
            {"format_id": "140", "language": "en", "format_note": "English (original)", "acodec": "aac", "vcodec": "none", "language_preference": 10},
            {"format_id": "251-1", "language": "ar", "format_note": "Arabic", "acodec": "opus", "vcodec": "none"},
            {"format_id": "137", "language": "en", "format_note": "English video", "acodec": "none", "vcodec": "avc1"},
        ]
        choices = audio_language_options(formats)
        self.assertEqual([choice["language"] for choice in choices], ["en", "ar"])
        self.assertTrue(choices[0]["original"])
        self.assertEqual(choices[0]["format_count"], 2)


if __name__ == "__main__":
    unittest.main()
