# RichMP3

Fast, resilient audio downloading and conversion in a single command.

RichMP3 pulls the **lowest-bandwidth audio** available from YouTube, SoundCloud,
Archive.org and the 1000+ other sites supported by yt-dlp, converts it to a
compact **mono** file with FFmpeg, keeps filenames and folder names in full
Unicode (Arabic included), and archives each finished playlist as a ZIP — all
while a live Rich dashboard shows per-track and overall progress.

```
RichMP3   قائمة القرآن الكريم   12 tracks · 7 done
MP3 · ABR 24 kbps · 11025 Hz · mono · 4↓ 4⚙

Overall █████████████░░░░░░░░░░░   58.2%   7/12
 001  Title A    Downloading   ████░░░░░░░░   41%  1.2 MB/3.0 MB 180 KB/s
 002  Title B    Converting    ███████░░░░░   73%  2.1x encode
 003  Title C    Fetching Metadata
 004  Title D    Queued
⠋ Elapsed 00:03:12  ·  ETA 00:02:05
```

## Features

- **Bandwidth-first download** — strictly the lowest-bandwidth `worstaudio`
  stream (original-language only, dubs filtered), preferring `m4a`/`webm`
  containers that demux fastest, with `worst`/`best` only as a last resort for
  sites that expose a single progressive file.
- **Original language track** — dubbed/localised audio is filtered out with
  yt-dlp's `language_preference` metadata; the original or default track wins.
- **Configurable encoding** — 8–128 kbps, 8000–44100 Hz, always mono.
  Default: MP3, ABR 24 kbps, 11025 Hz, LAME `-compression_level 5`.
- **Voice-clarity filter** — at ≤16 kHz, `highpass=f=100,lowpass=f=5000` strips
  rumble and hiss for clearer speech and slightly smaller files. Disable with
  `--no-voice-filter`.
- **Sequential, Unicode-safe names** — `0001 - العنوان.mp3` with NFC
  normalisation, bidi-control stripping and byte-safe UTF-8 truncation.
- **Playlists and channels** — resolved once, downloaded item by item into one
  folder per playlist, in order.
- **Parallel producer/consumer** — separate download and encoder pools: a track
  starts encoding the moment its download finishes while later tracks keep
  downloading. Fragmented HLS/DASH downloads fetch up to 8 fragments at once,
  and each encoder is pinned to one thread.
- **Self-cleaning** — every raw download is deleted right after a successful
  conversion; only final files and the ZIP remain. When zipping succeeds the
  duplicate source folder is deleted too (`--keep-folder` opts out).
- **Crash-resistant** — per-track retries with backoff, failure isolation,
  atomic conversion/zip writes, and a cancellation path that terminates FFmpeg.
- **Two interfaces** — live Rich dashboard on a TTY, plain line output for pipes
  and `--no-ui`.
- **Savings report** — the end-of-run panel shows original vs. final size,
  bright-green MB + % saved, and total elapsed minutes.

## Requirements

- Python 3.11+
- FFmpeg (with `libmp3lame`, and `libopus` if you use `--format opus`)
- `rich` and `yt-dlp` (installed as package dependencies)

Termux:

```bash
pkg install python ffmpeg
python -m pip install rich yt-dlp
```

From this repository:

```bash
python -m pip install -e .
richmp3 --version
# or, without installing:
python -m richmp3 --version
```

## Quick start

```bash
# Default: MP3, ABR 24 kbps, 11025 Hz, mono, ZIP enabled
richmp3 "https://www.youtube.com/playlist?list=..."

# Several URLs in one run
richmp3 URL1 URL2

# Higher quality, no archive
richmp3 -b 64 -r 22050 --no-zip URL

# Better quality per byte at low bitrates (Opus, 8-128 kbps)
richmp3 -f opus -b 24 URL

# Preview planned filenames; touches nothing and needs no FFmpeg
richmp3 --dry-run URL

# Slow connection
richmp3 --limit-rate 300k --workers 2 URL

# Restricted / age-gated media
richmp3 --cookies ~/cookies.txt URL
```

Exit codes: `0` success, `1` one or more failures, `2` setup error
(missing FFmpeg, bad options), `130` interrupted.

## How the defaults work

| Setting | Default | Notes |
| --- | --- | --- |
| bitrate | `24` kbps | clamped to 8–128; MP3 ceiling also depends on sample rate |
| sample rate | `11025` Hz | `11000` is not a legal MP3 rate, so input snaps to the closest legal rate; Opus defaults to 12000 Hz |
| channels | mono | always `-ac 1` |
| mode | ABR | LAME `-abr 1` (variable bitrate around the target) |
| MP3 quality | `compression_level 5` | balanced LAME speed/size |
| voice filter | on at ≤16 kHz | `highpass=100, lowpass=5000`; off with `--no-voice-filter` |
| container | MP3 | `--format opus` produces Ogg/Opus |
| download workers | `4` | parallel tracks |
| encode workers | CPU/2, max 4 | caps simultaneous FFmpeg processes (`-threads 1` each) |
| concurrent fragments | `8` | parallel HLS/DASH fragment fetches |
| ZIP | on | `stored` by default (audio does not compress) |
| source folder | removed after ZIP | `--keep-folder` keeps it |

**Why ABR instead of `-q:a`?** LAME's VBR quality scale (`-q:a 0–9`) does not map
to a kbps target, so "24 kbps VBR" is best expressed as ABR at 24 kbps. Use
`--mode cbr` for constant bitrate.

