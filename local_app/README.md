# VanishCam — AI Webcam Meme & Disappearance Effects

VanishCam is an AI-powered real-time webcam effects suite that runs entirely locally on your device. Video is processed in real time using MediaPipe computer vision models — frames are never recorded or sent to any cloud server. The clean preview window and virtual camera output feed directly into video conferencing tools (Zoom, Google Meet, Teams, Discord, etc.) or streaming software like OBS Studio without any overlaid watermarks, menus, or debug text.

---

## Features

- **Universal All-In-One Mode**: Seamlessly switch between or trigger any meme move dynamically in real time without needing to switch modes:
  - **Goku Instant Transmission**: Place two joined fingers (index and middle) at your forehead or temple to charge Ki and teleport away with authentic anime speed lines and sound effects. Teleport back after a 2-second cooldown with the same gesture!
  - **Naruto Substitution Jutsu**: Bring both palms firmly together in a classic jutsu pose to vanish instantly in a cloud of smoke, leaving behind a falling wooden substitution log.
  - **Normal Vanish**: Flash a steady peace sign (V-sign) with one hand to dissolve gracefully into your background.
- **Mutual Exclusion & Stillness Recognition**: Strict spatial and geometric gesture classification ensures no accidental false triggers between moves.
- **OBS Studio & Virtual Webcam Support**: Direct integration via `pyvirtualcam` to output as a virtual camera, or capture the clean preview window in OBS.
- **Hardware Acceleration**: Optimized with CPU vectorization and smooth frame interpolation.

---

## Getting Started

### macOS with Camo Studio

From the repository root, run `./VanishCam.command` (or double-click it in Finder). The command creates an isolated `.venv-local` environment and installs the pinned dependencies on first launch. It selects the AVFoundation device named **Camo Camera**, disables mirroring to preserve the Camo orientation, and requires the **OBS Virtual Camera** backend. The Mac launcher saves one local calibration image in `.local-state/background.png`, ignored by Git, and reuses it on future starts. Use **Reset background** in the menu-bar app or **Space** in the preview to capture a replacement; step out for four seconds. Reset when the camera position, lighting, or room changes. A changed capture resolution triggers recalibration automatically. No video is recorded or uploaded.

Before first use, install OBS Studio, start and stop **OBS Virtual Camera** once in OBS, and then quit OBS so its macOS camera extension is registered. If System Settings reports the extension is waiting for approval, approve it there and restart if prompted. Keep Camo Studio running with the Logitech camera selected. If macOS requests camera access, allow it for the app launching the command. Select **OBS Virtual Camera** in Teams yourself; no Camo or Teams setting is changed here.

The launcher fails rather than falling back to FaceTime or another device if **Camo Camera** is not found. Quit VanishCam with `Q` or `ESC`, and do not stream from OBS while VanishCam is sending frames.

### Quick Start (Windows)

Simply run the batch launchers from the root directory:

- **`START_ALL_CAMERAS.bat`**: Universal launcher. Starts All-In-One mode where all gestures (Goku, Naruto, Peace Sign) are active simultaneously.
- **`START_GOKU.bat`**: Starts directly in Goku Instant Transmission mode.
- **`START_NARUTO.bat`**: Starts directly in Naruto Substitution mode.
- **`START_NORMAL.bat`**: Starts directly in Normal Dissolve mode.
- **`START_OBS.bat`**: Starts with virtual camera disabled, perfect for OBS Window Capture.

### Background Calibration

1. Launch any mode.
2. Step out of the camera frame for 4 seconds so the camera can capture a clean background image.
3. The console will let you know when background calibration is complete, and you can step back in.

---

## Gestures & Controls

### Gesture Triggers

| Effect | Gesture | Details |
| :--- | :--- | :--- |
| **Goku Instant Transmission** | 2 joined fingers at forehead / temple | Hold still for ~0.25s to charge Ki aura, then teleports away. Hold again after 2s cooldown to reappear. |
| **Naruto Substitution Jutsu** | Both palms joined together (jutsu pose) | Requires both hands with palms and fingertips touching. Leaves a wooden substitution log in smoke. |
| **Normal Vanish** | Single-hand Peace Sign (V-sign) | Single hand held steady in a clear V divergence. Dissolves your silhouette into the background. |

### Keyboard Shortcuts

- `SPACE`: Recalibrate and capture a fresh background (step out of frame for 4 seconds).
- `R`: Reappear manually / reset to ready state.
- `1`: Trigger Normal Dissolve vanish (or reappear).
- `2`: Trigger Naruto Substitution Jutsu (or reappear).
- `3`: Trigger Goku Instant Transmission (or reappear).
- `C`: Cycle to next available webcam index (0, 1, 2, ...).
- `F`: Toggle fullscreen window.
- `Q` or `ESC`: Quit and cleanly release all camera and audio resources.

---

## Virtual Camera & OBS Integration

### Virtual Webcam
If [OBS Studio](https://obsproject.com/) (with the OBS Virtual Camera driver) or [Unity Capture](https://github.com/schellingb/UnityCapture) is installed, VanishCam will automatically output to the virtual camera device. You can then select **OBS Virtual Camera** as your camera in Zoom, Teams, Discord, Google Meet, etc.

To disable the virtual camera and use local preview only:
```powershell
local_app\START_LOCAL.bat --no-virtual-camera
```

### OBS Window Capture
To bring the feed into OBS Studio:
1. Run `local_app\START_OBS.bat` (or pass `--no-virtual-camera`).
2. In OBS Studio, add a **Window Capture** source.
3. Select the window **`Webcam - Preview`**.

---

## CLI Options

```powershell
python local_app/vanish_cam.py [OPTIONS]

Options:
  --camera INT              Webcam index (default: 0)
  --camera-name NAME        Select an AVFoundation camera by name (macOS)
  --width INT               Video capture width (default: 960)
  --height INT              Video capture height (default: 540)
  --fps FLOAT               Max FPS for virtual camera output (default: 30)
  --mode {all,normal,naruto,goku}
                            Active meme mode (default: all)
  --fullscreen              Start in fullscreen mode
  --no-mirror               Do not horizontally mirror the camera feed
  --no-virtual-camera       Disable virtual camera output
  --menu                    Show visual mode selection screen on startup
  --gesture-debug           Print real-time gesture tracking diagnostics to terminal
  --self-test               Verify model assets and audio pipeline without opening a camera
```

---

## Building Executable (Windows)

To build a standalone one-file Windows executable:
```cmd
cd local_app
BUILD_WINDOWS.bat
```
The compiled binary will be placed in `local_app\dist\VanishCam.exe`.
# Standalone macOS app

From the repository root, run `./Build-macOS.command` to produce
`dist/macos/VanishCam.app` for Apple silicon. It embeds its runtime, models,
audio, and FFmpeg dependencies; there is no Terminal or external Python app at
runtime. It captures Logitech or the Mac camera directly, or **Camo Camera**
when you want Camo Studio's adjustments. Camo must be running only for that
input. An enabled OBS Virtual Camera extension is required for output.
See the root README's macOS section for controls, private background
storage, and the development-only launchers.
