#!/bin/bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/opt/python@3.12/bin:$PATH"
ROOT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[VanishCam] ffmpeg is required for Camo-by-name camera selection."
  echo "Install it with: brew install ffmpeg"
  read -r -p "Press Return to close..."
  exit 1
fi

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON="$(command -v python3.12)"
elif [[ -x /opt/homebrew/opt/python@3.12/bin/python3.12 ]]; then
  PYTHON="/opt/homebrew/opt/python@3.12/bin/python3.12"
else
  echo "[VanishCam] Python 3.12 is required. Install it with: brew install python@3.12"
  read -r -p "Press Return to close..."
  exit 1
fi

VENV_DIR="$ROOT_DIR/.venv-local"
VENV_PY="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi

if ! "$VENV_PY" -c 'import cv2, mediapipe, numpy, pyvirtualcam, pygame; from importlib.metadata import version; assert version("mediapipe") == "0.10.35"' >/dev/null 2>&1; then
  echo "[VanishCam] Installing dependencies in the isolated .venv-local environment..."
  "$VENV_PY" -m pip install -r local_app/requirements.txt
fi

exec "$VENV_PY" local_app/vanish_cam.py \
  --camera-name "Camo Camera" \
  --no-mirror \
  --virtual-camera \
  --virtual-backend obs \
  --virtual-device "OBS Virtual Camera" \
  --background-file "$ROOT_DIR/.local-state/background.png" \
  --reset-background-request "$ROOT_DIR/.local-state/reset-background" \
  --show-myself-request "$ROOT_DIR/.local-state/show-myself" \
  "$@"
