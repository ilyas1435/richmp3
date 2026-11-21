# RichMP3 on Replit

This is the imported Python command-line application, not a web service.
Keep its existing structure and stack.

## Run

- Click **Run** to start the **RichMP3** console workflow.
- At `RichMP3>`, enter a media/playlist URL, optionally with CLI flags.
  Enter `--help` for all options, or `quit` to exit.
- URLs containing spaces must be quoted. Enter arguments only, without a
  `python` or `richmp3` command prefix.
- Alternatively, use Shell:

  ```sh
  python -m richmp3 --wizard
  python -m richmp3 "https://example.org/audio.mp3"
  python -m richmp3 --no-zip -b 64 "https://example.org/audio.mp3"
  python -m richmp3 --help
  ```

The wizard offers speech-focused MP3 quality profiles and phone-friendly
download settings. In the Run console, enter `:menu` to open it.

The URLs above are placeholders; replace them with media you have permission
to download. If console input is unavailable, use the Shell commands instead.
The Run launcher delegates to the unchanged CLI.

## Environment

- Python 3.11 is configured in `.replit`.
- Python dependencies are declared in `requirements.txt` and `pyproject.toml`.
- FFmpeg (MP3 and Opus encoding) and Deno (yt-dlp JavaScript challenges) are
  configured as Nix packages in `.replit`.
- No API keys or other secrets are required for public media. Some sites
  require cookies or reject cloud-hosted traffic. Do not commit cookie files;
  supply private cookies only if needed using the existing `--cookies` option.
- Downloads and playlist ZIPs go to `downloads/` by default (ignored by Git).
  Retrieve output files from the file tree.
- There is no web preview or web deployment to configure.

## Check

```sh
python -m unittest discover -s tests -v
python -m richmp3 --version
```

The suite includes real FFmpeg conversion tests and offline pipeline tests.
Live third-party downloads depend on the source site's availability and access
rules; passing offline checks does not guarantee access to a particular site.
