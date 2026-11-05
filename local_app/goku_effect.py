"""Goku Instant Transmission (Shunkan Ido) effect.

Detects two joined fingers touching the forehead/temple area,
plays the authentic DBZ teleport sound, and renders animated
ki speed lines, aura glow, and instant disappearance/reappearance.
"""

from __future__ import annotations

import math
from pathlib import Path
import random

import cv2
import numpy as np

GOKU_TELEPORT_SECONDS = 0.50
GOKU_HOLD_SECONDS = 0.9
TELEPORT_SOUND_PATH = Path(__file__).resolve().parent / "assets" / "teleport.MP3"

# Key face landmark indices for forehead and temples (MediaPipe FaceLandmarker)
FOREHEAD_CENTER_INDICES = (10, 151, 9, 8)
LEFT_TEMPLE_INDICES = (109, 67, 103)
RIGHT_TEMPLE_INDICES = (338, 297, 332)
ALL_FOREHEAD_INDICES = FOREHEAD_CENTER_INDICES + LEFT_TEMPLE_INDICES + RIGHT_TEMPLE_INDICES


def goku_pose_from_landmarks(
    hand_landmarks_list,
    face_landmarks_list,
    width: int,
    height: int,
    last_face_box: tuple[float, float, float, float] | None = None,
) -> tuple[bool, tuple[int, int] | None, tuple[float, float, float, float] | None]:
    """Recognize two joined fingers (index + middle) placed at the forehead/temple."""
    current_face_box = last_face_box
    face_pts = None

    if face_landmarks_list and len(face_landmarks_list) > 0:
        face = face_landmarks_list[0]
        if len(face) >= 468:
            xs = [p.x for p in face]
            ys = [p.y for p in face]
            fx1, fy1, fx2, fy2 = min(xs), min(ys), max(xs), max(ys)
            current_face_box = (fx1, fy1, fx2, fy2)
            face_pts = face

    if not hand_landmarks_list or face_pts is None:
        return False, None, current_face_box

    for hand in hand_landmarks_list:
        if len(hand) < 21:
            continue

        pts = np.array([(p.x, p.y) for p in hand], dtype=np.float32)
        wrist = pts[0]
        middle_mcp = pts[9]
        hand_scale = float(np.linalg.norm(wrist - middle_mcp))
        if hand_scale < 0.015:
            continue

        # Check extended fingers: index (5..8), middle (9..12)
        index_tip = pts[8]
        index_pip = pts[6]
        index_mcp = pts[5]
        dist_tip_mcp = float(np.linalg.norm(index_tip - index_mcp))
        dist_pip_mcp = float(np.linalg.norm(index_pip - index_mcp))
        index_extended = (
            (dist_tip_mcp > dist_pip_mcp * 1.08 or np.linalg.norm(index_tip - wrist) > np.linalg.norm(index_pip - wrist) * 1.02)
            and dist_tip_mcp > hand_scale * 0.40
        )

        middle_tip = pts[12]
        middle_pip = pts[10]
        dist_mid_tip_mcp = float(np.linalg.norm(middle_tip - middle_mcp))
        dist_mid_pip_mcp = float(np.linalg.norm(middle_pip - middle_mcp))
        middle_extended = (
            (dist_mid_tip_mcp > dist_mid_pip_mcp * 1.08 or np.linalg.norm(middle_tip - wrist) > np.linalg.norm(middle_pip - wrist) * 1.02)
            and dist_mid_tip_mcp > hand_scale * 0.40
        )

        # Check folded fingers: ring (13..16), pinky (17..20)
        ring_tip = pts[16]
        ring_mcp = pts[13]
        pinky_tip = pts[20]
        pinky_mcp = pts[17]

        dist_index = float(np.linalg.norm(index_tip - wrist))
        dist_middle = float(np.linalg.norm(middle_tip - wrist))
        dist_ring = float(np.linalg.norm(ring_tip - wrist))
        dist_pinky = float(np.linalg.norm(pinky_tip - wrist))

        ring_folded = (
            dist_ring < dist_index * 0.88
            or np.linalg.norm(ring_tip - ring_mcp) < hand_scale * 0.88
        )
        pinky_folded = (
            dist_pinky < dist_middle * 0.88
            or np.linalg.norm(pinky_tip - pinky_mcp) < hand_scale * 0.88
        )

        # Check fingers are strictly joined together (index and middle touching)
        finger_tip_dist = float(np.linalg.norm(index_tip - middle_tip))
        fingers_joined = finger_tip_dist < hand_scale * 0.35

        if not (index_extended and middle_extended and ring_folded and pinky_folded and fingers_joined):
            continue

        # Midpoint of the two joined fingertips
        tip_x = float((index_tip[0] + middle_tip[0]) * 0.5)
        tip_y = float((index_tip[1] + middle_tip[1]) * 0.5)
        pixel_pos = (int(tip_x * width), int(tip_y * height))

        # Check fingers placed at the forehead / temple area
        at_forehead = False

        if face_pts is not None:
            forehead_pts = np.array(
                [(face_pts[idx].x, face_pts[idx].y) for idx in ALL_FOREHEAD_INDICES],
                dtype=np.float32,
            )
            distances = np.linalg.norm(forehead_pts - np.array([tip_x, tip_y]), axis=1)
            min_dist = float(np.min(distances))

            chin_y = face_pts[152].y
            forehead_y = face_pts[10].y
            face_h = max(0.08, chin_y - forehead_y)

            # Placed directly at forehead / upper temple level
            if min_dist < face_h * 0.38 and tip_y < forehead_y + face_h * 0.38:
                at_forehead = True

        if at_forehead:
            return True, pixel_pos, current_face_box

    return False, None, current_face_box


