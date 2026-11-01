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
