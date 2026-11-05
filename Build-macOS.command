#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/python@3.12/bin:$PATH"
PYTHON="$ROOT_DIR/.venv-local/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  python3.12 -m venv "$ROOT_DIR/.venv-local"
fi
"$PYTHON" -m pip install -r local_app/requirements-build-macos.txt
mkdir -p build/macos dist/macos
"$PYTHON" -m PyInstaller --noconfirm \
  --workpath build/macos/pyinstaller --distpath dist/macos \
  local_app/VanishCam-macOS.spec
APP="$ROOT_DIR/dist/macos/VanishCam.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
/usr/bin/ditto dist/macos/VanishCamEngine "$APP/Contents/Resources/Engine"
/usr/bin/swift local_app/BuildMenuIcon.swift build/macos/VanishCam.iconset
/usr/bin/iconutil -c icns build/macos/VanishCam.iconset -o "$APP/Contents/Resources/VanishCam.icns"
/usr/bin/swiftc -swift-version 5 -parse-as-library local_app/VanishCamMenu.swift \
  -o "$APP/Contents/MacOS/VanishCamMenu"
cp local_app/VanishCamMenu-Info.plist "$APP/Contents/Info.plist"
/usr/bin/codesign --force --deep --sign - "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
echo "Built standalone app: $APP"
echo "Open it in Finder. No external Python, FFmpeg or repository is needed at runtime."
