"""Playlist archiving with progress and cancellation support."""

from __future__ import annotations

import threading
import zipfile
from pathlib import Path
from typing import Callable

from .utils import Cancelled, Log, safe_unlink

ProgressCallback = Callable[[float], None]
_CHUNK = 1024 * 1024


class ArchiveError(RuntimeError):
    pass


class Archiver:
    def __init__(self, log: Log) -> None:
        self.log = log

    def create(
        self,
        folder: Path,
        zip_path: Path,
        method: str = "stored",
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        folder = Path(folder)
        zip_path = Path(zip_path)
        files = sorted(path for path in folder.rglob("*") if path.is_file())
        if not files:
            raise ArchiveError(f"No files to archive in {folder}")

        total = sum(path.stat().st_size for path in files) or 1
        compression = zipfile.ZIP_DEFLATED if method == "deflate" else zipfile.ZIP_STORED
        temp_path = zip_path.with_name(zip_path.name + ".part")
        safe_unlink(temp_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        try:
            with zipfile.ZipFile(
                temp_path,
                mode="w",
                compression=compression,
                allowZip64=True,
                compresslevel=6 if compression == zipfile.ZIP_DEFLATED else None,
            ) as archive:
                for path in files:
                    if cancel_event and cancel_event.is_set():
                        raise Cancelled()
                    arcname = path.relative_to(folder).as_posix()
                    info = zipfile.ZipInfo.from_file(path, arcname)
                    info.compress_type = compression
                    with open(path, "rb") as source, archive.open(info, mode="w") as target:
                        while True:
                            if cancel_event and cancel_event.is_set():
                                raise Cancelled()
                            chunk = source.read(_CHUNK)
                            if not chunk:
                                break
                            target.write(chunk)
                            written += len(chunk)
                            if on_progress:
                                on_progress(min(1.0, written / total))
            if cancel_event and cancel_event.is_set():
                raise Cancelled()
            temp_path.replace(zip_path)
        except BaseException:
            safe_unlink(temp_path)
            raise

        if on_progress:
            on_progress(1.0)
        self.log.info(f"Archived {len(files)} files -> {zip_path.name}")
        return zip_path
