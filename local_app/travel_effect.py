"""Instant Transmission travel: keep the person, swap the world behind them."""

from __future__ import annotations

import math
import random
from pathlib import Path

import cv2
import numpy as np

TRAVEL_SECONDS = 1.1
TRAVEL_FLASH_END = 0.4
TRAVEL_ARRIVAL_ZOOM = 1.35
PARALLAX_MARGIN = 0.08
PARALLAX_SMOOTHING = 0.15


def load_destination(path: Path | None) -> np.ndarray | None:
    if path is None or not path.is_file():
        return None
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        print(f"[Travel] Could not read destination image: {path.name}")
    return image


def cover(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Scale and center-crop an image to fill width x height without stretching."""
    source_height, source_width = image.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized = cv2.resize(
        image,
        (max(width, round(source_width * scale)), max(height, round(source_height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )
    y = (resized.shape[0] - height) // 2
    x = (resized.shape[1] - width) // 2
    return resized[y:y + height, x:x + width]


def zoom(image: np.ndarray, factor: float) -> np.ndarray:
    if factor <= 1.001:
        return image
    height, width = image.shape[:2]
    crop_width, crop_height = round(width / factor), round(height / factor)
    x, y = (width - crop_width) // 2, (height - crop_height) // 2
    return cv2.resize(image[y:y + crop_height, x:x + crop_width], (width, height), interpolation=cv2.INTER_LINEAR)


def zoom_blur(image: np.ndarray, factor: float) -> np.ndarray:
    """Cheap radial motion blur: average a few zoom levels up to factor."""
    if factor <= 1.001:
        return image
    far, near = zoom(image, factor), zoom(image, 1 + (factor - 1) * 0.5)
    return cv2.addWeighted(far, 0.5, near, 0.5, 0)


def composite(person: np.ndarray, scene: np.ndarray, mask: np.ndarray) -> np.ndarray:
    alpha = np.clip(mask, 0, 1).astype(np.float32)
    return cv2.blendLinear(person, scene, alpha, 1 - alpha)


class Destination:
    """A destination image prepared for one output size, with gentle parallax."""

    def __init__(self, image: np.ndarray, width: int, height: int):
        self.width, self.height = width, height
        self.margin_x = round(width * PARALLAX_MARGIN)
        self.margin_y = round(height * PARALLAX_MARGIN)
        self.scene = cover(image, width + 2 * self.margin_x, height + 2 * self.margin_y)
        self.offset = np.zeros(2, dtype=np.float32)

    def view(self, mask: np.ndarray | None = None) -> np.ndarray:
        """Shift the scene opposite to the person's position so the camera feels present."""
        target = np.zeros(2, dtype=np.float32)
        if mask is not None:
            small = cv2.resize(mask, (max(1, mask.shape[1] // 8), max(1, mask.shape[0] // 8)), interpolation=cv2.INTER_AREA)
            moments = cv2.moments((small > 0.5).astype(np.uint8), binaryImage=True)
            if moments["m00"] > 0:
                center_x = moments["m10"] / moments["m00"] / small.shape[1] - 0.5
                center_y = moments["m01"] / moments["m00"] / small.shape[0] - 0.5
                target = np.clip(np.array([-center_x, -center_y], dtype=np.float32) * 2, -1, 1)
        self.offset += (target - self.offset) * PARALLAX_SMOOTHING
        x = self.margin_x + round(self.offset[0] * self.margin_x)
        y = self.margin_y + round(self.offset[1] * self.margin_y)
        return self.scene[y:y + self.height, x:x + self.width]


def speed_lines(canvas: np.ndarray, intensity: float, seed: int) -> np.ndarray:
    if intensity <= 0.05:
        return canvas
    height, width = canvas.shape[:2]
    overlay = canvas.copy()
    rng = random.Random(seed)
    center_x, center_y = width / 2, height / 2
    reach = math.hypot(width, height) / 2
    for _ in range(int(40 * intensity)):
        angle = rng.uniform(0, 2 * math.pi)
        inner = reach * rng.uniform(0.25, 0.6)
        start = (int(center_x + inner * math.cos(angle)), int(center_y + inner * math.sin(angle)))
        end = (int(center_x + reach * math.cos(angle)), int(center_y + reach * math.sin(angle)))
        color = (255, 255, 255) if rng.random() < 0.7 else (255, 230, 80)
        cv2.line(overlay, start, end, color, rng.choice((1, 2, 3)), cv2.LINE_AA)
    return cv2.addWeighted(overlay, 0.85 * intensity, canvas, 1 - 0.85 * intensity, 0)


def flash(canvas: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0.01:
        return canvas
    white = np.full_like(canvas, 255)
    return cv2.addWeighted(white, amount, canvas, 1 - amount, 0)


def render_travel(
    frame: np.ndarray,
    mask: np.ndarray,
    destination: Destination,
    age: float,
    arriving: bool,
) -> np.ndarray:
    """Flash out of the current place, then rush into the next one while the person stays put."""
    t = float(np.clip(age / TRAVEL_SECONDS, 0.0, 1.0))
    seed = int(age * 120)
    if t < TRAVEL_FLASH_END:
        rise = t / TRAVEL_FLASH_END
        leaving = frame if arriving else composite(frame, destination.view(mask), mask)
        canvas = zoom_blur(leaving, 1 + 0.2 * rise)
        canvas = speed_lines(canvas, rise, seed)
        return flash(canvas, 0.9 * rise ** 1.5)
    settle = (t - TRAVEL_FLASH_END) / (1 - TRAVEL_FLASH_END)
    ease = 1 - (1 - settle) ** 3
    rush = TRAVEL_ARRIVAL_ZOOM - (TRAVEL_ARRIVAL_ZOOM - 1) * ease
    if arriving:
        canvas = composite(frame, zoom_blur(destination.view(mask), rush), mask)
    else:
        canvas = zoom_blur(frame, rush)
    canvas = speed_lines(canvas, 1 - settle, seed)
    return flash(canvas, 0.9 * (1 - settle) ** 2)


def render_at_destination(frame: np.ndarray, mask: np.ndarray, destination: Destination) -> np.ndarray:
    return composite(frame, destination.view(mask), mask)
