from __future__ import annotations

import unittest

from richmp3.interactive import configure_interactively


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


if __name__ == "__main__":
    unittest.main()
