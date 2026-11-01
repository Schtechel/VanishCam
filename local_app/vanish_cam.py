"""Local webcam: dissolve effect triggered by index and middle finger V gesture."""

from __future__ import annotations

import argparse
import math
import os
import platform
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

try:
    from .goku_effect import (
        GOKU_HOLD_SECONDS, GOKU_TELEPORT_SECONDS, TELEPORT_SOUND_PATH,
        goku_pose_from_landmarks, render_goku_charging, render_goku_teleport,
    )
    from .naruto_effect import (
        EFFECT_SECONDS, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_substitution, substitution_anchor,
    )
    from .vanish_sound import SOUND_PATH, VanishSound
except ImportError:
    from goku_effect import (
        GOKU_HOLD_SECONDS, GOKU_TELEPORT_SECONDS, TELEPORT_SOUND_PATH,
        goku_pose_from_landmarks, render_goku_charging, render_goku_teleport,
    )
    from naruto_effect import (
        EFFECT_SECONDS, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_substitution, substitution_anchor,
    )
    from vanish_sound import SOUND_PATH, VanishSound


APP_DIR = Path(__file__).resolve().parent
MODEL_DIR = APP_DIR / "models"
WINDOW_NAME = "Webcam - Preview"

SEGMENTER_MODEL = MODEL_DIR / "selfie_segmenter_landscape.tflite"
GESTURE_MODEL = MODEL_DIR / "gesture_recognizer.task"
HAND_MODEL = APP_DIR / "hand_landmarker.task"
FACE_MODEL = APP_DIR / "face_landmarker.task"

MODEL_URLS = {
    SEGMENTER_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_segmenter_landscape/float16/latest/"
        "selfie_segmenter_landscape.tflite"
    ),
    GESTURE_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
        "gesture_recognizer/float16/1/gesture_recognizer.task"
    ),
}

CALIBRATION_SECONDS = 4.0
BACKGROUND_SAMPLE_SECONDS = 0.55
VANISH_SECONDS = 3.6
GESTURE_INTERVAL_SECONDS = 0.14
PEACE_HOLD_SECONDS = 0.25
PEACE_MAX_DRIFT = 0.040


@dataclass
class AppState:
    phase: str = "calibrating"
    calibration_started: float = 0.0
    vanish_started: float | None = None
    last_gesture_check: float = 0.0
    fullscreen: bool = False


def positive_fps(value: str) -> float:
    fps = float(value)
    if not np.isfinite(fps) or not 1 <= fps <= 120:
        raise argparse.ArgumentTypeError("FPS must be between 1 and 120.")
    return fps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VanishCam: All-In-One Universal Meme Camera (Goku, Naruto, Normal Vanish)."
    )
    parser.add_argument("--camera", type=int, default=0, help="Webcam index")
    parser.add_argument("--width", type=int, default=960, help="Video width")
    parser.add_argument("--height", type=int, default=540, help="Video height")
    parser.add_argument(
        "--fullscreen", action="store_true", help="Start in fullscreen mode"
    )
    parser.add_argument(
        "--no-mirror", action="store_true", help="Do not mirror the webcam"
    )
    parser.add_argument("--fps", type=positive_fps, default=30.0, help="Maximum FPS for virtual output (default: 30)")
    parser.add_argument(
        "--virtual-camera", action=argparse.BooleanOptionalAction, default=None,
        help="Require virtual webcam; enabled by default if available. --no-virtual-camera disables it",
    )
    parser.add_argument(
        "--virtual-backend", choices=("obs", "unitycapture", "v4l2loopback"),
        help="Virtual webcam driver to use",
    )
    parser.add_argument("--virtual-device", help="Name of the virtual device to use")
    parser.add_argument(
        "--mode", choices=("all", "normal", "naruto", "goku"), default="all",
        help="Effect mode (default: all - all memes active simultaneously)",
    )
    parser.add_argument(
        "--menu", action="store_true",
        help="Show the visual selection menu instead of starting immediately",
    )
    parser.add_argument(
        "--gesture-debug", action="store_true",
        help="Print gesture recognition status to the terminal (no text on video)",
    )
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def choose_mode() -> str | None:
    """Simple keyboard/mouse menu shown before the clean camera feed."""
    title = "Choose Effect"
    selected = [None]
    window = np.zeros((560, 720, 3), dtype=np.uint8)
    window[:] = (26, 29, 34)
    cv2.putText(window, "VANISHCAM - CHOOSE MODE", (68, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (236, 239, 242), 2, cv2.LINE_AA)
    buttons = (
        ("all",    "0  ALL-IN-ONE (ALL MEMES)", "All gestures active: Goku, Naruto and V-Sign", 80),
        ("normal", "1  NORMAL VANISH",             "V-Sign  /  dissolve", 195),
        ("naruto", "2  NARUTO VANISH",             "Joined hands  /  log and smoke", 310),
        ("goku",   "3  GOKU VANISH",               "2 fingers to forehead  /  teleport", 425),
    )
    for mode, heading, detail, top in buttons:
        color = (58, 70, 85) if mode == "all" else (48, 54, 62)
        border = (120, 190, 220) if mode == "all" else (111, 142, 153)
        cv2.rectangle(window, (65, top), (655, top + 92), color, -1, cv2.LINE_AA)
        cv2.rectangle(window, (65, top), (655, top + 92), border, 2, cv2.LINE_AA)
        cv2.putText(window, heading, (90, top + 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.77, (240, 245, 247), 2, cv2.LINE_AA)
        cv2.putText(window, detail, (90, top + 66),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.53, (179, 195, 201), 1, cv2.LINE_AA)

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONUP and 65 <= x <= 655:
            for mode, _, _, top in buttons:
                if top <= y <= top + 92:
                    selected[0] = mode

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, on_mouse)
    try:
        while selected[0] is None:
            cv2.imshow(title, window)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("0"), ord("a"), 13, ord(" ")):
                selected[0] = "all"
            elif key == ord("1"):
                selected[0] = "normal"
            elif key == ord("2"):
                selected[0] = "naruto"
            elif key == ord("3"):
                selected[0] = "goku"
            elif key in (ord("q"), 27):
                return None
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return None
        return selected[0]
    finally:
        cv2.destroyWindow(title)


def open_virtual_camera(args: argparse.Namespace, width: int, height: int):
    if args.virtual_camera is False:
        return None
    try:
        import pyvirtualcam

        camera = pyvirtualcam.Camera(
            width=width, height=height, fps=args.fps,
            fmt=pyvirtualcam.PixelFormat.BGR,
            backend=args.virtual_backend, device=args.virtual_device,
        )
    except (ImportError, RuntimeError, OSError, ValueError) as error:
        message = (
            "Virtual webcam not available. Install OBS Studio (with the "
            "OBS Virtual Camera driver) or Unity Capture. If using OBS Virtual Camera, "
            "stop 'Start Virtual Camera' in OBS. "
            "Run START_LOCAL.bat to install pyvirtualcam. "
            f"Details: {error}"
        )
        if args.virtual_camera is True or args.virtual_backend or args.virtual_device:
            raise RuntimeError(message) from error
        print(f"[Webcam] {message}\n[Webcam] Continuing with local preview only.")
        return None
    print(f"[Webcam] Virtual output active: {camera.device} ({width}x{height}, {args.fps:g} max FPS)")
    return camera


