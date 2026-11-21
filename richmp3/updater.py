"""Safe fast-forward updater for a clean Git checkout."""

from __future__ import annotations

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
            "لم أجد نسخة Git من المشروع. شغّل هذا الأمر من نسخة مستنسخة من GitHub.",
            ok=False,
        )

    if _git(root, "status", "--porcelain").stdout.strip():
        return UpdateResult(
            False,
            "لم يتم التحديث: توجد تغييرات محلية. احفظها أو انقلها أولًا ثم أعد المحاولة.",
            ok=False,
        )

    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream.returncode != 0:
        return UpdateResult(
            False,
            "لم يتم التحديث: لا يوجد فرع GitHub مرتبط بهذا الفرع.",
            ok=False,
        )

    fetched = _git(root, "fetch", "--quiet", upstream.stdout.strip().split("/", 1)[0])
    if fetched.returncode != 0:
        return UpdateResult(
            False,
            "تعذر الاتصال بمستودع GitHub. تحقق من الإنترنت وإعدادات Git ثم أعد المحاولة.",
            ok=False,
        )

    counts = _git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if counts.returncode != 0:
        return UpdateResult(False, "تعذر مقارنة النسخة المحلية بتحديث GitHub.", ok=False)
    try:
        ahead, behind = (int(value) for value in counts.stdout.split())
    except (TypeError, ValueError):
        return UpdateResult(False, "تعذر قراءة نتيجة مقارنة الفروع.", ok=False)

    if behind == 0:
        if ahead:
            return UpdateResult(False, "لا توجد تحديثات للتنزيل؛ نسختك المحلية فيها تغييرات أحدث.")
        return UpdateResult(False, "البرنامج محدّث بالفعل.")
    if ahead:
        return UpdateResult(
            False,
            "لم يتم التحديث: الفرع المحلي وGitHub يحتويان تغييرات متعارضة.",
            ok=False,
        )

    previous = _git(root, "rev-parse", "HEAD")
    pulled = _git(root, "pull", "--ff-only", "--quiet")
    if pulled.returncode != 0:
        return UpdateResult(
            False,
            "تعذر سحب التحديث السريع؛ لم أدمج تغييرات متعارضة.",
            ok=False,
        )
    current = _git(root, "rev-parse", "HEAD")
    changed = _git(root, "diff", "--name-only", previous.stdout.strip(), current.stdout.strip())
    paths = set(changed.stdout.splitlines())
    needs_dependencies = bool(paths & {"pyproject.toml", "requirements.txt"})
    message = "تم سحب التحديث. أعد تشغيل RichMP3 لتشغيل النسخة الجديدة."
    if needs_dependencies:
        message += " تغيّرت تبعيات Python؛ نفّذ python -m pip install -e . من مجلد المشروع."
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
