#!/usr/bin/env bash
# One-time setup on macOS (Apple Silicon or Intel).
# Installs into its own virtualenv (~/.tripshots/venv) pinned to Python 3.12, so it
# doesn't depend on pipx's shared pip or on whatever the newest Homebrew Python is
# (librosa/numba often lag behind brand-new Python releases).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HOME/.tripshots/venv"
BIN="$HOME/.local/bin"

# renamed from reelmaker: move the old settings, library and caches over, drop the old command
if [ -d "$HOME/.reelmaker" ] && [ ! -L "$HOME/.reelmaker" ] && [ ! -e "$HOME/.tripshots" ]; then
  echo "==> Moving ~/.reelmaker to ~/.tripshots (your library, looks, styles and settings come along)"
  mv "$HOME/.reelmaker" "$HOME/.tripshots"
  [ -f "$HOME/.tripshots/.env" ] && sed -i '' 's/^\([# ]*\)REELMAKER_/\1TRIPSHOTS_/' "$HOME/.tripshots/.env"
fi
[ -L "$HOME/.reelmaker" ] && rm "$HOME/.reelmaker"
[ -L "$BIN/reelmaker" ] && rm "$BIN/reelmaker"

if ! command -v brew >/dev/null; then
  echo "Install Homebrew first: https://brew.sh"; exit 1
fi

echo "==> Installing ffmpeg, yt-dlp and Python 3.12 (Homebrew)"
brew install ffmpeg yt-dlp python@3.12

PY="$(brew --prefix python@3.12)/bin/python3.12"
[ -x "$PY" ] || { echo "python3.12 not found at $PY"; exit 1; }

echo "==> Creating virtualenv at $VENV"
rm -rf "$VENV"
"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade --quiet pip setuptools wheel

echo "==> Installing TripShots"
"$VENV/bin/python" -m pip install --quiet "$HERE" pillow-heif "rembg[cpu]" google-genai opentimelineio

mkdir -p "$BIN"
ln -sf "$VENV/bin/tripshots" "$BIN/tripshots"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) SHELLRC="$HOME/.zshrc"; [ -n "${BASH_VERSION:-}" ] && [ "$SHELL" = "/bin/bash" ] && SHELLRC="$HOME/.bash_profile"
     grep -q 'tripshots: local bin' "$SHELLRC" 2>/dev/null || \
       printf '\n# tripshots: local bin\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$SHELLRC"
     echo "Added ~/.local/bin to PATH in $SHELLRC (open a new terminal)";;
esac

mkdir -p "$HOME/.tripshots"
# optional: earshot's sound bank (sound effects built in code, offline; MIT) - NOT the unrelated
# "earshot" package on PyPI, so it is installed from GitHub at a pinned commit, without torch.
EARSHOT="earshot @ git+https://github.com/Leonxlnx/earshot@591fa3e028032e6dce56620a20e932e35667e8d8"
if [[ " $* " == *" --sound "* || " $* " == *" --sound-ears "* ]]; then
  echo "==> Sound: earshot sound bank"
  "$VENV/bin/python" -m pip install --quiet scipy soundfile soxr librosa pyloudnorm
  "$VENV/bin/python" -m pip install --quiet --no-deps "$EARSHOT" && echo "earshot sound bank ready" || echo "earshot install failed (optional)"
fi
if [[ " $* " == *" --sound-ears "* ]]; then
  echo "==> Sound: earshot's listening models (CPU torch, ~1.1 GB of models on first use)"
  "$VENV/bin/python" -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
  "$VENV/bin/python" -m pip install --quiet "transformers>=4.40" scikit-learn matplotlib
fi
[ "${TRIPSHOTS_OFFLINE:-}" = "1" ] || { "$BIN/tripshots" sounds --fetch >/dev/null 2>&1 && echo "real sound effects fetched (Openverse, CC0)" || true; }
if [[ " $* " == *" --maps "* ]] || [ -d "$HOME/.tripshots/hyperframes/node_modules" ]; then
  echo "==> Route-map layer: Node.js + HyperFrames"
  brew install node
  "$BIN/tripshots" maps --setup >/dev/null && echo "route map ready" || echo "route map setup failed (optional; see: tripshots maps)"
fi
[ -f "$HOME/.tripshots/.env" ] || cp "$HERE/.env.example" "$HOME/.tripshots/.env"

echo
"$BIN/tripshots" doctor || true
echo
echo "Done. Try:  tripshots make ~/path/to/trip --music song.mp3"
echo "Optional: ./install.sh --maps (route maps)  --sound (earshot sound bank)  --sound-ears (earshot listening)"
echo "To update after changing the code:  ./install.sh  (re-run any time)"
