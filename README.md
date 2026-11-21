# RichMP3

Fast, resilient audio downloading and conversion in a single command.

RichMP3 pulls the **lowest-bandwidth audio** available from YouTube, SoundCloud,
Archive.org and the 1000+ other sites supported by yt-dlp, converts it to a
compact **mono** file with FFmpeg, keeps filenames and folder names in full
Unicode (Arabic included), and archives each finished playlist as a ZIP — all
while a live Rich dashboard shows per-track and overall progress.

```
RichMP3   قائمة القرآن الكريم   12 tracks · 7 done
MP3 · VBR Q7 · 11025 Hz · mono · 8↓ 8⚙

Overall █████████████░░░░░░░░░░░   58.2%   7/12
 001  Title A    Downloading   ████░░░░░░░░   41%  1.2 MB/3.0 MB 180 KB/s
 002  Title B    Converting    ███████░░░░░   73%  2.1x encode
 003  Title C    Fetching Metadata
 004  Title D    Queued
⠋ Elapsed 00:03:12  ·  ETA 00:02:05
```

## Features

- **Bandwidth-first download** — chooses the smallest audio-only stream for
  the selected language, then converts it to the requested compact format.
- **Original language by default** — explicitly marked original tracks are
  preferred. If a source exposes several languages but does not identify the
  original, RichMP3 stops and explains how to choose instead of silently
  downloading a dub.
- **Configurable encoding** — 8–128 kbps, 8000–44100 Hz, always mono.
  Default: MP3 VBR Q7, 11025 Hz; ABR and CBR are also available.
- **Voice-clarity filter** — at ≤16 kHz, `highpass=f=100,lowpass=f=5000` strips
  rumble and hiss for clearer speech and slightly smaller files. Disable with
  `--no-voice-filter`.
- **Sequential, Unicode-safe names** — `0001 - العنوان.mp3` with NFC
  normalisation, bidi-control stripping and byte-safe UTF-8 truncation.
- **Playlists and channels** — resolved once with `extract_flat: in_playlist` and
  consumed lazily, so workers start on the first track without waiting for the
  whole playlist to enumerate. Files land in one folder per playlist, in order.
- **Parallel producer/consumer** — separate download and encoder pools: a track
  starts encoding the moment its download finishes while later tracks keep
  downloading. Fragmented HLS/DASH downloads fetch up to 16 fragments at once,
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

### Install on Termux

This one-time command installs the launcher and its dependencies. It uses the
public GitHub repository and keeps the editable checkout in Termux home so
`richmp3 update` can update it later:

```bash
pkg update -y && pkg install -y git && \
mkdir -p "$HOME/.local/share" && \
git clone --depth 1 https://github.com/ilyas1435/richmp3.git "$HOME/.local/share/richmp3" && \
bash "$HOME/.local/share/richmp3/install_termux.sh"
```

The installer creates a virtual environment, installs Python and FFmpeg
dependencies, and adds `richmp3` to Termux's command path. After installation,
run `richmp3` to open the menu. This initial clone command is for first-time
installation; use `richmp3 update` for later updates.
Run `termux-setup-storage` once and grant access so RichMP3 can save to the
shared Android `Download` folder.

### Install from a local checkout

```bash
python -m pip install -e .
richmp3 version
# or, without installing:
python -m richmp3 version
```

## Quick start

```bash
# Open the interactive menu
richmp3

# Download from the interactive wizard
richmp3 wizard

# Change and save defaults
richmp3 settings

# Check GitHub and safely pull fast-forward updates
richmp3 update

# Show version and all commands
richmp3 version
richmp3 help

# Default: MP3 VBR Q7, 11025 Hz, mono, ZIP enabled
richmp3 "https://www.youtube.com/playlist?list=..."

# Several URLs in one run
richmp3 URL1 URL2

# Higher quality, no archive
richmp3 --mode abr -b 64 -r 22050 --no-zip URL

# Choose another MP3 mode
richmp3 --mode abr -b 24 URL
richmp3 --mode cbr -b 32 URL
richmp3 --mode vbr --vbr-quality 7 URL

# Better quality per byte at low bitrates (Opus, 8-128 kbps)
richmp3 -f opus -b 24 URL

# List audio languages and choose one
richmp3 languages URL
richmp3 download --choose-audio URL
richmp3 download --audio-language ar URL

# Preview planned filenames; touches nothing and needs no FFmpeg
richmp3 --dry-run URL

# Slow connection
richmp3 --limit-rate 300k --workers 2 URL

# Restricted / age-gated media
richmp3 --cookies ~/cookies.txt URL
```

