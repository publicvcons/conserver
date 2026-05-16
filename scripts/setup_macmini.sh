#!/usr/bin/env bash
#
# setup_macmini.sh
#
# Idempotent installer for the PublicVCons Mac mini toolchain.
#
# What this installs and where:
#
#   Internal SSD
#     /opt/homebrew                      Homebrew (Apple Silicon) or /usr/local (Intel)
#     ~/Code/whisper.cpp                 whisper.cpp source and built `main` binary
#     ~/venvs/pvcons                     Python 3.12 virtualenv with pyannote.audio
#     ~/.publicvcons.env                 environment variables for the pipeline
#
#   External APFS drive at /Volumes/publicvcons
#     models/whisper-cpp/                whisper large-v3 GGML model (~3 GB)
#     models/ollama/                     Ollama model store (llama3.1:8b q4, ~5 GB)
#
# Re-run is safe. Steps that detect existing artifacts are skipped.
#
# Usage:
#   chmod +x setup_macmini.sh
#   ./setup_macmini.sh

set -euo pipefail

EXT_ROOT="/Volumes/publicvcons"
WHISPER_DIR="$HOME/Code/whisper.cpp"
WHISPER_MODEL_DIR="$EXT_ROOT/models/whisper-cpp"
WHISPER_MODEL="$WHISPER_MODEL_DIR/ggml-large-v3.bin"
OLLAMA_MODELS_DIR="$EXT_ROOT/models/ollama"
VENV_DIR="$HOME/venvs/pvcons"
ENV_FILE="$HOME/.publicvcons.env"

# ----- helpers ---------------------------------------------------------------

say() { printf "\n==> %s\n" "$*"; }
warn() { printf "\n!!  %s\n" "$*" >&2; }
need() {
  command -v "$1" >/dev/null 2>&1 || { warn "missing required command: $1"; return 1; }
}

# ----- preflight -------------------------------------------------------------

say "Preflight checks"

if [[ "$(uname)" != "Darwin" ]]; then
  warn "This script targets macOS."
  exit 1
fi

if [[ ! -d "$EXT_ROOT" ]]; then
  warn "External drive not mounted at $EXT_ROOT. Plug it in and try again."
  exit 1
fi

ARCH="$(uname -m)"
say "Detected macOS on $ARCH"

# ----- Homebrew --------------------------------------------------------------

if ! need brew; then
  say "Installing Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ "$ARCH" == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

say "Updating Homebrew"
brew update

# ----- core packages ---------------------------------------------------------

say "Installing brew packages"
brew install --quiet \
  ffmpeg \
  yt-dlp \
  cmake \
  pkg-config \
  python@3.12 \
  ollama

# ----- whisper.cpp -----------------------------------------------------------

mkdir -p "$WHISPER_MODEL_DIR"

if [[ ! -d "$WHISPER_DIR/.git" ]]; then
  say "Cloning whisper.cpp"
  mkdir -p "$(dirname "$WHISPER_DIR")"
  git clone --depth=1 https://github.com/ggerganov/whisper.cpp "$WHISPER_DIR"
else
  say "Updating whisper.cpp"
  git -C "$WHISPER_DIR" pull --ff-only
fi

if [[ ! -x "$WHISPER_DIR/main" && ! -x "$WHISPER_DIR/build/bin/whisper-cli" ]]; then
  say "Building whisper.cpp"
  ( cd "$WHISPER_DIR" && make -j "$(sysctl -n hw.ncpu)" )
fi

if [[ ! -s "$WHISPER_MODEL" ]]; then
  say "Downloading whisper large-v3 model (about 3 GB) to $WHISPER_MODEL_DIR"
  ( cd "$WHISPER_DIR" && bash ./models/download-ggml-model.sh large-v3 )
  mv "$WHISPER_DIR/models/ggml-large-v3.bin" "$WHISPER_MODEL"
fi

# ----- Ollama ----------------------------------------------------------------

mkdir -p "$OLLAMA_MODELS_DIR"

say "Configuring Ollama to use external model store"
# Set system-wide so Ollama service inherits it, no matter how it was started.
launchctl setenv OLLAMA_MODELS "$OLLAMA_MODELS_DIR"
export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"

