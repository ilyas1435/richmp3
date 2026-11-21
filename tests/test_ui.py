from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from rich.console import Console

from richmp3.config import Settings
from richmp3.models import Playlist, Stage, Track
from richmp3.ui import Dashboard, UIContext, print_dry_run, print_summary


def make_context() -> UIContext:
    context = UIContext()
    playlist = Playlist(
        url="https://example.test/playlist",
        title="قائمة أغاني عربية طويلة جداً",
        tracks=[
            Track(
                index=1,
                url="u1",
                title="أغنية عربية",
                stage=Stage.DOWNLOADING,
                download_fraction=0.42,
                downloaded_bytes=1_200_000,
                total_bytes=3_000_000,
                speed=180_000,
                duration=215,
            ),
            Track(
                index=2,
                url="u2",
                title="A very long track name that must be truncated in a narrow terminal",
                stage=Stage.CONVERTING,
                convert_fraction=0.73,
                convert_speed=2.1,
                duration=180,
            ),
            Track(index=3, url="u3", title="Fetching", stage=Stage.FETCHING),
            Track(index=4, url="u4", title="Queued", stage=Stage.QUEUED),
            Track(index=5, url="u5", title="Done", stage=Stage.COMPLETED),
        ],
    )
    context.playlists.append(playlist)
    context.messages.append(("info", "Resolving [with] markup brackets"))
    return context


class DashboardRenderTests(unittest.TestCase):
    def test_render_multiple_widths(self) -> None:
        settings = Settings()
        for width in (40, 50, 78, 120):
            buffer = io.StringIO()
            console = Console(
                file=buffer, width=width, force_terminal=False, color_system=None
            )
            dashboard = Dashboard(console, settings, make_context())
            console.print(dashboard._render())
            output = buffer.getvalue()
            self.assertIn("RichMP3", output)
            self.assertLess(output.count("\n"), 30)

    def test_finished_and_zipping_states(self) -> None:
        context = make_context()
        context.finished = True
        for track in context.playlists[0].tracks:
            track.stage = Stage.COMPLETED
        context.playlists[0].stage = Stage.ZIPPING
        context.playlists[0].zip_fraction = 0.5
        buffer = io.StringIO()
        console = Console(file=buffer, width=90, force_terminal=False, color_system=None)
        console.print(Dashboard(console, Settings(), context)._render())
        self.assertIn("Zipping", buffer.getvalue())

    def test_summary_and_dry_run_render(self) -> None:
        context = make_context()
        playlist = context.playlists[0]
        playlist.directory = Path("/tmp/out/playlist")
        playlist.tracks[0].stage = Stage.FAILED
        playlist.tracks[0].error = "boom"
        playlist.tracks[1].stage = Stage.COMPLETED
        playlist.tracks[1].original_bytes = 3_000_000
        playlist.tracks[1].final_bytes = 300_000
        playlist.tracks[2].stage = Stage.SKIPPED

        buffer = io.StringIO()
        console = Console(file=buffer, width=100, force_terminal=False, color_system=None)
        print_summary(console, context, Settings())
        summary = buffer.getvalue()
        self.assertIn("Run summary", summary)
        self.assertIn("Failed items", summary)
        self.assertIn("Original", summary)
        self.assertIn("Final", summary)
        self.assertIn("Saved", summary)
        self.assertIn("min", summary)
        self.assertIn("MB", summary)

        with tempfile.TemporaryDirectory() as tmp:
            context.playlists[0].directory = Path(tmp)
            context.playlists[0].tracks[0].output_path = Path(tmp) / "0001 - x.mp3"
            buffer = io.StringIO()
            console = Console(file=buffer, width=100, force_terminal=False, color_system=None)
            print_dry_run(console, Settings(), context)
            self.assertIn("Dry run", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