On Termux, the default output is `~/storage/shared/Download`; run
`termux-setup-storage` and grant access once. On other systems it defaults to
`./downloads`.

The wizard offers MP3 VBR, ABR and CBR modes, speech-quality presets, phone
workload presets, an output directory, audio language, and an optional ZIP.
Its default lecture profile is VBR Q7 at 11025 Hz. The maximum-speed preset
uses up to 8 download workers, 8 encoders, and 16 media fragments; it can use
more battery and warm the phone. Choose balanced or battery saver to reduce
load. MP3 is chosen instead of Opus for broad compatibility with older
players. Wizard choices apply to that run; normal configuration-file and CLI
options remain available.

The saved settings menu stores choices in the active `richmp3.toml` or the
user config at `~/.config/richmp3/config.toml`. Run `richmp3 settings` to edit
them; command-line options still override saved values.

`richmp3 update` checks the configured GitHub upstream and pulls
only when the checkout is clean and can be fast-forwarded. It never stashes,
resets, or merges conflicting work. If dependencies change, it tells you to
reinstall them in the project environment. Restart RichMP3 after an update.
The updater requires running from a Git checkout with an upstream branch
configured; a wheel-only installation cannot update its source files.

From the interactive console, use `:settings` (or `:s`) to change saved
defaults, `:update` to check and pull, and `:menu` to start a download using
one-time settings.

Track-row percentages show progress within that track's current phase.
Overall run progress also accounts for later conversion and cleanup work, so
it can stay near 62% after a download finishes and the audio is being encoded.

Exit codes: `0` success, `1` one or more failures, `2` setup error
(missing FFmpeg, bad options), `130` interrupted.

## How the defaults work

| Setting | Default | Notes |
| --- | --- | --- |
| MP3 mode | VBR | `vbr` (default), `abr`, or `cbr` |
| VBR quality | `7` | LAME scale 0–9; lower is clearer and creates larger files |
| bitrate | `24` kbps | used for ABR/CBR and Opus; ignored for MP3 VBR |
| sample rate | `11025` Hz | `11000` is not a legal MP3 rate, so input snaps to the closest legal rate; Opus defaults to 12000 Hz |
| channels | mono | always `-ac 1` |
| MP3 encoder speed | fastest | LAME `-compression_level 9` |
| voice filter | on at ≤16 kHz | `highpass=100, lowpass=5000`; off with `--no-voice-filter` |
| container | MP3 | `--format opus` produces Ogg/Opus |
| download workers | `8` | parallel tracks; lower with `--workers` if needed |
| encode workers | CPU cores, max 8 | parallel FFmpeg processes (`-threads 1` each) |
| concurrent fragments | `16` | parallel HLS/DASH fragment fetches |
| audio language | `original` | prefers original; use `richmp3 languages URL` to list alternatives |
| ZIP | on | `stored` by default (audio does not compress) |
| source folder | removed after ZIP | `--keep-folder` keeps it |

VBR is the default and uses LAME's `-q:a` quality scale. Use `--mode abr` to
target an average bitrate, or `--mode cbr` for a fixed bitrate. For VBR, set
`--vbr-quality 0-9`; lower values improve clarity and increase file size.
ABR and CBR use `--bitrate`.

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
output = "~/storage/shared/Download" # Termux; use "downloads" elsewhere
bitrate = 24
vbr_quality = 7
sample_rate = 11025
format = "mp3"        # mp3 | opus
audio_language = "original" # original, or a code such as en or ar
mode = "vbr"          # vbr | abr | cbr
voice_filter = true   # strip rumble/hiss at <=16 kHz
download_workers = 8
convert_workers = 8
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
concurrent_fragments = 16
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
  pipeline.py     lazy metadata -> download pool -> encode pool, ZIP
  utils.py        names, rates, formatting, process control, logging
tests/            unit + real-FFmpeg integration tests
```

The pipeline is intentionally dependency-injected at the seams
(`downloader` and `converter` attributes), so tests run the whole orchestration
without network access. `python -m unittest discover -s tests -v` covers naming,
config snapping, FFmpeg commands, a real encode, ZIP behaviour, retries,
cancellation and every UI render width.

## Performance notes on Android/Termux

- Shared storage (`/storage/emulated/0`) is FUSE-backed. The maximum-speed
  preset uses 8 track downloads and up to 8 encoders; choose balanced or
  battery saver if the phone warms up or storage becomes a bottleneck.
- Downloads and encodes run in separate pools. A slow encode never idles a
  download worker, so playlists stay network-saturated until the last file.
- Downloads are network-bound and fragmented media (`concurrent_fragments = 16`)
  benefits from parallelism; reduce it with `--fragments` if the connection is
  unstable.
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
