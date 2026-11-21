"""Safe fast-forward updater for a clean Git checkout."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateResult:
    updated: bool
    message: str
    ok: bool = True
    dependencies_changed: bool = False


def update_from_github(start: Path | None = None) -> UpdateResult:
    """Fetch the configured upstream and fast-forward only a clean checkout."""
    root = find_repository_root(start or Path(__file__))
    if root is None:
        return UpdateResult(
            False,
            "No Git checkout found. Run this command from a GitHub clone.",
            ok=False,
        )

    if _git(root, "status", "--porcelain").stdout.strip():
        return UpdateResult(
            False,
            "Update cancelled: the working tree has local changes. Commit or move them, then retry.",
            ok=False,
        )

    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream.returncode != 0:
        return UpdateResult(
            False,
            "Update unavailable: this branch has no configured upstream.",
            ok=False,
        )

    fetched = _git(root, "fetch", "--quiet", upstream.stdout.strip().split("/", 1)[0])
    if fetched.returncode != 0:
        return UpdateResult(
            False,
            "Could not reach GitHub. Check your connection and Git configuration, then retry.",
            ok=False,
        )

    counts = _git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if counts.returncode != 0:
        return UpdateResult(False, "Could not compare the local checkout with GitHub.", ok=False)
    try:
        ahead, behind = (int(value) for value in counts.stdout.split())
    except (TypeError, ValueError):
        return UpdateResult(False, "Could not read the branch comparison result.", ok=False)

    if behind == 0:
        if ahead:
            return UpdateResult(False, "No updates to download; the local branch is ahead.")
        return UpdateResult(False, "RichMP3 is already up to date.")
    if ahead:
        return UpdateResult(
            False,
            "Update cancelled: the local branch and GitHub have diverged.",
            ok=False,
        )

    previous = _git(root, "rev-parse", "HEAD")
    pulled = _git(root, "pull", "--ff-only", "--quiet")
    if pulled.returncode != 0:
        return UpdateResult(
            False,
            "Fast-forward update failed. No conflicting changes were merged.",
            ok=False,
        )
    current = _git(root, "rev-parse", "HEAD")
    changed = _git(root, "diff", "--name-only", previous.stdout.strip(), current.stdout.strip())
    paths = set(changed.stdout.splitlines())
    needs_dependencies = bool(paths & {"pyproject.toml", "requirements.txt"})
    message = "Update installed. Restart RichMP3 to use the new version."
    if needs_dependencies:
        termux_python = Path.home() / ".venvs" / "richmp3" / "bin" / "python"
        python = str(termux_python) if termux_python.is_file() else "python"
        command = shlex.join([python, "-m", "pip", "install", "-e", str(root)])
        message += f" Python dependencies changed; run: {command}"
    return UpdateResult(True, message, dependencies_changed=needs_dependencies)


def find_repository_root(start: Path) -> Path | None:
    """Find the nearest checkout containing the module or current directory."""
    start = Path(start).resolve()
    candidates = (start, *start.parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(["git", *args], 1, "", "")
