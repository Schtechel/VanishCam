import unittest
from types import SimpleNamespace
import numpy as np

from local_app.goku_effect import (
    GOKU_HOLD_SECONDS,
    GOKU_TELEPORT_SECONDS,
    goku_pose_from_landmarks,
    render_goku_charging,
    render_goku_teleport,
)


class GokuPoseTests(unittest.TestCase):
    @staticmethod
    def make_face(center_x=0.5, top_y=0.2, bottom_y=0.5):
        # 468 dummy landmarks with forehead around (center_x, top_y)
        face = [SimpleNamespace(x=center_x, y=(top_y + bottom_y) * 0.5) for _ in range(468)]
        face[10] = SimpleNamespace(x=center_x, y=top_y)  # forehead center
        face[151] = SimpleNamespace(x=center_x, y=top_y + 0.05)
        face[152] = SimpleNamespace(x=center_x, y=bottom_y)  # chin
        face[109] = SimpleNamespace(x=center_x - 0.08, y=top_y + 0.02)  # left temple
        face[338] = SimpleNamespace(x=center_x + 0.08, y=top_y + 0.02)  # right temple
        return face

    @staticmethod
    def make_goku_hand(tip_x=0.48, tip_y=0.22, wrist_x=0.48, wrist_y=0.48, separated=False):
        pts = [SimpleNamespace(x=wrist_x, y=wrist_y) for _ in range(21)]
        # Index
        pts[5] = SimpleNamespace(x=tip_x - 0.01, y=wrist_y - 0.08)
        pts[6] = SimpleNamespace(x=tip_x - 0.01, y=wrist_y - 0.16)
        pts[8] = SimpleNamespace(x=tip_x - 0.01 if not separated else tip_x - 0.06, y=tip_y)
        # Middle
        pts[9] = SimpleNamespace(x=tip_x + 0.01, y=wrist_y - 0.08)
        pts[10] = SimpleNamespace(x=tip_x + 0.01, y=wrist_y - 0.16)
        pts[12] = SimpleNamespace(x=tip_x + 0.01 if not separated else tip_x + 0.06, y=tip_y)
        # Ring (folded)
        pts[13] = SimpleNamespace(x=tip_x + 0.03, y=wrist_y - 0.05)
        pts[14] = SimpleNamespace(x=tip_x + 0.03, y=wrist_y - 0.09)
        pts[16] = SimpleNamespace(x=tip_x + 0.03, y=wrist_y - 0.06)
        # Pinky (folded)
        pts[17] = SimpleNamespace(x=tip_x + 0.05, y=wrist_y - 0.04)
        pts[18] = SimpleNamespace(x=tip_x + 0.05, y=wrist_y - 0.08)
        pts[20] = SimpleNamespace(x=tip_x + 0.05, y=wrist_y - 0.05)
        return pts

    def test_goku_pose_detected_at_forehead(self):
        face = self.make_face()
        hand = self.make_goku_hand(tip_x=0.50, tip_y=0.21)
        detected, tip_pos, _ = goku_pose_from_landmarks([hand], [face], 640, 480)
        self.assertTrue(detected)
        self.assertIsNotNone(tip_pos)

    def test_goku_pose_detected_at_temple(self):
        face = self.make_face()
        hand = self.make_goku_hand(tip_x=0.42, tip_y=0.22)  # left temple
        detected, tip_pos, _ = goku_pose_from_landmarks([hand], [face], 640, 480)
        self.assertTrue(detected)

    def test_separated_fingers_peace_sign_rejected(self):
        face = self.make_face()
        hand = self.make_goku_hand(tip_x=0.50, tip_y=0.21, separated=True)  # V sign
        detected, tip_pos, _ = goku_pose_from_landmarks([hand], [face], 640, 480)
        self.assertFalse(detected)

    def test_hand_away_from_forehead_rejected(self):
        face = self.make_face()
        hand = self.make_goku_hand(tip_x=0.20, tip_y=0.60)  # low hand
        detected, tip_pos, _ = goku_pose_from_landmarks([hand], [face], 640, 480)
        self.assertFalse(detected)

    def test_no_hand_rejected(self):
        face = self.make_face()
        detected, _, _ = goku_pose_from_landmarks([], [face], 640, 480)
        self.assertFalse(detected)

    def test_missing_face_never_uses_screen_position_or_stale_face_box(self):
        hand = self.make_goku_hand(tip_x=0.50, tip_y=0.21)
        for box in (None, (0.4, 0.2, 0.6, 0.5)):
            with self.subTest(box=box):
                detected, tip, _ = goku_pose_from_landmarks([hand], [], 640, 480, box)
                self.assertFalse(detected)
                self.assertIsNone(tip)


class GokuRenderTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((240, 320, 3), 120, dtype=np.uint8)
        self.bg = np.full((240, 320, 3), 30, dtype=np.uint8)
        self.mask = np.zeros((240, 320), dtype=np.float32)
        self.mask[50:200, 100:220] = 1.0

    def test_charging_render_returns_valid_frame(self):
        out = render_goku_charging(self.frame, (160, 60), 0.5)
        self.assertEqual(out.shape, self.frame.shape)
        self.assertEqual(out.dtype, np.uint8)

    def test_teleport_vanish_returns_valid_frame(self):
        out_start = render_goku_teleport(self.frame, self.bg, self.mask, 0.1, False)
        out_mid = render_goku_teleport(self.frame, self.bg, self.mask, 0.3, False)
        out_end = render_goku_teleport(self.frame, self.bg, self.mask, GOKU_TELEPORT_SECONDS + 0.1, False)
        self.assertEqual(out_start.shape, self.frame.shape)
        self.assertEqual(out_mid.shape, self.frame.shape)
        self.assertEqual(out_end.shape, self.frame.shape)
        # At the end, frame should be purely the background
        np.testing.assert_array_equal(out_end, self.bg)

    def test_teleport_reappear_returns_valid_frame(self):
        out = render_goku_teleport(self.frame, self.bg, self.mask, 0.2, True)
        self.assertEqual(out.shape, self.frame.shape)


if __name__ == "__main__":
    unittest.main()
