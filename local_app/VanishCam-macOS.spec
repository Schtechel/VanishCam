"""Folder-based frozen engine embedded in the native Mac application."""

from pathlib import Path
import shutil
from PyInstaller.utils.hooks import collect_dynamic_libs

root = Path(SPECPATH).resolve()
ffmpeg = shutil.which("ffmpeg")
if ffmpeg is None:
    raise SystemExit("Install FFmpeg before building the macOS app.")
resources = [
    (str(root / name), ".")
    for name in ("hand_landmarker.task", "face_landmarker.task")
] + [(str(root / "models"), "models"), (str(root / "assets"), "assets")]
a = Analysis(
    [str(root / "mac_engine.py")],
    pathex=[str(root)],
    binaries=collect_dynamic_libs("mediapipe") + [(ffmpeg, ".")],
    datas=resources,
    hiddenimports=["pygame.mixer", "mediapipe.tasks.c", "pyvirtualcam"],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="VanishCamEngine",
    console=True, strip=False, upx=False, target_arch="arm64",
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name="VanishCamEngine",
)
