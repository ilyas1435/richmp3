from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from richmp3.interactive import configure_interactively, save_settings_interactively


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
        result, _ = self.run_wizard(["", "", "", "", "https://example.test/list", ""])
        self.assertIsNotNone(result)
        assert result is not None
        urls, settings = result
        self.assertEqual(urls, ["https://example.test/list"])
        self.assertEqual(settings["format"], "mp3")
        self.assertEqual(settings["mode"], "cbr")
        self.assertEqual(settings["bitrate"], 24)
        self.assertEqual(settings["sample_rate"], 11025)
        self.assertEqual(settings["download_workers"], 2)
        self.assertEqual(settings["convert_workers"], 1)
        self.assertEqual(settings["concurrent_fragments"], 4)
        self.assertFalse(settings["zip"])
        self.assertTrue(settings["voice_filter"])

    def test_custom_profile_and_multiple_urls(self) -> None:
        result, _ = self.run_wizard(
            ["4", "20", "16000", "1", "/tmp/audio", "نعم",
             "https://example.test/a https://example.test/b", "نعم"]
        )
        self.assertIsNotNone(result)
        assert result is not None
        urls, settings = result
        self.assertEqual(len(urls), 2)
        self.assertEqual(settings["bitrate"], 20)
        self.assertEqual(settings["sample_rate"], 16000)
        self.assertEqual(settings["download_workers"], 1)
        self.assertEqual(settings["output"], "/tmp/audio")
        self.assertTrue(settings["zip"])

    def test_user_can_cancel_before_starting(self) -> None:
        result, output = self.run_wizard(
            ["1", "1", "", "", "https://example.test", "لا"]
        )
        self.assertIsNone(result)
        self.assertTrue(any("أُلغي" in line for line in output))

    def test_invalid_url_quotes_are_reported(self) -> None:
        result, output = self.run_wizard(
            ["2", "2", "", "", '"https://example.test', ""]
        )
        self.assertIsNone(result)
        self.assertTrue(any("علامات الاقتباس" in line for line in output))

    def test_settings_shortcut_saves_defaults_and_preserves_other_values(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "richmp3.toml"
            path.write_text(
                "# keep this comment\nretries = 5\ncustom_option = \"keep\"\n"
                "\n[custom]\nbitrate = 7\n",
                encoding="utf-8",
            )
            remaining = iter(["1", "3", "", "", ""])
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
            self.assertEqual(config["download_workers"], 3)
            self.assertEqual(config["retries"], 5)
            self.assertEqual(config["custom_option"], "keep")
            self.assertEqual(config["custom"]["bitrate"], 7)


if __name__ == "__main__":
    unittest.main()
