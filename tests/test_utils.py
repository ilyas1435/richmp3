from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from richmp3.utils import (
    format_bytes,
    format_duration,
    parse_rate,
    sanitize_filename,
    unique_path,
)


class UtilsTests(unittest.TestCase):
    def test_parse_rate(self) -> None:
        self.assertEqual(parse_rate("500k"), 500 * 1024)
        self.assertEqual(parse_rate("1M"), 1024 * 1024)
        self.assertEqual(parse_rate("1.5m"), int(1.5 * 1024 * 1024))
        self.assertEqual(parse_rate("8000"), 8000)
        self.assertIsNone(parse_rate(None))
        with self.assertRaises(ValueError):
            parse_rate("fast")

    def test_format_helpers(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "1:01:01")
        self.assertEqual(format_duration(None), "--:--")

    def test_sanitize_keeps_arabic(self) -> None:
        self.assertEqual(sanitize_filename("أغنية عربية"), "أغنية عربية")

    def test_sanitize_removes_illegal_characters(self) -> None:
        result = sanitize_filename('a/b\\c:d*e?f"g<h>i|j')
        for char in '/\\:*?"<>|':
            self.assertNotIn(char, result)
        self.assertIn("a", result)

    def test_sanitize_removes_bidi_controls(self) -> None:
        result = sanitize_filename("abc\u202edef\u2066ghi")
        self.assertEqual(result, "abcdefghi")

    def test_sanitize_truncates_on_utf8_boundary(self) -> None:
        name = "عربي" * 200
        result = sanitize_filename(name, max_bytes=60)
        self.assertLessEqual(len(result.encode("utf-8")), 60)
        self.assertTrue(result)  # must not cut a multi-byte character in half

    def test_sanitize_reserved_windows_name(self) -> None:
        self.assertTrue(sanitize_filename("CON").startswith("_CON"))

    def test_sanitize_empty_fallback(self) -> None:
        self.assertEqual(sanitize_filename("   ...  "), "untitled")

    def test_unique_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.mp3"
            path.write_bytes(b"x")
            self.assertEqual(unique_path(path).name, "a (2).mp3")
            unique_path(path).write_bytes(b"x")
            self.assertEqual(unique_path(path).name, "a (3).mp3")


if __name__ == "__main__":
    unittest.main()
