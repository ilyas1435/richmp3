"""Named, reusable settings profiles."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from .config import CONFIG_KEYS

_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")


def profile_directory() -> Path:
    return Path.home() / ".config" / "richmp3" / "profiles"


def validate_profile_name(name: str) -> str:
    if not _PROFILE_NAME.fullmatch(name):
        raise ValueError(
            "Profile names must be 1-24 lowercase letters or numbers; "
            "hyphens and underscores are also allowed."
        )
    return name


def profile_path(name: str, directory: Path | None = None) -> Path:
    return (directory or profile_directory()) / f"{validate_profile_name(name)}.toml"


def save_profile(
    name: str,
    settings: dict[str, object],
    directory: Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    path = profile_path(name, directory)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Profile '{name}' already exists.")
    unknown = set(settings) - CONFIG_KEYS
    if unknown:
        raise ValueError(f"Unsupported profile settings: {', '.join(sorted(unknown))}")

    lines: list[str] = []
    for key, value in settings.items():
        if isinstance(value, bool):
            encoded = "true" if value else "false"
        elif isinstance(value, (int, float)):
            encoded = str(value)
        elif isinstance(value, str):
            encoded = json.dumps(value, ensure_ascii=False)
        else:
            raise TypeError(f"Unsupported value for profile setting '{key}'")
        lines.append(f"{key} = {encoded}")
    if not lines:
        raise ValueError("Cannot save an empty profile.")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return path


def load_profile(name: str, directory: Path | None = None) -> dict[str, Any]:
    path = profile_path(name, directory)
    if not path.is_file():
        raise ValueError(f"Profile '{name}' was not found. Run 'richmp3 profiles' to list profiles.")
    with path.open("rb") as source:
        data = tomllib.load(source)
    settings = {key: value for key, value in data.items() if key in CONFIG_KEYS}
    if not settings:
        raise ValueError(f"Profile '{name}' has no supported settings.")
    return settings


def list_profiles(directory: Path | None = None) -> list[str]:
    folder = directory or profile_directory()
    if not folder.is_dir():
        return []
    return sorted(
        path.stem
        for path in folder.glob("*.toml")
        if path.is_file() and _PROFILE_NAME.fullmatch(path.stem)
    )
