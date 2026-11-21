from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from richmp3.profiles import (
    list_profiles,
    load_profile,
    save_profile,
    validate_profile_name,
)


class ProfileTests(unittest.TestCase):
    def test_profile_round_trip_and_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = save_profile(
                "lecture",
                {
                    "mode": "abr",
                    "bitrate": 24,
                    "audio_language": "original",
                    "zip": False,
                },
                folder,
            )
            self.assertEqual(path, folder / "lecture.toml")
            self.assertEqual(
                load_profile("lecture", folder),
                {
                    "mode": "abr",
                    "bitrate": 24,
                    "audio_language": "original",
                    "zip": False,
                },
            )
            self.assertEqual(list_profiles(folder), ["lecture"])

    def test_duplicate_profile_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            save_profile("small", {"bitrate": 16}, folder)
            with self.assertRaises(FileExistsError):
                save_profile("small", {"bitrate": 32}, folder)
            save_profile("small", {"bitrate": 32}, folder, overwrite=True)
            self.assertEqual(load_profile("small", folder)["bitrate"], 32)

    def test_profile_names_prevent_path_traversal(self) -> None:
        for name in ("../escape", "BadName", "two words", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_profile_name(name)

    def test_unknown_settings_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Unsupported profile settings"):
                save_profile("safe", {"unknown_key": "value"}, Path(tmp))

    def test_missing_profile_has_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "richmp3 profiles"):
                load_profile("missing", Path(tmp))


if __name__ == "__main__":
    unittest.main()
