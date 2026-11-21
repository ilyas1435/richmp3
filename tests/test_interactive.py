from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from richmp3.config import default_convert_workers, default_output_directory
from richmp3.interactive import (
    configure_interactively,
    save_profile_interactively,
    save_settings_interactively,
)
from richmp3.profiles import load_profile


class InteractiveWizardTests(unittest.TestCase):
    def run_wizard(self, answers: list[str]):
        remaining = iter(answers)
        output: list[str] = []
        result = configure_interactively(
            input_fn=lambda _prompt: next(remaining),
            output_fn=output.append,
        )
        return result, output

    def test_recommended_lecture_profile_uses_compatible_phone_settings(self) -> None:
        result, output = self.run_wizard(
            ["", "", "32", "", "", "", "", "https://example.test/list", ""]
        )
        self.assertIsNotNone(result)
        self.assertTrue(any("Quick audio setup" in line for line in output))
        self.assertFalse(any(any("\u0600" <= char <= "\u06ff" for char in line) for line in output))
        assert result is not None
        urls, settings = result
        self.assertEqual(urls, ["https://example.test/list"])
        self.assertEqual(settings["format"], "mp3")
        self.assertEqual(settings["mode"], "vbr")
        self.assertEqual(settings["vbr_quality"], 7)
        self.assertEqual(settings["bitrate"], 32)
        self.assertEqual(settings["sample_rate"], 11025)
        self.assertEqual(settings["download_workers"], 8)
        self.assertEqual(settings["convert_workers"], default_convert_workers())
        self.assertEqual(settings["concurrent_fragments"], 16)
        self.assertEqual(settings["output"], str(default_output_directory()))
        self.assertEqual(settings["audio_language"], "original")
        self.assertFalse(settings["zip"])
        self.assertTrue(settings["voice_filter"])

    def test_custom_profile_and_multiple_urls(self) -> None:
        result, _ = self.run_wizard(
            ["3", "4", "20", "16000", "1", "", "/tmp/audio", "yes",
             "https://example.test/a https://example.test/b", "yes"]
        )
        self.assertIsNotNone(result)
        assert result is not None
        urls, settings = result
        self.assertEqual(len(urls), 2)
        self.assertEqual(settings["bitrate"], 20)
        self.assertEqual(settings["mode"], "cbr")
        self.assertEqual(settings["sample_rate"], 16000)
        self.assertEqual(settings["download_workers"], 1)
        self.assertEqual(settings["output"], "/tmp/audio")
        self.assertTrue(settings["zip"])

    def test_user_can_cancel_before_starting(self) -> None:
        result, output = self.run_wizard(
            ["1", "1", "", "1", "", "", "", "https://example.test", "no"]
        )
        self.assertIsNone(result)
        self.assertTrue(any("Cancelled" in line for line in output))

    def test_invalid_url_quotes_are_reported(self) -> None:
        result, output = self.run_wizard(
            ["2", "2", "", "", "", "", '"https://example.test', ""]
        )
        self.assertIsNone(result)
        self.assertTrue(any("quotation marks" in line for line in output))

    def test_settings_shortcut_saves_defaults_and_preserves_other_values(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "richmp3.toml"
            path.write_text(
                "# keep this comment\nretries = 5\ncustom_option = \"keep\"\n"
                "\n[custom]\nbitrate = 7\n",
                encoding="utf-8",
            )
            remaining = iter(["2", "1", "3", "", "", "", ""])
            output: list[str] = []
            saved = save_settings_interactively(
                input_fn=lambda _prompt: next(remaining),
                output_fn=output.append,
                config_path=path,
            )
            self.assertEqual(saved, path)
            self.assertIn("# keep this comment", path.read_text(encoding="utf-8"))
            config = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["bitrate"], 16)
            self.assertEqual(config["sample_rate"], 11025)
            self.assertEqual(config["download_workers"], 8)
            self.assertEqual(config["mode"], "abr")
            self.assertEqual(config["retries"], 5)
            self.assertEqual(config["custom_option"], "keep")
            self.assertEqual(config["custom"]["bitrate"], 7)

    def test_vbr_target_bitrate_is_saved_for_abr_and_cbr(self) -> None:
        with TemporaryDirectory() as tmp:
            answers = iter(["", "", "32", "", "", "", "", ""])
            saved = save_profile_interactively(
                "lecture",
                input_fn=lambda _prompt: next(answers),
                output_fn=lambda _line: None,
                profile_dir=Path(tmp),
            )
            self.assertEqual(saved, Path(tmp) / "lecture.toml")
            profile = load_profile("lecture", Path(tmp))
            self.assertEqual(profile["mode"], "vbr")
            self.assertEqual(profile["vbr_quality"], 7)
            self.assertEqual(profile["bitrate"], 32)


if __name__ == "__main__":
    unittest.main()
