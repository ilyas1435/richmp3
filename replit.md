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
  python -m richmp3 wizard
  python -m richmp3 "https://example.org/audio.mp3"
  python -m richmp3 --no-zip -b 64 "https://example.org/audio.mp3"
  python -m richmp3 help
  ```

The command menu's **Download** option asks for a URL and uses saved settings;
**Change and save settings** edits future defaults. Use `richmp3 wizard` for
one-time setup options. In the Run console, enter `:menu` for a one-time setup,
`:settings` to change and save defaults, or `:update` to fast-forward from the
configured GitHub upstream when the checkout is clean. On Termux, install via
`install_termux.sh`, then use `richmp3`, `richmp3 settings`, or `richmp3 update`.

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
python -m richmp3 version
```

The suite includes real FFmpeg conversion tests and offline pipeline tests.
Live third-party downloads depend on the source site's availability and access
rules; passing offline checks does not guarantee access to a particular site.
