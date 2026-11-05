#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
APP="$ROOT_DIR/build/VanishCam.app"
SOURCE="$ROOT_DIR/local_app/VanishCamMenu.swift"
EXECUTABLE="$APP/Contents/MacOS/VanishCamMenu"

if [[ ! -x "$EXECUTABLE" || "$SOURCE" -nt "$EXECUTABLE" || "$ROOT_DIR/local_app/VanishCamMenu-Info.plist" -nt "$EXECUTABLE" || "$ROOT_DIR/local_app/BuildMenuIcon.swift" -nt "$EXECUTABLE" ]]; then
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  /usr/bin/swift "$ROOT_DIR/local_app/BuildMenuIcon.swift" "$ROOT_DIR/build/VanishCam.iconset"
  /usr/bin/iconutil -c icns "$ROOT_DIR/build/VanishCam.iconset" -o "$APP/Contents/Resources/VanishCam.icns"
  /usr/bin/swiftc -swift-version 5 -parse-as-library "$SOURCE" -o "$EXECUTABLE"
  cp "$ROOT_DIR/local_app/VanishCamMenu-Info.plist" "$APP/Contents/Info.plist"
  /usr/bin/codesign --force --sign - "$APP"
fi
/usr/bin/open "$APP"