# Restart Ollama so the new model store takes effect, even if it was
# already running with the default ~/.ollama path.
if pgrep -x ollama >/dev/null 2>&1; then
  say "Restarting Ollama to pick up OLLAMA_MODELS"
  pkill -x ollama || true
  sleep 2
fi

say "Starting Ollama service in background"
nohup ollama serve >/tmp/ollama.log 2>&1 &
sleep 3

# Sanity check: warn loudly if a stale internal model store still exists.
if [[ -d "$HOME/.ollama/models" && -n "$(ls -A "$HOME/.ollama/models" 2>/dev/null)" ]]; then
  warn "Stale Ollama models still present at $HOME/.ollama/models"
  warn "Run: rm -rf $HOME/.ollama/models   then re-run this script"
fi

if ! ollama list 2>/dev/null | grep -q "llama3.1:8b-instruct-q4_K_M"; then
  say "Pulling llama3.1:8b-instruct-q4_K_M (about 5 GB)"
  ollama pull llama3.1:8b-instruct-q4_K_M
fi

# ----- Python venv -----------------------------------------------------------

if [[ ! -d "$VENV_DIR" ]]; then
  say "Creating Python venv at $VENV_DIR"
  mkdir -p "$(dirname "$VENV_DIR")"
  python3.12 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

say "Installing Python packages into venv"
pip install --upgrade pip wheel
pip install \
  "pyannote.audio>=3.1,<4" \
  "torch>=2.2" \
  "torchaudio>=2.2" \
  "huggingface_hub>=0.24" \
  pyyaml \
  jsonschema \
  requests

deactivate

# ----- env file --------------------------------------------------------------

say "Writing env file at $ENV_FILE"
cat > "$ENV_FILE" <<EOF
# PublicVCons pipeline environment. Source this from your shell rc.
export PUBLICVCONS_ROOT="$EXT_ROOT"
export PUBLICVCONS_DATA="$EXT_ROOT/data"
export PUBLICVCONS_MEDIA="$EXT_ROOT/media"
export PUBLICVCONS_WORK="$EXT_ROOT/work"
export WHISPER_DIR="$WHISPER_DIR"
export WHISPER_MODEL="$WHISPER_MODEL"
export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
export PVCONS_VENV="$VENV_DIR"
# Hugging Face token for pyannote, set after you create the token:
#   export HUGGING_FACE_HUB_TOKEN="hf_..."
EOF

ZSHRC="$HOME/.zshrc"
SOURCE_LINE="[ -f \"$ENV_FILE\" ] && source \"$ENV_FILE\""
if ! grep -Fq "$SOURCE_LINE" "$ZSHRC" 2>/dev/null; then
  say "Adding source line to $ZSHRC"
  printf "\n# PublicVCons pipeline\n%s\n" "$SOURCE_LINE" >> "$ZSHRC"
fi

# ----- summary ---------------------------------------------------------------

say "Toolchain install complete"
cat <<EOF

Installed:
  ffmpeg, yt-dlp, cmake, python@3.12, ollama   (Homebrew)
  whisper.cpp at $WHISPER_DIR (built)
  whisper large-v3 at $WHISPER_MODEL
  llama3.1:8b-instruct-q4_K_M in $OLLAMA_MODELS_DIR
  pyannote.audio venv at $VENV_DIR

Next steps:
  1. Open a new shell window so $ENV_FILE is sourced
  2. Create a Hugging Face token and accept pyannote model terms
       https://huggingface.co/settings/tokens
       https://huggingface.co/pyannote/speaker-diarization-3.1
  3. Add the token to $ENV_FILE:
       export HUGGING_FACE_HUB_TOKEN="hf_..."
  4. Verify each tool:
       ffmpeg -version | head -1
       yt-dlp --version
       "\$WHISPER_DIR/main" --help | head -3
       ollama list
       source "\$PVCONS_VENV/bin/activate" && python -c "import pyannote.audio; print(pyannote.audio.__version__)"

When all four print versions cleanly you are ready for the end to end run.
EOF
