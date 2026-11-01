"""Two-hand trigger and smoke/log compositing for body substitution."""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


EFFECT_SECONDS = 1.45
LOG_PATH = Path(__file__).resolve().parent / "assets" / "substitution_log.png"


def joined_hands_from_landmarks(
    hands, width: int, height: int, is_peace_sign: bool = False
) -> bool:
    """Recognize two hands with palms joined together."""
    if not hands or len(hands) < 2 or is_peace_sign:
        return False

    points = [np.array([(p.x * width, p.y * height) for p in hand])
              for hand in hands[:2] if len(hand) == 21]
    if len(points) != 2 or not all(np.isfinite(hand).all() for hand in points):
        return False

    palms = [hand[[0, 5, 9, 13, 17]].mean(axis=0) for hand in points]
    scale = [max(float(np.linalg.norm(hand[5] - hand[17])),
                 float(np.linalg.norm(hand[0] - hand[9]))) for hand in points]
    if min(scale) < 6.0 or max(scale) > min(scale) * 3.0:
        return False

    size = sum(scale) * 0.5
    directions = [hand[9] - hand[0] for hand in points]
    norm_d0 = np.linalg.norm(directions[0])
    norm_d1 = np.linalg.norm(directions[1])
    alignment = float(np.dot(directions[0], directions[1]) /
                      max(1e-6, norm_d0 * norm_d1))
    fingertips = [hand[[8, 12, 16, 20]].mean(axis=0) for hand in points]
    palm_dist = float(np.linalg.norm(palms[0] - palms[1]))
    tip_dist = float(np.linalg.norm(fingertips[0] - fingertips[1]))

    # Both palms must be joined together:
    # 1. Palms touching or very close: palm_dist < size * 1.15
    # 2. Fingertips touching or very close: tip_dist < size * 1.25
    # 3. Both hands oriented in the same general direction: alignment > 0.35
    if (
        alignment > 0.35
        and palm_dist < size * 1.15
        and tip_dist < size * 1.25
    ):
        return True

    return False


