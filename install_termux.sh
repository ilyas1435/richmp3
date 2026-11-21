#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [[ -z "${PREFIX:-}" ]] || ! command -v pkg >/dev/null 2>&1; then
  echo "This installer is for Termux. Install manually using the README instructions."
  exit 1
fi

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${RICHMP3_VENV_DIR:-$HOME/.venvs/richmp3}"
COMMAND_LINK="$PREFIX/bin/richmp3"

if [[ ! -f "$REPO_DIR/pyproject.toml" || ! -d "$REPO_DIR/.git" ]]; then
  echo "Run this installer from a Git checkout of RichMP3."
  exit 1
fi

mkdir -p "$PREFIX/bin"
if [[ -e "$COMMAND_LINK" && ! -L "$COMMAND_LINK" ]]; then
  echo "Cannot install: $COMMAND_LINK already exists and is not a symlink."
  exit 1
fi

pkg install -y python ffmpeg git nodejs
python -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --editable "$REPO_DIR"

ln -sfn "$VENV_DIR/bin/richmp3" "$COMMAND_LINK"

echo "RichMP3 installed. Start it with: richmp3"
"$COMMAND_LINK" version
