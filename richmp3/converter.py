"""FFmpeg-based audio conversion with live progress reporting."""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from .config import Settings
from .utils import Cancelled, Log, terminate_process

ProgressCallback = Callable[[float | None, float | None], None]

_TIME_RE = re.compile(r"(\d+):(\d+):(\d+(?:\.\d+)?)")
_SPEED_RE = re.compile(r"^([0-9.]+)x$")


class ConversionError(RuntimeError):
    pass


class Converter:
    """Builds and runs a single FFmpeg encode at a time."""

    def __init__(self, settings: Settings, log: Log) -> None:
        self.settings = settings
        self.log = log
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg:
            raise ConversionError("ffmpeg was not found on PATH")

    # -- command construction -------------------------------------------------

    def build_command(self, src: Path, dst: Path) -> list[str]:
        s = self.settings
        cmd: list[str] = [
            self.ffmpeg or "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(s.sample_rate),
            # One encode thread per FFmpeg process: the encoder pools already
            # saturate the CPU, and frame threading only adds latency/overhead.
            "-threads",
            "1",
        ]

        voice_filter = self._voice_filter(s)
        if voice_filter:
            cmd += ["-af", voice_filter]

        if s.audio_format == "mp3":
            cmd += [
                "-c:a",
                "libmp3lame",
                "-b:a",
                f"{s.bitrate}k",
                "-compression_level",
                "5",
            ]
            if s.mode == "abr":
                cmd += ["-abr", "1"]
            cmd += ["-id3v2_version", "3", "-write_id3v1", "0"]
            muxer = "mp3"
        else:
            cmd += [
                "-c:a",
                "libopus",
                "-b:a",
                f"{s.bitrate}k",
                "-vbr",
                "on",
                "-compression_level",
                "10",
                "-application",
                "audio",
            ]
            muxer = "ogg"

        cmd += [
            "-map_metadata",
            "0",
            "-progress",
            "pipe:1",
            "-nostats",
            "-f",
            muxer,
            str(dst),
        ]
        return cmd

    @staticmethod
    def _voice_filter(settings: Settings) -> str | None:
        """Strip rumble/hiss for low-rate voice encodes.

        Only applied at <=16 kHz, where the material is voice-oriented and the
        band above ~5 kHz carries mostly noise.  Music at 22.05 kHz or higher is
        left untouched.
        """
        if not settings.voice_filter or settings.sample_rate > 16000:
            return None
        lowpass = min(5000, settings.sample_rate // 2 - 200)
        highpass = min(100, max(20, settings.sample_rate // 10))
        return f"highpass=f={highpass},lowpass=f={lowpass}"

    # -- metadata -------------------------------------------------------------

    def probe_duration(self, path: Path) -> float | None:
        if not self.ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    self.ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        try:
            value = float(result.stdout.strip())
            return value if value > 0 else None
        except ValueError:
            return None

    # -- conversion -----------------------------------------------------------

    def convert(
        self,
        src: Path,
        dst: Path,
        duration: float | None,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if cancel_event and cancel_event.is_set():
            raise Cancelled()

        src = Path(src)
        if not src.is_file():
            raise ConversionError(f"Source file missing: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        temp_dst = dst.with_name(dst.name + ".part")
        for leftover in (temp_dst, dst.with_name(dst.name + ".part.part")):
            leftover.unlink(missing_ok=True)

        if duration is None:
            duration = self.probe_duration(src)

        cmd = self.build_command(src, temp_dst)
        self.log.debug("ffmpeg: " + " ".join(cmd))

        stderr_lines: deque[str] = deque(maxlen=40)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        def drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    self.log.debug(f"ffmpeg: {line}")

        stderr_thread = threading.Thread(target=drain_stderr, name="ffmpeg-stderr", daemon=True)
        stderr_thread.start()

        cancelled = False
        last_note = 0.0
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    break

                key, _, value = raw_line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and value.isdigit():
                    seconds = int(value) / 1_000_000
                    if duration and duration > 0:
                        fraction = max(0.0, min(1.0, seconds / duration))
                        if on_progress and time.monotonic() - last_note > 0.05:
                            on_progress(fraction, None)
                            last_note = time.monotonic()
                elif key == "out_time" and on_progress and duration:
                    match = _TIME_RE.search(value)
                    if match:
                        seconds = (
                            int(match.group(1)) * 3600
                            + int(match.group(2)) * 60
                            + float(match.group(3))
                        )
                        on_progress(max(0.0, min(1.0, seconds / duration)), None)
                elif key == "speed" and on_progress:
                    match = _SPEED_RE.match(value.strip())
                    if match:
                        on_progress(None, float(match.group(1)))

            if cancelled:
                terminate_process(proc)
            returncode = proc.wait()
        finally:
            if proc.stdout:
                try:
                    proc.stdout.close()
                except OSError:
                    pass
            stderr_thread.join(timeout=2)
            if proc.stderr:
                try:
                    proc.stderr.close()
                except OSError:
                    pass

        if cancelled or (cancel_event and cancel_event.is_set()):
            temp_dst.unlink(missing_ok=True)
            raise Cancelled()

        if returncode != 0:
            temp_dst.unlink(missing_ok=True)
            detail = " | ".join(stderr_lines) or f"ffmpeg exited with code {returncode}"
            raise ConversionError(detail)

        try:
            if temp_dst.stat().st_size == 0:
                raise ConversionError("ffmpeg produced an empty file")
        except FileNotFoundError as exc:
            raise ConversionError("ffmpeg reported success but produced no file") from exc

        temp_dst.replace(dst)
        if on_progress:
            on_progress(1.0, None)
        self.log.info(f"Converted {dst.name}")
        return dst