def send_virtual_frame(camera, frame: np.ndarray) -> None:
    if frame.shape[:2] != (camera.height, camera.width):
        frame = cv2.resize(frame, (camera.width, camera.height), interpolation=cv2.INTER_LINEAR)
    camera.send(np.ascontiguousarray(frame))


def download_models(mode: str = "normal") -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for destination, url in MODEL_URLS.items():
        if (mode in ("naruto", "goku")) and destination == GESTURE_MODEL:
            continue
        if destination.exists() and destination.stat().st_size > 100_000:
            continue

        temporary = destination.with_suffix(destination.suffix + ".part")
        print(f"[VanishCam] Downloading {destination.name}...")
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "VanishCam/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length", 0))
                received = 0
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 256):
                        output.write(chunk)
                        received += len(chunk)
                        if total:
                            percent = int(received * 100 / total)
                            print(f"\r  {percent:3d}%", end="", flush=True)
            print()
            os.replace(temporary, destination)
        except (OSError, urllib.error.URLError) as error:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(
                "Unable to download MediaPipe models. "
                "Please check your internet connection and try again."
            ) from error


def open_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    if platform.system() == "Windows":
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(index)
    else:
        capture = cv2.VideoCapture(index)

    if not capture.isOpened():
        raise RuntimeError(
            f"Webcam {index} unavailable. Close other applications or try --camera 1."
        )

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def create_tasks(mode: str = "all") -> tuple[vision.ImageSegmenter, Any]:
    segmenter_options = vision.ImageSegmenterOptions(
        base_options=python.BaseOptions(model_asset_path=str(SEGMENTER_MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        output_confidence_masks=True,
        output_category_mask=False,
    )
    if mode == "all":
        if not GESTURE_MODEL.is_file():
            raise RuntimeError(f"Gesture model not found: {GESTURE_MODEL}")
        if not FACE_MODEL.is_file():
            raise RuntimeError(f"Face model not found: {FACE_MODEL}")
        gesture_options = vision.GestureRecognizerOptions(
            base_options=python.BaseOptions(model_asset_path=str(GESTURE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.20,
            min_hand_presence_confidence=0.20,
            min_tracking_confidence=0.35,
        )
        face_options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(FACE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.30,
            min_face_presence_confidence=0.30,
            min_tracking_confidence=0.40,
        )
        segmenter = vision.ImageSegmenter.create_from_options(segmenter_options)
        try:
            gesture_task = vision.GestureRecognizer.create_from_options(gesture_options)
            try:
                alt_task = vision.GestureRecognizer.create_from_options(
                    replace(gesture_options, running_mode=vision.RunningMode.IMAGE)
                )
                try:
                    face_task = vision.FaceLandmarker.create_from_options(face_options)
                except Exception:
                    alt_task.close()
                    raise
            except Exception:
                gesture_task.close()
                raise
        except Exception:
            segmenter.close()
            raise
        return segmenter, UniversalTracker(gesture_task, face_task, alt_task)
    elif mode == "naruto":
        if not HAND_MODEL.is_file():
            raise RuntimeError(f"Hand model not found: {HAND_MODEL}")
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.20,
            min_hand_presence_confidence=0.20,
            min_tracking_confidence=0.35,
        )
        task_class = vision.HandLandmarker
        wrapper_class = MultiViewHandLandmarker
    elif mode == "goku":
        if not HAND_MODEL.is_file():
            raise RuntimeError(f"Hand model not found: {HAND_MODEL}")
        if not FACE_MODEL.is_file():
            raise RuntimeError(f"Face model not found: {FACE_MODEL}")
        hand_options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.20,
            min_hand_presence_confidence=0.20,
            min_tracking_confidence=0.35,
        )
        face_options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(FACE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.35,
            min_face_presence_confidence=0.35,
            min_tracking_confidence=0.45,
        )
        segmenter = vision.ImageSegmenter.create_from_options(segmenter_options)
        try:
            hand_task = vision.HandLandmarker.create_from_options(hand_options)
            try:
                face_task = vision.FaceLandmarker.create_from_options(face_options)
            except Exception:
                hand_task.close()
                raise
        except Exception:
            segmenter.close()
            raise
        return segmenter, GokuTracker(hand_task, face_task)
    else:
        options = vision.GestureRecognizerOptions(
            base_options=python.BaseOptions(model_asset_path=str(GESTURE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.20,
            min_hand_presence_confidence=0.20,
            min_tracking_confidence=0.35,
        )
        task_class = vision.GestureRecognizer
        wrapper_class = MultiViewGestureRecognizer

    segmenter = vision.ImageSegmenter.create_from_options(segmenter_options)
    try:
        primary = task_class.create_from_options(options)
        try:
            alternate = task_class.create_from_options(
                replace(options, running_mode=vision.RunningMode.IMAGE)
            )
        except Exception:
            primary.close()
            raise
    except Exception:
        segmenter.close()
        raise
    return segmenter, wrapper_class(primary, alternate)


def smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    values = np.clip((values - edge0) / max(edge1 - edge0, 1e-6), 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def ease_in_out_cubic(value: float) -> float:
    if value < 0.5:
        return 4.0 * value * value * value
    return 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0


def make_dissolve_fields(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7391)
    y, x = np.mgrid[0:height, 0:width]
    y_normal = y.astype(np.float32) / max(height - 1, 1)
    x_normal = x.astype(np.float32) / max(width - 1, 1)
    low_noise = rng.random((max(2, height // 10), max(2, width // 10)), dtype=np.float32)
    low_noise = cv2.resize(low_noise, (width, height), interpolation=cv2.INTER_CUBIC)
    fine_noise = rng.random((height, width), dtype=np.float32)
    field = (
        (1.0 - y_normal) * 0.72
        + low_noise * 0.17
        + fine_noise * 0.08
        + np.sin(x_normal * 18.0) * 0.025
    )
    return np.clip(field, 0.0, 1.0), fine_noise


def person_mask(
    segmenter: vision.ImageSegmenter,
    image: mp.Image,
    timestamp_ms: int,
    width: int,
    height: int,
) -> np.ndarray:
    result = segmenter.segment_for_video(image, timestamp_ms)
    if not result.confidence_masks:
        return np.zeros((height, width), dtype=np.float32)
    raw = np.squeeze(result.confidence_masks[0].numpy_view()).astype(np.float32)
    resized = cv2.resize(raw, (width, height), interpolation=cv2.INTER_LINEAR)
    resized = cv2.GaussianBlur(resized, (0, 0), sigmaX=2.0, sigmaY=2.0)
    mask = np.clip(resized / 0.55, 0.0, 1.0)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.dilate(mask, kernel)
    return mask


def alpha_composite(person: np.ndarray, background: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    alpha_3 = alpha[:, :, None]
    return (
        person.astype(np.float32) * alpha_3
        + background.astype(np.float32) * (1.0 - alpha_3)
    ).astype(np.uint8)


def apply_dissolve(
    frame: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray,
    progress: float,
    field: np.ndarray,
    sparkle_noise: np.ndarray,
) -> np.ndarray:
    if progress <= 0.002:
        return alpha_composite(frame, background, mask)
    if progress >= 0.999:
        return background.copy()

    points = cv2.findNonZero((mask > 0.01).astype(np.uint8))
    if points is None:
        return background.copy()
    x, y, width, height = cv2.boundingRect(points)
    left, top = max(0, x - 18), max(0, y - 18)
    right = min(mask.shape[1], x + width + 18)
    bottom = min(mask.shape[0], y + height + 18)
    area = np.s_[top:bottom, left:right]
    mask = mask[area]
    field = field[area]
    sparkle_noise = sparkle_noise[area]
    eased = ease_in_out_cubic(progress)
    survival = smoothstep(eased - 0.055, eased + 0.055, field)
    alpha = mask * survival
    output = alpha_composite(frame[area], background[area], alpha)
    edge = (
        (np.abs(field - eased) < 0.018)
        & (mask > 0.48)
        & (sparkle_noise > 0.54)
    ).astype(np.float32)
    glow = cv2.GaussianBlur(edge, (0, 0), sigmaX=5.0, sigmaY=5.0)
    glow = np.clip(glow * 5.0 + edge, 0.0, 1.0)[:, :, None]
    cyan = np.full_like(output, (255, 228, 92), dtype=np.uint8)
    result = np.clip(
        output.astype(np.float32) * (1.0 - glow * 0.8)
        + cyan.astype(np.float32) * glow * 0.8,
        0,
        255,
    ).astype(np.uint8)
    canvas = background.copy()
    canvas[area] = result
    return canvas


def victory_landmark_score(points: np.ndarray) -> float:
    """Recognize extended index and middle fingers using 3D distances, independent of orientation."""
    if points.shape != (21, 3) or not np.isfinite(points).all():
        return 0.0

    straightness = []
    extended = []
    folded = []
    lengths = []
    for index, base in enumerate((5, 9, 13, 17)):
        finger = points[base : base + 4]
        length = float(np.linalg.norm(np.diff(finger, axis=0), axis=1).sum())
        if length < 1e-6:
            if index < 2:
                return 0.0
            straightness.append(0.0)
            lengths.append(0.0)
            extended.append(False)
            folded.append(True)
            continue
        ratio = float(np.linalg.norm(finger[3] - finger[0])) / length
        tip_distance = float(np.linalg.norm(finger[3] - points[0]))
        joint_distance = float(np.linalg.norm(finger[1] - points[0]))
        straightness.append(ratio)
        lengths.append(length)
        extended.append(ratio >= 0.82 and tip_distance > joint_distance * 1.10)
        folded.append(ratio < 0.78 or tip_distance <= joint_distance * 1.05)

    reference_length = min(lengths[:2])
    for index, base in ((2, 13), (3, 17)):
        reach = float(np.linalg.norm(points[base + 3] - points[base]))
        folded[index] = folded[index] or reach < reference_length * 0.65
    if not (extended[0] and extended[1] and folded[2] and folded[3]):
        return 0.0
    separation = float(np.linalg.norm(points[8] - points[12]))
    if separation < min(lengths[:2]) * 0.20:
        return 0.0

    # In a Victory / Peace sign, index and middle fingers must diverge in a V-shape
    v_idx = points[8] - points[5]
    v_mid = points[12] - points[9]
    norm_idx = np.linalg.norm(v_idx)
    norm_mid = np.linalg.norm(v_mid)
    if norm_idx < 1e-6 or norm_mid < 1e-6:
        return 0.0
    cos_angle = float(np.dot(v_idx, v_mid) / (norm_idx * norm_mid))
    mcp_dist = float(np.linalg.norm(points[5] - points[9]))
    tip_dist = float(np.linalg.norm(points[8] - points[12]))

    # Must diverge: angle >= 15 deg (cos <= 0.965) and tip distance significantly wider than knuckles
    if cos_angle > 0.965 or tip_dist < mcp_dist * 1.25:
        return 0.0

    return float(np.clip(min(straightness[:2]), 0.0, 1.0))


def classify_gesture_result(
    result: vision.GestureRecognizerResult,
    image: mp.Image,
) -> tuple[str, float]:
    # A Peace Sign strictly requires only 1 hand in the frame.
    # If 2 or more hands are present, it is not a Peace Sign (e.g. Naruto move).
    if len(result.hand_landmarks) > 1 or len(result.hand_world_landmarks) > 1:
        return "Hand_Detected", 0.0

    for landmarks in result.hand_world_landmarks:
        points = np.array([(point.x, point.y, point.z) for point in landmarks])
        score = victory_landmark_score(points)
        if score:
            return "Victory", score
    for landmarks in result.hand_landmarks:
        points = np.array([(point.x * image.width, point.y * image.height, 0.0)
                           for point in landmarks])
        score = victory_landmark_score(points)
        if score:
            return "Victory", score
    for categories in result.gestures:
        for category in categories:
            if category.category_name == "Victory" and category.score >= 0.62:
                return "Victory", float(category.score)
    if result.hand_landmarks or result.hand_world_landmarks:
        return "Hand_Detected", 0.0
    return "No_Hand", 0.0


class MultiViewGestureRecognizer:
    """Retry detection on rotated frames without altering tracking state."""

    def __init__(self, primary, alternate):
        self.primary = primary
        self.alternate = alternate
        self.preferred_rotation: int | None = None
        self.preferred_crop: str | None = None
        self.next_retry_ms = 0
        self.retry_cursor = 0

    def recognize_gesture(self, image: mp.Image, timestamp_ms: int) -> tuple[str, float]:
        result = self.primary.recognize_for_video(image, timestamp_ms)
        best = classify_gesture_result(result, image)
        if best[0] == "Victory":
            self.preferred_rotation = None
            self.preferred_crop = None
            return best
        if timestamp_ms < self.next_retry_ms:
            return best

        rgb = image.numpy_view()
        height, width = rgb.shape[:2]
        crops = {
            "full": rgb,
            "lower_left": rgb[int(height * 0.28):, :int(width * 0.78)],
            "lower_right": rgb[int(height * 0.28):, int(width * 0.22):],
        }
        views = [("full", rotation) for rotation in (0, 1, 3, 2)]
        views += [(crop, rotation) for crop in ("lower_left", "lower_right")
                  for rotation in (0, 1, 3)]
        preferred = (self.preferred_crop, self.preferred_rotation)
        selected = []
        if preferred in views:
            selected.append(preferred)
        while len(selected) < 3:
            view = views[self.retry_cursor % len(views)]
            self.retry_cursor += 1
            if view not in selected:
                selected.append(view)
        for crop, rotation in selected:
            rotated = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(np.rot90(crops[crop], rotation)),
            )
            result = self.alternate.recognize(rotated)
            candidate = classify_gesture_result(result, rotated)
            if candidate[0] == "Victory":
                self.preferred_rotation = rotation
                self.preferred_crop = crop
                self.next_retry_ms = timestamp_ms + int(GESTURE_INTERVAL_SECONDS * 1000)
                return candidate
            if candidate[0] == "Hand_Detected":
                best = candidate
        self.preferred_rotation = None
        self.preferred_crop = None
        self.next_retry_ms = timestamp_ms + int(GESTURE_INTERVAL_SECONDS * 1000)
        return best

    def close(self) -> None:
        try:
            self.primary.close()
        finally:
            self.alternate.close()


class MultiViewHandLandmarker:
    """Track two hands in video and retry difficult views with the hand model."""

    def __init__(self, primary, alternate):
        self.primary = primary
        self.alternate = alternate
        self.preferred_view: tuple[str, int] | None = None
        self.next_retry_ms = 0
        self.last_hand_count = 0
        self.retry_cursor = 0

    def recognize_joined_hands(self, image: mp.Image, timestamp_ms: int) -> bool:
        result = self.primary.detect_for_video(image, timestamp_ms)
        self.last_hand_count = len(result.hand_landmarks)
        if joined_hands_from_landmarks(result.hand_landmarks, image.width, image.height):
            self.preferred_view = None
            return True
        if timestamp_ms < self.next_retry_ms:
            return False

        rgb = image.numpy_view()
        height, width = rgb.shape[:2]
        views = {
            "full": rgb,
            "center": rgb[int(height * 0.18):, int(width * 0.12):int(width * 0.88)],
            "lower_left": rgb[int(height * 0.22):, :int(width * 0.78)],
            "lower_right": rgb[int(height * 0.22):, int(width * 0.22):],
        }
        attempts = [("full", rotation) for rotation in (1, 3, 2)]
        attempts += [("center", rotation) for rotation in (0, 1, 3)]
        attempts += [("lower_left", 0), ("lower_right", 0)]
        selected = []
        if self.preferred_view in attempts:
            selected.append(self.preferred_view)
        while len(selected) < 2:
            view = attempts[self.retry_cursor % len(attempts)]
            self.retry_cursor += 1
            if view not in selected:
                selected.append(view)
        for crop, rotation in selected:
            rotated = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(np.rot90(views[crop], rotation)),
            )
            result = self.alternate.detect(rotated)
            self.last_hand_count = max(self.last_hand_count, len(result.hand_landmarks))
            if joined_hands_from_landmarks(result.hand_landmarks, rotated.width, rotated.height):
                self.preferred_view = (crop, rotation)
                self.next_retry_ms = timestamp_ms + 90
                return True
        self.preferred_view = None
        self.next_retry_ms = timestamp_ms + 80
        return False

    def close(self) -> None:
        try:
            self.primary.close()
        finally:
            self.alternate.close()


class GokuTracker:
    """Track 2-finger temple/forehead pose with hold duration for Goku Instant Transmission."""

    def __init__(self, hand_landmarker, face_landmarker):
        self.hand_landmarker = hand_landmarker
        self.face_landmarker = face_landmarker
        self.last_face_box: tuple[float, float, float, float] | None = None
        self.hold_started: float | None = None
        self.last_detected_time: float = 0.0
        self.last_tip_pos: tuple[int, int] | None = None

    def update(
        self, image: mp.Image, timestamp_ms: int, now: float
    ) -> tuple[bool, float, tuple[int, int] | None]:
        face_result = self.face_landmarker.detect_for_video(image, timestamp_ms)
        hand_result = self.hand_landmarker.detect_for_video(image, timestamp_ms)

        detected, tip_pos, self.last_face_box = goku_pose_from_landmarks(
            hand_result.hand_landmarks,
            face_result.face_landmarks,
            image.width,
            image.height,
            self.last_face_box,
        )
        if tip_pos is not None:
            self.last_tip_pos = tip_pos

        if detected:
            self.last_detected_time = now
            if self.hold_started is None:
                self.hold_started = now
            duration = now - self.hold_started
            progress = min(1.0, duration / GOKU_HOLD_SECONDS)
            triggered = duration >= GOKU_HOLD_SECONDS
            if triggered:
                self.hold_started = None
            return triggered, progress, (tip_pos or self.last_tip_pos)
        else:
            if self.hold_started is not None and (now - self.last_detected_time) < 0.22:
                duration = now - self.hold_started
                progress = min(1.0, duration / GOKU_HOLD_SECONDS)
                triggered = duration >= GOKU_HOLD_SECONDS
                if triggered:
                    self.hold_started = None
                return triggered, progress, self.last_tip_pos
            self.hold_started = None
            return False, 0.0, None

    def reset(self) -> None:
        self.hold_started = None
        self.last_detected_time = 0.0

    def close(self) -> None:
        try:
            self.hand_landmarker.close()
        finally:
            self.face_landmarker.close()


class UniversalTracker:
    """Track Goku (temple salute), Naruto (joined hands), and Normal (V-sign) gestures simultaneously."""

    def __init__(
        self,
        gesture_recognizer: vision.GestureRecognizer,
        face_landmarker: vision.FaceLandmarker,
        alternate_recognizer: vision.GestureRecognizer | None = None,
    ):
        self.gesture_recognizer = gesture_recognizer
        self.face_landmarker = face_landmarker
        self.alternate_recognizer = alternate_recognizer
        self.last_face_box: tuple[float, float, float, float] | None = None
        self.hold_started: float | None = None
        self.last_detected_time: float = 0.0
        self.last_tip_pos: tuple[int, int] | None = None
        self.last_hand_count: int = 0
        self.next_naruto_retry_ms: int = 0
        self.peace_hold_started: float | None = None
        self.last_peace_time: float = 0.0
        self.last_peace_pos: tuple[float, float] | None = None

    def update(
        self, image: mp.Image, timestamp_ms: int, now: float
    ) -> tuple[str | None, float, tuple[int, int] | None]:
        face_result = self.face_landmarker.detect_for_video(image, timestamp_ms)
        hand_result = self.gesture_recognizer.recognize_for_video(image, timestamp_ms)
        self.last_hand_count = len(hand_result.hand_landmarks)

        # 1. Goku Instant Transmission (2 joined fingers touching forehead/temple)
        goku_detected, tip_pos, self.last_face_box = goku_pose_from_landmarks(
            hand_result.hand_landmarks,
            face_result.face_landmarks,
            image.width,
            image.height,
            self.last_face_box,
        )
        if tip_pos is not None:
            self.last_tip_pos = tip_pos

        if goku_detected:
            self.last_detected_time = now
            if self.hold_started is None:
                self.hold_started = now
            duration = now - self.hold_started
            progress = min(1.0, duration / GOKU_HOLD_SECONDS)
            if duration >= GOKU_HOLD_SECONDS:
                self.hold_started = None
                return "goku", 1.0, (tip_pos or self.last_tip_pos)
            return "goku_charging", progress, (tip_pos or self.last_tip_pos)
        else:
            if self.hold_started is not None and (now - self.last_detected_time) < 0.22:
                duration = now - self.hold_started
                progress = min(1.0, duration / GOKU_HOLD_SECONDS)
                if duration >= GOKU_HOLD_SECONDS:
                    self.hold_started = None
                    return "goku", 1.0, self.last_tip_pos
                return "goku_charging", progress, self.last_tip_pos
            self.hold_started = None

        # 2. Check Peace Sign (Normal Vanish: V-sign)
        is_peace = False
        peace_score = 0.0

        # Peace sign strictly requires exactly 1 hand held STILL in V position
        if len(hand_result.hand_landmarks) == 1:
            peace_name, p_score = classify_gesture_result(hand_result, image)
            if peace_name == "Victory" and p_score >= 0.62:
                # Track hand anchor (knuckle 5 MCP) to ensure hand is still
                hand_pts = hand_result.hand_landmarks[0]
                curr_pos = (hand_pts[5].x, hand_pts[5].y)

                is_still = True
                if self.last_peace_pos is not None:
                    drift = math.hypot(curr_pos[0] - self.last_peace_pos[0],
                                       curr_pos[1] - self.last_peace_pos[1])
                    if drift > PEACE_MAX_DRIFT:
                        is_still = False

                if is_still:
                    self.last_peace_time = now
                    self.last_peace_pos = curr_pos
                    if self.peace_hold_started is None:
                        self.peace_hold_started = now
                    hold_duration = now - self.peace_hold_started
                    if hold_duration >= PEACE_HOLD_SECONDS:
                        is_peace = True
                        peace_score = p_score
                        self.peace_hold_started = None
                        self.last_peace_pos = None
                else:
                    # Hand moving too fast (e.g. sweeping in to perform Naruto), reset hold timer
                    self.peace_hold_started = now
                    self.last_peace_pos = curr_pos
            else:
                if self.peace_hold_started is not None and (now - self.last_peace_time) > 0.12:
                    self.peace_hold_started = None
                    self.last_peace_pos = None
        elif len(hand_result.hand_landmarks) == 0 and hand_result.gestures:
            # Mock / classifier-only test case without landmarks
            peace_name, p_score = classify_gesture_result(hand_result, image)
            if peace_name == "Victory" and p_score >= 0.62:
                is_peace = True
                peace_score = p_score
        else:
            # 2 or more hands in frame: user is performing Naruto or moving hands
            self.peace_hold_started = None
            self.last_peace_pos = None

        # 3. Naruto Substitution Jutsu (2 hands with palms joined together)
        naruto_detected = joined_hands_from_landmarks(
            hand_result.hand_landmarks,
            image.width,
            image.height,
            is_peace_sign=is_peace,
        )
        if not naruto_detected and not is_peace and self.alternate_recognizer is not None and timestamp_ms >= self.next_naruto_retry_ms:
            rgb = image.numpy_view()
            h, w = rgb.shape[:2]
            center_crop = rgb[int(h * 0.18):, int(w * 0.15):int(w * 0.85)]
            center_img = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(center_crop),
            )
            alt_result = self.alternate_recognizer.recognize(center_img)
            alt_name, alt_score = classify_gesture_result(alt_result, center_img)
            alt_is_peace = (alt_name == "Victory" and alt_score >= 0.62)
            if not alt_is_peace and joined_hands_from_landmarks(
                alt_result.hand_landmarks,
                center_img.width,
                center_img.height,
                is_peace_sign=alt_is_peace,
            ):
                naruto_detected = True
                self.next_naruto_retry_ms = timestamp_ms + 100
            else:
                self.next_naruto_retry_ms = timestamp_ms + 120

        # Peace sign strictly triggers normal dissolve vanish only
        if is_peace:
            return "normal", peace_score, None

        # Naruto move strictly triggers log conversion substitution only
        if naruto_detected:
            return "naruto", 1.0, None

        return None, 0.0, None

    def reset(self) -> None:
        self.hold_started = None
        self.last_detected_time = 0.0
        self.peace_hold_started = None
        self.last_peace_time = 0.0
        self.last_peace_pos = None

    def close(self) -> None:
        try:
            self.gesture_recognizer.close()
        finally:
            try:
                if self.alternate_recognizer is not None:
                    self.alternate_recognizer.close()
            finally:
                self.face_landmarker.close()


def recognize_gesture(
    recognizer: MultiViewGestureRecognizer,
    image: mp.Image,
    timestamp_ms: int,
) -> tuple[str, float]:
    if isinstance(recognizer, MultiViewGestureRecognizer):
        return recognizer.recognize_gesture(image, timestamp_ms)
    return classify_gesture_result(recognizer.recognize_for_video(image, timestamp_ms), image)


def start_vanish_on_gesture(state: AppState, name: str, score: float, now: float) -> bool:
    """Start dissolve on first reliable recognition of the V gesture."""
    if state.phase == "ready" and name == "Victory" and score >= 0.62:
        state.phase = "vanishing"
        state.vanish_started = now
        return True
    return False


def start_naruto_on_join(state: AppState, joined: bool, now: float) -> bool:
    if state.phase == "ready" and joined:
        state.phase = "naruto_vanishing"
        state.vanish_started = now
        return True
    return False


def set_fullscreen(enabled: bool) -> None:
    mode = cv2.WINDOW_FULLSCREEN if enabled else cv2.WINDOW_NORMAL
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, mode)


def self_test() -> int:
    """Check bundled resources and model initialization without opening a webcam."""
    required = (SEGMENTER_MODEL, GESTURE_MODEL, HAND_MODEL, FACE_MODEL, SOUND_PATH, TELEPORT_SOUND_PATH)
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing resources: {', '.join(missing)}")
    load_log()
    import pygame.mixer
    for mode in ("all", "normal", "naruto", "goku"):
        segmenter, recognizer = create_tasks(mode)
        try:
            recognizer.close()
        finally:
            segmenter.close()
    print("[Webcam] Self-test complete: models, assets, and audio verified.")
    return 0


def run() -> int:
    args = parse_args()
    if getattr(args, "self_test", False):
        return self_test()
    if getattr(args, "menu", False):
        mode = choose_mode()
    else:
        mode = args.mode or "all"
    if mode is None:
        return 0
    with ExitStack() as resources:
        return run_camera(args, resources, mode)


def run_camera(args: argparse.Namespace, resources: ExitStack, mode: str) -> int:
    download_models(mode)
    capture = open_camera(args.camera, args.width, args.height)
    resources.callback(capture.release)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    segmenter, recognizer = create_tasks(mode)
    resources.callback(segmenter.close)
    resources.callback(recognizer.close)
    log_sprite = load_log() if mode in ("all", "naruto") else None
    if mode == "all":
        vanish_sound = VanishSound(SOUND_PATH)
        teleport_sound = VanishSound(TELEPORT_SOUND_PATH)
        resources.callback(vanish_sound.close)
        resources.callback(teleport_sound.close)
    elif mode == "naruto":
        vanish_sound = VanishSound()
        teleport_sound = vanish_sound
        resources.callback(vanish_sound.close)
    elif mode == "goku":
        vanish_sound = VanishSound(TELEPORT_SOUND_PATH)
        teleport_sound = vanish_sound
        resources.callback(teleport_sound.close)
    else:
        vanish_sound = None
        teleport_sound = None

    def play_vanish() -> None:
        if vanish_sound is not None:
            vanish_sound.play()

    def play_teleport() -> None:
        if teleport_sound is not None:
            teleport_sound.play()
        elif vanish_sound is not None:
            vanish_sound.play()

    resources.callback(cv2.destroyAllWindows)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, args.width, args.height)

    state = AppState(
        calibration_started=time.perf_counter(), fullscreen=args.fullscreen
    )
    if state.fullscreen:
        set_fullscreen(True)

    background: np.ndarray | None = None
    background_samples: list[np.ndarray] = []
    last_mask: np.ndarray | None = None
    last_mask_at = float("-inf")
    dissolve_field: np.ndarray | None = None
    sparkle_noise: np.ndarray | None = None
    log_anchor: tuple[int, int, int] | None = None
    log_cache: dict[int, np.ndarray] = {}
    vanished_frame: np.ndarray | None = None
    virtual_camera = None
    virtual_camera_initialized = False
    calibration_remaining = None
    last_gesture_report = 0.0
    charging_tip: tuple[int, int] | None = None
    charging_progress = 0.0
    current_camera_index = args.camera
    last_triggered_effect = "goku" if mode in ("all", "goku") else mode
    goku_reappeared_at = 0.0
    started = time.perf_counter()
    print("[Webcam] Step out of frame for 4 seconds to capture background.")
    if mode == "all":
        print("[Webcam] ALL-IN-ONE ACTIVE: Goku, Naruto, and Peace sign available simultaneously!")
    print("[Webcam] Controls: 1 Normal, 2 Naruto, 3 Goku, R reappear, C switch camera, SPACE new background, Q quit.")

    try:
        while True:
            ok, camera_frame = capture.read()
            if not ok:
                raise RuntimeError("Webcam stopped providing video frames.")

            if not args.no_mirror:
                camera_frame = cv2.flip(camera_frame, 1)

            height, width = camera_frame.shape[:2]
            if not virtual_camera_initialized:
                virtual_camera = open_virtual_camera(args, width, height)
                virtual_camera_initialized = True
                if virtual_camera is not None:
                    resources.callback(virtual_camera.close)
            if (mode in ("all", "normal")) and (dissolve_field is None or dissolve_field.shape != (height, width)):
                dissolve_field, sparkle_noise = make_dissolve_fields(height, width)
            now = time.perf_counter()

            elapsed_ms = int((now - started) * 1000)
            mp_image = None

            if state.phase == "calibrating":
                elapsed = now - state.calibration_started
                remaining = max(0, int(np.ceil(CALIBRATION_SECONDS - elapsed)))
                if remaining != calibration_remaining:
                    print(f"[Webcam] Background capture: {remaining} seconds.")
                    calibration_remaining = remaining
                if elapsed >= CALIBRATION_SECONDS - BACKGROUND_SAMPLE_SECONDS:
                    background_samples.append(camera_frame.copy())
                if elapsed >= CALIBRATION_SECONDS:
                    if background_samples:
                        stack = np.stack(background_samples[-18:], axis=0)
                        background = np.median(stack, axis=0).astype(np.uint8)
                    else:
                        background = camera_frame.copy()
                    background_samples.clear()
                    state.phase = "ready"
                    if mode == "all":
                        print("\n" + "=" * 68)
                        print(" [VANISHCAM] UNIVERSAL ALL-IN-ONE CAMERA ACTIVE!")
                        print(" Perform any gesture to activate its effect:")
                        print("   * Goku Teleport      : 2 fingers joined at forehead / temple")
                        print("   * Naruto Substitution: Palms joined in jutsu pose")
                        print("   * Normal Dissolve    : Victory sign (V-Sign / Peace)")
                        print(" Keys: [1] Normal  [2] Naruto  [3] Goku  [R] Reappear  [C] Switch Camera")
                        print("       [SPACE] New Background  [F] Fullscreen  [Q] Quit")
                        print("=" * 68 + "\n")
                    else:
                        print("[Webcam] Background ready. You can re-enter the frame.")
                display = camera_frame

            elif background is None:
                state.phase = "calibrating"
                state.calibration_started = now
                display = camera_frame

            elif state.phase == "vanished":
                if vanished_frame is None:
                    vanished_frame = background.copy()
                    if (mode == "naruto" or (mode == "all" and last_triggered_effect == "naruto")) and log_anchor is not None:
                        overlay_log(vanished_frame, log_sprite, landed_log_anchor(log_anchor, height),
                                    cache=log_cache)
                display = vanished_frame

                if mode == "all":
                    cooldown_elapsed = now - (state.vanish_started or 0.0)
                    if now - state.last_gesture_check >= 0.06:
                        state.last_gesture_check = now
                        rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        action, val, tip = recognizer.update(mp_image, elapsed_ms, now)

                        if action == "goku":
                            if cooldown_elapsed >= 2.0:
                                last_triggered_effect = "goku"
                                state.phase = "goku_reappearing"
                                state.vanish_started = time.perf_counter()
                                vanished_frame = None
                                play_teleport()
                                charging_progress = 0.0
                                charging_tip = None
                                print("[All-In-One] Goku Teleport return (2s cooldown complete)!!")
                            else:
                                recognizer.reset()
                        # Peace sign (action == 'normal') only vanishes, does NOT reappear.
                        # Keyboard [R] or [1] can be used to reappear from normal vanish.
                elif mode == "goku":
                    cooldown_elapsed = now - (state.vanish_started or 0.0)
                    if cooldown_elapsed >= 2.0:
                        if now - state.last_gesture_check >= 0.06:
                            state.last_gesture_check = now
                            rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                            triggered, progress, tip = recognizer.update(mp_image, elapsed_ms, now)
                            if triggered:
                                state.phase = "goku_reappearing"
                                state.vanish_started = time.perf_counter()
                                vanished_frame = None
                                play_teleport()
                                charging_progress = 0.0
                                charging_tip = None
                                print("[Goku] Teleport return (2s cooldown complete)!!")
                    else:
                        recognizer.reset()

            else:
                mask = last_mask
                if (
                    state.phase == "ready"
                    and now - state.last_gesture_check >=
                    (0.06 if mode in ("all", "goku") else (0.08 if mode == "naruto" else GESTURE_INTERVAL_SECONDS))
                ):
                    state.last_gesture_check = now
                    rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    if mode == "all":
                        action, val, tip = recognizer.update(mp_image, elapsed_ms, now)
                        # 2-second cooldown on Goku move after reappearing
                        goku_cooldown_left = 2.0 - (now - goku_reappeared_at)
                        if goku_cooldown_left > 0.0 and action in ("goku", "goku_charging"):
                            action = None
                            recognizer.reset()
                            charging_progress = 0.0
                            charging_tip = None

                        if action == "goku_charging":
                            charging_progress = val
                            charging_tip = tip
                        else:
                            charging_progress = 0.0
                            charging_tip = None

                        if action == "naruto":
                            last_triggered_effect = "naruto"
                            if mask is None:
                                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                                last_mask = mask
                                last_mask_at = now
                            log_anchor = substitution_anchor(mask)
                            state.phase = "naruto_vanishing"
                            state.vanish_started = time.perf_counter()
                            play_vanish()
                            vanished_frame = None
                            print("[All-In-One] Naruto Substitution Jutsu!!")
                        elif action == "goku":
                            last_triggered_effect = "goku"
                            state.phase = "goku_vanishing"
                            state.vanish_started = time.perf_counter()
                            play_teleport()
                            vanished_frame = None
                            print("[All-In-One] Goku Instant Transmission!!")
                        elif action == "normal":
                            last_triggered_effect = "normal"
                            state.phase = "vanishing"
                            state.vanish_started = time.perf_counter()
                            play_vanish()
                            vanished_frame = None
                            print("[All-In-One] Normal Peace Sign Vanish!!")
                    elif mode == "normal":
                        name, score = recognize_gesture(recognizer, mp_image, elapsed_ms)
                        if args.gesture_debug and now - last_gesture_report >= 1.0:
                            print(
                                f"[Gesture] {name}, score={score:.2f}, "
                                f"crop={recognizer.preferred_crop or 'full'}, "
                                f"rotation={recognizer.preferred_rotation or 0}"
                            )
                            last_gesture_report = now
                        if start_vanish_on_gesture(state, name, score, now):
                            play_vanish()
                    elif mode == "naruto":
                        joined = recognizer.recognize_joined_hands(mp_image, elapsed_ms)
                        if args.gesture_debug and now - last_gesture_report >= 1.0:
                            print(f"[Hands] detected={recognizer.last_hand_count}, "
                                  f"joined={joined}, view={recognizer.preferred_view or 'full'}")
                            last_gesture_report = now
                        if start_naruto_on_join(state, joined, time.perf_counter()):
                            if mask is None:
                                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                                last_mask = mask
                                last_mask_at = now
                            log_anchor = substitution_anchor(mask)
                            play_vanish()
                    elif mode == "goku":
                        goku_cooldown_left = 2.0 - (now - goku_reappeared_at)
                        if goku_cooldown_left > 0.0:
                            recognizer.reset()
                            charging_progress = 0.0
                            charging_tip = None
                        else:
                            triggered, progress, tip = recognizer.update(mp_image, elapsed_ms, now)
                            charging_progress = progress
                            charging_tip = tip
                            if triggered:
                                state.phase = "goku_vanishing"
                                state.vanish_started = time.perf_counter()
                                play_teleport()
                                charging_progress = 0.0
                                charging_tip = None
                                print("[Goku] Instant Transmission!!")
                            elif args.gesture_debug and progress > 0 and now - last_gesture_report >= 0.2:
                                print(f"[Goku] Gathering Ki... {progress*100:.0f}%")
                                last_gesture_report = now

                if state.phase in ("vanishing", "naruto_vanishing", "goku_vanishing", "goku_reappearing"):
                    if mask is None or now - last_mask_at >= 0.04:
                        if mp_image is None:
                            rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                        last_mask = mask
                        last_mask_at = now

                mask_used = mask if mask is not None else np.zeros((height, width), dtype=np.float32)

                if (mode == "naruto" or state.phase == "naruto_vanishing") and state.phase == "naruto_vanishing":
                    age = max(0.04, time.perf_counter() - state.vanish_started)
                    display = render_substitution(
                        camera_frame, background, mask_used, log_sprite, log_anchor, age, log_cache
                    )
                    if age >= EFFECT_SECONDS:
                        state.phase = "vanished"
                        vanished_frame = display
                elif (mode in ("all", "goku")) and state.phase == "goku_vanishing":
                    age = max(0.01, time.perf_counter() - state.vanish_started)
                    display = render_goku_teleport(
                        camera_frame, background, mask_used, age, reappearing=False
                    )
                    if age >= GOKU_TELEPORT_SECONDS:
                        state.phase = "vanished"
                        vanished_frame = background.copy()
                elif (mode in ("all", "goku")) and state.phase == "goku_reappearing":
                    age = max(0.01, time.perf_counter() - state.vanish_started)
                    display = render_goku_teleport(
                        camera_frame, background, mask_used, age, reappearing=True
                    )
                    if age >= GOKU_TELEPORT_SECONDS:
                        state.phase = "ready"
                        state.vanish_started = None
                        goku_reappeared_at = time.perf_counter()
                        print("[Goku] Reappeared! 2s cooldown before teleporting again.")
                elif state.phase == "ready":
                    if charging_progress > 0 and charging_tip is not None:
                        display = render_goku_charging(camera_frame, charging_tip, charging_progress)
                    else:
                        display = camera_frame
                else:
                    progress = 0.0
                    if state.phase == "vanishing" and state.vanish_started is not None:
                        progress = min(
                            1.0, (time.perf_counter() - state.vanish_started) / VANISH_SECONDS
                        )
                        if progress >= 1.0:
                            state.phase = "vanished"
                    display = apply_dissolve(
                        camera_frame, background, mask_used, progress, dissolve_field, sparkle_noise
                    )
                    if state.phase == "vanished":
                        vanished_frame = background.copy()

            if virtual_camera is not None:
                send_virtual_frame(virtual_camera, display)
            cv2.imshow(WINDOW_NAME, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                state.phase = "calibrating"
                state.calibration_started = now
                state.vanish_started = None
                log_anchor = None
                last_mask = None
                last_mask_at = float("-inf")
                vanished_frame = None
                charging_progress = 0.0
                charging_tip = None
                background_samples.clear()
                calibration_remaining = None
                print("[Webcam] Step out of frame for 4 seconds: capturing new background.")
            elif key == ord("c"):
                found = False
                for try_idx in range(1, 5):
                    candidate = (current_camera_index + try_idx) % 5
                    test_cap = cv2.VideoCapture(candidate, cv2.CAP_DSHOW if platform.system() == "Windows" else candidate)
                    if test_cap.isOpened():
                        ok, _ = test_cap.read()
                        if ok:
                            capture.release()
                            capture = test_cap
                            current_camera_index = candidate
                            found = True
                            print(f"\n[Webcam] Switched to Webcam {current_camera_index}! Recalibrating background...")
                            state.phase = "calibrating"
                            state.calibration_started = now
                            state.vanish_started = None
                            log_anchor = None
                            last_mask = None
                            last_mask_at = float("-inf")
                            vanished_frame = None
                            charging_progress = 0.0
                            charging_tip = None
                            background_samples.clear()
                            calibration_remaining = None
                            break
                        test_cap.release()
                if not found:
                    print(f"\n[Webcam] No other webcams found (staying on camera {current_camera_index}).")
            elif key == ord("1") and background is not None:
                if state.phase == "ready":
                    last_triggered_effect = "normal"
                    state.phase = "vanishing"
                    state.vanish_started = time.perf_counter()
                    play_vanish()
                    vanished_frame = None
                    print("[Manual Key 1] Normal Dissolve Vanish!")
                elif state.phase == "vanished":
                    state.phase = "ready"
                    state.vanish_started = None
                    vanished_frame = None
                    log_anchor = None
                    print("[Manual Key 1] Reappeared!")
            elif key == ord("2") and background is not None:
                if state.phase == "ready":
                    last_triggered_effect = "naruto"
                    if mask is None:
                        rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                        last_mask = mask
                        last_mask_at = now
                    log_anchor = substitution_anchor(mask)
                    state.phase = "naruto_vanishing"
                    state.vanish_started = time.perf_counter()
                    play_vanish()
                    vanished_frame = None
                    print("[Manual Key 2] Naruto Substitution Jutsu!")
                elif state.phase == "vanished":
                    state.phase = "ready"
                    state.vanish_started = None
                    vanished_frame = None
                    log_anchor = None
                    print("[Manual Key 2] Reappeared!")
            elif key == ord("3") and background is not None:
                if state.phase == "ready":
                    goku_cooldown_left = 2.0 - (now - goku_reappeared_at)
                    if goku_cooldown_left > 0.0:
                        print(f"[Goku] Please wait {goku_cooldown_left:.1f}s before teleporting (2s cooldown after reappearing).")
                    else:
                        last_triggered_effect = "goku"
                        state.phase = "goku_vanishing"
                        state.vanish_started = time.perf_counter()
                        play_teleport()
                        vanished_frame = None
                        print("[Manual Key 3] Goku Instant Transmission!")
                elif state.phase == "vanished":
                    cooldown_elapsed = now - (state.vanish_started or 0.0)
                    if cooldown_elapsed < 2.0:
                        remaining = 2.0 - cooldown_elapsed
                        print(f"[Goku] Please wait {remaining:.1f}s before reappearing (2s cooldown).")
                    else:
                        last_triggered_effect = "goku"
                        state.phase = "goku_reappearing"
                        state.vanish_started = time.perf_counter()
                        vanished_frame = None
                        play_teleport()
            elif key == ord("r"):
                if background is not None:
                    if last_triggered_effect == "goku" and state.phase == "vanished":
                        cooldown_elapsed = now - (state.vanish_started or 0.0)
                        if cooldown_elapsed < 2.0:
                            remaining = 2.0 - cooldown_elapsed
                            print(f"[Goku] Please wait {remaining:.1f}s before reappearing (2s cooldown).")
                        else:
                            state.phase = "goku_reappearing"
                            state.vanish_started = time.perf_counter()
                            vanished_frame = None
                            play_teleport()
                    else:
                        state.phase = "ready"
                        state.vanish_started = None
                        vanished_frame = None
                        log_anchor = None
                        last_mask = None
                        last_mask_at = float("-inf")
                        charging_progress = 0.0
                        charging_tip = None
                        if hasattr(recognizer, "reset"):
                            recognizer.reset()
            elif key == ord("v") and background is not None:
                if state.phase == "ready":
                    chosen = last_triggered_effect or ("goku" if mode == "all" else mode)
                    if chosen == "goku":
                        goku_cooldown_left = 2.0 - (now - goku_reappeared_at)
                        if goku_cooldown_left > 0.0:
                            print(f"[Goku] Please wait {goku_cooldown_left:.1f}s before teleporting (2s cooldown after reappearing).")
                        else:
                            last_triggered_effect = "goku"
                            state.phase = "goku_vanishing"
                            state.vanish_started = time.perf_counter()
                            play_teleport()
                            vanished_frame = None
                    elif chosen == "naruto":
                        last_triggered_effect = "naruto"
                        if mask is None:
                            rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                            mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                            last_mask = mask
                            last_mask_at = now
                        log_anchor = substitution_anchor(mask)
                        state.phase = "naruto_vanishing"
                        state.vanish_started = time.perf_counter()
                        play_vanish()
                        vanished_frame = None
                    else:
                        last_triggered_effect = "normal"
                        state.phase = "vanishing"
                        state.vanish_started = time.perf_counter()
                        play_vanish()
                        vanished_frame = None
                elif state.phase == "vanished":
                    if last_triggered_effect == "goku":
                        cooldown_elapsed = now - (state.vanish_started or 0.0)
                        if cooldown_elapsed < 2.0:
                            remaining = 2.0 - cooldown_elapsed
                            print(f"[Goku] Please wait {remaining:.1f}s before reappearing (2s cooldown).")
                        else:
                            state.phase = "goku_reappearing"
                            state.vanish_started = time.perf_counter()
                            vanished_frame = None
                            play_teleport()
                    else:
                        state.phase = "ready"
                        state.vanish_started = None
                        vanished_frame = None
                        log_anchor = None
            elif key == ord("f"):
                state.fullscreen = not state.fullscreen
                set_fullscreen(state.fullscreen)
            if virtual_camera is not None:
                virtual_camera.sleep_until_next_frame()
    finally:
        resources.close()

    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"\n[VanishCam] ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