def render_goku_charging(
    frame: np.ndarray,
    tip_pos: tuple[int, int] | None,
    progress: float,
) -> np.ndarray:
    """Render Ki energy charge aura around the fingers as the user prepares Shunkan Ido."""
    if tip_pos is None or progress <= 0.02:
        return frame

    output = frame.copy()
    h, w = frame.shape[:2]
    cx, cy = tip_pos

    radius = int(12 + progress * 24 + math.sin(progress * 25.0) * 4)
    radius = max(4, min(radius, min(h, w) // 3))

    overlay = np.zeros_like(frame)
    color_inner = (255, 255, 230)
    color_outer = (255, 210, 40)

    cv2.circle(overlay, (cx, cy), radius, color_outer, -1, cv2.LINE_AA)
    cv2.circle(overlay, (cx, cy), max(2, radius // 2), color_inner, -1, cv2.LINE_AA)

    rng = random.Random(int(progress * 100))
    for _ in range(int(3 + progress * 6)):
        angle = rng.uniform(0, 2 * math.pi)
        length = radius * rng.uniform(0.9, 1.6)
        x2 = int(cx + length * math.cos(angle))
        y2 = int(cy + length * math.sin(angle))
        cv2.line(overlay, (cx, cy), (x2, y2), (255, 255, 200), 2, cv2.LINE_AA)

    blurred = cv2.GaussianBlur(overlay, (0, 0), sigmaX=5.0, sigmaY=5.0)
    alpha = min(0.85, 0.35 + progress * 0.50)
    output = cv2.addWeighted(output, 1.0, blurred, alpha, 0)
    return output


def render_goku_teleport(
    frame: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray | None,
    age: float,
    reappearing: bool = False,
) -> np.ndarray:
    """Render authentic DBZ Instant Transmission warp speed lines and disappearance/reappearance."""
    progress = float(np.clip(age / GOKU_TELEPORT_SECONDS, 0.0, 1.0))
    if reappearing:
        t = 1.0 - progress
    else:
        t = progress

    if t >= 0.999:
        return background.copy() if not reappearing else frame.copy()

    height, width = frame.shape[:2]

    if mask is None or np.all(mask < 0.05):
        out = cv2.addWeighted(frame, 1.0 - t, background, t, 0)
        return out

    binary = (mask > 0.15).astype(np.uint8)
    points = cv2.findNonZero(binary)
    if points is None:
        return background.copy()

    bx, by, bw, bh = cv2.boundingRect(points)
    bx1 = max(0, bx - 20)
    by1 = max(0, by - 40)
    bx2 = min(width, bx + bw + 20)
    by2 = min(height, by + bh + 40)

    person_alpha = float(np.clip(1.0 - (t / 0.42), 0.0, 1.0))
    canvas = background.copy()

    if person_alpha > 0.01:
        # Edge glow (Ki aura)
        edge = cv2.Canny((mask * 255).astype(np.uint8), 30, 120)
        edge_dilated = cv2.dilate(edge, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
        aura_mask = (edge_dilated > 0)[:, :, None].astype(np.float32)

        effective_mask = (mask[:, :, None] * person_alpha).astype(np.float32)
        blended = (
            frame.astype(np.float32) * effective_mask
            + background.astype(np.float32) * (1.0 - effective_mask)
        )

        cyan_glow = np.full_like(frame, (255, 230, 80), dtype=np.uint8)
        aura_intensity = float(math.sin(t * math.pi) * 0.9)
        blended = (
            blended * (1.0 - aura_mask * aura_intensity)
            + cyan_glow.astype(np.float32) * (aura_mask * aura_intensity)
        )
        canvas = np.clip(blended, 0, 255).astype(np.uint8)

    # Vertical anime speed lines (Shunkan Ido lines)
    line_intensity = float(math.sin(t * math.pi) ** 0.7)
    if line_intensity > 0.05:
        rng = random.Random(int(age * 120))
        num_lines = int(35 * line_intensity)

        for _ in range(num_lines):
            lx = rng.randint(bx1, bx2)
            length = rng.randint(int(bh * 0.4), int(bh * 1.3))
            ly_start = rng.randint(max(0, by1 - 60), min(height - 10, by2))
            ly_end = min(height - 1, ly_start + length)
            thickness = rng.choice([1, 2, 3])

            color_choice = rng.random()
            if color_choice < 0.65:
                color = (255, 255, 255)
            elif color_choice < 0.85:
                color = (255, 240, 100)
            else:
                color = (80, 220, 255)

            alpha_line = rng.uniform(0.5, 0.95) * line_intensity
            line_overlay = canvas.copy()
            cv2.line(line_overlay, (lx, ly_start), (lx, ly_end), color, thickness, cv2.LINE_AA)
            cv2.addWeighted(line_overlay, alpha_line, canvas, 1.0 - alpha_line, 0, canvas)

        # Jagged electric lightning bolts
        for _ in range(int(4 * line_intensity)):
            start_x = rng.randint(bx, bx + bw)
            start_y = rng.randint(by, by + bh)
            curr_x, curr_y = start_x, start_y
            bolt_len = rng.randint(4, 8)
            for _ in range(bolt_len):
                next_x = curr_x + rng.randint(-18, 18)
                next_y = curr_y + rng.randint(-35, 35)
                next_x = max(0, min(width - 1, next_x))
                next_y = max(0, min(height - 1, next_y))
                cv2.line(canvas, (curr_x, curr_y), (next_x, next_y), (255, 255, 255), 2, cv2.LINE_AA)
                cv2.line(canvas, (curr_x, curr_y), (next_x, next_y), (255, 230, 80), 1, cv2.LINE_AA)
                curr_x, curr_y = next_x, next_y

    return canvas