**Why 11025 Hz?** MP3 only supports the MPEG-2.5/2/1 rates
(8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000). RichMP3 snaps
requests to the nearest legal rate and warns instead of letting FFmpeg fail.
For Opus the legal rates are 8, 12, 16, 24 and 48 kHz. Opus always decodes at
48 kHz internally, so `ffprobe` reports 48 kHz even when a lower rate is fed to
the encoder; the requested rate still controls the encoded bandwidth.

## Output layout

```
downloads/
├── قائمة قصائد عربية/
│   ├── 0001 -  أولى.mp3
│   ├── 0002 -  ثانية.mp3
│   └── 0003 -  ثالثة.mp3
└── قائمة قصائد عربية.zip
```

- Folder name = playlist/channel title (sanitised, never transliterated).
- Prefix width is automatic (minimum 4 digits) or fixed with `--number-width`.
- Raw downloads live in a hidden sibling `.<folder>.part/` directory on the same
  filesystem and are removed after every successful conversion.
- After a successful ZIP, the source folder is removed by default; pass
  `--keep-folder` (or `keep_folder = true`) to keep it.
- Re-running a URL skips files that already exist; pass `--overwrite` to redo
  them. Conversion and ZIP writes use a `.part` file and an atomic rename.

## Summary panel

```
╭─────────────────────────── Run summary ───────────────────────────╮
│ Original             Final                Saved          Elapsed │
│ 1.20 MB              0.34 MB              0.86 MB (71.7%)  2.4 min │
╰───────────────────────────────────────────────────────────────────╯
```

Original = bytes downloaded before conversion; Final = bytes written after
conversion. Saved is highlighted bright green in both MB and percent.

## Configuration file

RichMP3 reads `./richmp3.toml` or `~/.config/richmp3/config.toml` if present.
Command-line flags override the file. Use `--config PATH` for an explicit file.

```toml
output = "~/Music/richmp3"
bitrate = 24
sample_rate = 11025
format = "mp3"        # mp3 | opus
mode = "abr"          # abr | cbr
voice_filter = true   # strip rumble/hiss at <=16 kHz (clearer voice, smaller files)
download_workers = 4
convert_workers = 4
playlist = true
zip = true
zip_method = "stored" # stored | deflate
retries = 3
number_width = 4
overwrite = false
keep_folder = false     # false = delete the source folder after a successful zip
cookies = "~/cookies.txt"
limit_rate = "500k"
js_runtime = "auto"   # auto | deno | node | bun | quickjs
remote_components = false  # allow yt-dlp's EJS solver for better YouTube formats
timeout = 30
concurrent_fragments = 8
log_file = "~/richmp3.log"
no_ui = false
```

## Progress states

Each track moves through **Queued → Fetching Metadata → Downloading →
Converting → Cleaning Up → Completed**, or ends as **Failed / Skipped /
Cancelled**. Playlist-level **Zipping** is shown in the footer with its own bar.
Overall percentage is weighted by actual stage progress, not just item counts.

## Architecture

```
richmp3/
  cli.py          argument parsing, config merge, exit codes
  config.py       Settings dataclass, validation, sample-rate snapping
  models.py       Track/Playlist/Stage state model + progress weights
  downloader.py   yt-dlp wrapper, playlist resolution, format selection
  converter.py    FFmpeg command builder, progress parser, cancellation
  organizer.py    Unicode-safe names, sequential prefixes, temp layout, cleanup
  archive.py      streaming ZIP writer with progress and atomic replace
  ui.py           Rich live dashboard, plain fallback, summary, dry-run table
  pipeline.py     worker pools, retries, cleanup, ZIP orchestration
  utils.py        names, rates, formatting, process control, logging
tests/            unit + real-FFmpeg integration tests
```

The pipeline is intentionally dependency-injected at the seams
(`downloader` and `converter` attributes), so tests run the whole orchestration
without network access. `python -m unittest discover -s tests -v` covers naming,
config snapping, FFmpeg commands, a real encode, ZIP behaviour, retries,
cancellation and every UI render width.

## Performance notes on Android/Termux

- Shared storage (`/storage/emulated/0`) is FUSE-backed. Parallel writes are
  much slower there than on internal storage; `-w 4` is a sensible ceiling and
  `convert_workers = 2` avoids thermal throttling.
- Downloads and encodes run in separate pools. A slow encode never idles a
  download worker, so playlists stay network-saturated until the last file.
- Downloads are network-bound and fragmented media (`concurrent_fragments = 8`)
  benefits the most from parallelism.
- `--no-zip` saves a full read/write pass of the playlist on slow storage.
- `--no-voice-filter` keeps full-band audio if you are archiving music rather
  than speech.
- FFmpeg runs as a child process; `Ctrl+C` terminates the process group and
  removes partial encodes.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ffmpeg was not found` | `pkg install ffmpeg` (Termux) or install FFmpeg for your OS |
| `Sign in to confirm you're not a bot` | export cookies with a browser extension and pass `--cookies` |
| `No supported JavaScript runtime` | install Deno or Node (`pkg install nodejs`); RichMP3 auto-detects it, or set `js_runtime` |
| YouTube reports missing formats / `n challenge` | add `--remote-components` to allow yt-dlp's EJS solver, or install Deno |
| HTTP 403 / 429 | lower `--workers`, set `--limit-rate`, retry later |
| Opus will not play | use the default MP3, or a player with Opus support |
| A very long title is shortened | filenames are capped at a UTF-8-safe byte budget; a short hash suffix is added |
| Arabic appears reversed | that is terminal bidi shaping, not the filename; check with `ls` or a file manager |

## License

MIT
