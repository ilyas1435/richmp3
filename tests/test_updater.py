from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from richmp3.updater import update_from_github


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class UpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        self.writer = self.root / "writer"
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(self.remote)],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "clone", str(self.remote), str(self.local)],
            capture_output=True,
            check=True,
        )
        self._configure_user(self.local)
        (self.local / "README.md").write_text("initial\n", encoding="utf-8")
        git(self.local, "add", "README.md")
        git(self.local, "commit", "-m", "initial")
        git(self.local, "push", "-u", "origin", "main")
        subprocess.run(
            ["git", "clone", str(self.remote), str(self.writer)],
            capture_output=True,
            check=True,
        )
        self._configure_user(self.writer)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _configure_user(path: Path) -> None:
        git(path, "config", "user.name", "RichMP3 test")
        git(path, "config", "user.email", "test@example.invalid")

    def test_pulls_a_clean_fast_forward_update(self) -> None:
        (self.writer / "new-file.txt").write_text("updated\n", encoding="utf-8")
        git(self.writer, "add", "new-file.txt")
        git(self.writer, "commit", "-m", "upstream update")
        git(self.writer, "push", "origin", "main")

        result = update_from_github(self.local)

        self.assertTrue(result.ok)
        self.assertTrue(result.updated)
        self.assertTrue((self.local / "new-file.txt").is_file())

    def test_reports_when_checkout_is_current(self) -> None:
        result = update_from_github(self.local)
        self.assertTrue(result.ok)
        self.assertFalse(result.updated)
        self.assertIn("already up to date", result.message)

    def test_refuses_to_update_a_dirty_checkout(self) -> None:
        (self.writer / "new-file.txt").write_text("updated\n", encoding="utf-8")
        git(self.writer, "add", "new-file.txt")
        git(self.writer, "commit", "-m", "upstream update")
        git(self.writer, "push", "origin", "main")
        (self.local / "README.md").write_text("my local change\n", encoding="utf-8")

        result = update_from_github(self.local)

        self.assertFalse(result.ok)
        self.assertIn("local changes", result.message)
        self.assertFalse((self.local / "new-file.txt").exists())
        self.assertEqual((self.local / "README.md").read_text(), "my local change\n")

    def test_reports_dependency_files_that_need_reinstall(self) -> None:
        (self.writer / "requirements.txt").write_text("rich>=14\n", encoding="utf-8")
        git(self.writer, "add", "requirements.txt")
        git(self.writer, "commit", "-m", "dependency update")
        git(self.writer, "push", "origin", "main")

        result = update_from_github(self.local)

        self.assertTrue(result.updated)
        self.assertTrue(result.dependencies_changed)
        self.assertIn("pip install -e", result.message)


if __name__ == "__main__":
    unittest.main()