def substitution_anchor(mask: np.ndarray) -> tuple[int, int, int]:
    """Place the log at the person's torso instead of at a fixed screen spot."""
    height, width = mask.shape
    binary = (mask > 0.45).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    if count <= 1:
        return width // 2, height // 2, int(height * 0.57)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, _ = stats[largest]
    size = int(np.clip(h * 0.58, height * 0.24, height * 0.70))
    center_x = int(np.clip(x + w * 0.5, size // 3, width - size // 3))
    center_y = int(np.clip(y + h * 0.52, size // 3, height - size // 3))
    return center_x, center_y, size


def load_log() -> np.ndarray:
    sprite = cv2.imread(str(LOG_PATH), cv2.IMREAD_UNCHANGED)
    if sprite is None or sprite.ndim != 3 or sprite.shape[2] != 4:
        raise RuntimeError(f"Substitution log sprite not available: {LOG_PATH}")
    return sprite


def overlay_log(
    frame: np.ndarray,
    sprite: np.ndarray,
    anchor: tuple[int, int, int],
    cache: dict[int, np.ndarray] | None = None,
) -> None:
    center_x, center_y, target_size = anchor
    target_size = max(16, target_size)
    if cache is not None and target_size in cache:
        resized = cache[target_size]
    else:
        resized = cv2.resize(sprite, (target_size, target_size), interpolation=cv2.INTER_AREA)
        if cache is not None:
            cache[target_size] = resized

    top = center_y - target_size // 2
    left = center_x - target_size // 2
    f_h, f_w = frame.shape[:2]

    src_top = max(0, -top)
    src_left = max(0, -left)
    dst_top = max(0, top)
    dst_left = max(0, left)
    copy_h = min(target_size - src_top, f_h - dst_top)
    copy_w = min(target_size - src_left, f_w - dst_left)
    if copy_h <= 0 or copy_w <= 0:
        return

    src_slice = np.s_[src_top : src_top + copy_h, src_left : src_left + copy_w]
    dst_slice = np.s_[dst_top : dst_top + copy_h, dst_left : dst_left + copy_w]
    patch = resized[src_slice]
    alpha = (patch[:, :, 3:4].astype(np.float32) / 255.0)
    bgr = patch[:, :, :3].astype(np.float32)
    current = frame[dst_slice].astype(np.float32)
    frame[dst_slice] = np.clip(bgr * alpha + current * (1.0 - alpha), 0, 255).astype(np.uint8)


def landed_log_anchor(anchor: tuple[int, int, int], frame_height: int) -> tuple[int, int, int]:
    center_x, center_y, size = anchor
    floor_y = max(center_y, int(frame_height - size * 0.55))
    return center_x, floor_y, size


def falling_log_anchor(
    anchor: tuple[int, int, int],
    frame_height: int,
    age: float,
) -> tuple[int, int, int]:
    center_x, start_y, size = anchor
    landed_x, target_y, _ = landed_log_anchor(anchor, frame_height)
    fall_duration = 0.8
    if age <= 0.1:
        progress = 0.0
    else:
        t = min(1.0, (age - 0.1) / (fall_duration - 0.1))
        progress = t * t * 0.95
    y = int(start_y + (target_y - start_y) * progress)
    return center_x, y, size


def render_smoke(
    frame: np.ndarray,
    anchor: tuple[int, int, int],
    progress: float,
) -> None:
    center_x, center_y, size = anchor
    height, width = frame.shape[:2]
    expansion = math.sin(min(1.0, progress * 1.6) * math.pi * 0.5)
    fade = max(0.0, 1.0 - progress) ** 1.3
    if fade <= 0.01:
        return

    smoke_canvas = np.zeros((height, width), dtype=np.float32)
    base_radius = int(size * 0.38 * (0.55 + 0.95 * expansion))

    puffs = (
        (0.0,  0.05, 1.05),
        (-0.35, -0.15, 0.78),
        ( 0.35, -0.15, 0.78),
        (-0.55,  0.15, 0.65),
        ( 0.55,  0.15, 0.65),
        (-0.25,  0.35, 0.85),
        ( 0.25,  0.35, 0.85),
        ( 0.0,  -0.35, 0.60),
    )
    for ox, oy, scale in puffs:
        px = int(center_x + ox * size * (0.8 + 0.4 * expansion))
        py = int(center_y + oy * size * (0.8 + 0.4 * expansion))
        r = int(base_radius * scale)
        if r > 2:
            cv2.circle(smoke_canvas, (px, py), r, 1.0, -1)

    smoke_canvas = cv2.GaussianBlur(smoke_canvas, (0, 0), sigmaX=size * 0.08, sigmaY=size * 0.08)
    smoke_mask = np.clip(smoke_canvas * fade * 1.15, 0.0, 0.95)[:, :, None]

    smoke_color = np.array([238, 242, 246], dtype=np.float32)
    frame[:] = np.clip(
        frame.astype(np.float32) * (1.0 - smoke_mask) + smoke_color * smoke_mask,
        0, 255,
    ).astype(np.uint8)


def render_substitution(
    frame: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray,
    sprite: np.ndarray,
    anchor: tuple[int, int, int] | None,
    elapsed_seconds: float,
    cache: dict[int, np.ndarray] | None = None,
) -> np.ndarray:
    output = frame.copy()
    progress = min(1.0, elapsed_seconds / EFFECT_SECONDS)

    # 1. Ninja dissolves/vanishes
    ninja_visibility = max(0.0, 1.0 - (progress / 0.18))
    ninja_alpha = mask * ninja_visibility
    alpha_3 = ninja_alpha[:, :, None]
    output = (output.astype(np.float32) * alpha_3 + background.astype(np.float32) * (1.0 - alpha_3)).astype(np.uint8)

    # 2. Substitution Log and smoke
    if anchor is not None:
        height = frame.shape[0]
        if elapsed_seconds >= EFFECT_SECONDS:
            current_anchor = landed_log_anchor(anchor, height)
        else:
            current_anchor = falling_log_anchor(anchor, height, elapsed_seconds)
        overlay_log(output, sprite, current_anchor, cache=cache)

        if elapsed_seconds < EFFECT_SECONDS:
            render_smoke(output, anchor, progress)

    return output
