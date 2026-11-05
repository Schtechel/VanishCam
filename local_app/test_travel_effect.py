import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from local_app.travel_effect import (
    TRAVEL_SECONDS, Destination, cover, load_destination, render_at_destination, render_travel,
)


def person_mask(width=160, height=90, left=60):
    mask = np.zeros((height, width), dtype=np.float32)
    mask[20:90, left:left + 40] = 1.0
    return mask


class TravelEffectTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((90, 160, 3), 40, dtype=np.uint8)
        self.scene = np.zeros((300, 300, 3), dtype=np.uint8)
        self.scene[:, :, 0] = np.linspace(0, 255, 300, dtype=np.uint8)[None, :]
        self.scene[:, :, 2] = 200

    def test_cover_fills_without_stretching(self):
        result = cover(self.scene, 160, 90)
        self.assertEqual(result.shape, (90, 160, 3))

    def test_destination_keeps_person_and_replaces_room(self):
        mask = person_mask()
        result = render_at_destination(self.frame, mask, Destination(self.scene, 160, 90))
        self.assertTrue(np.array_equal(result[50, 80], self.frame[50, 80]))
        self.assertEqual(result[5, 5, 2], 200)

    def test_parallax_moves_opposite_to_person(self):
        destination = Destination(self.scene, 160, 90)
        centered = destination.view(person_mask(left=60)).copy()
        for _ in range(40):
            moved_right = destination.view(person_mask(left=120))
        self.assertLess(int(moved_right[45, 80, 0]), int(centered[45, 80, 0]))

    def test_arrival_ends_at_destination_and_return_ends_home(self):
        mask = person_mask()
        destination = Destination(self.scene, 160, 90)
        arrived = render_travel(self.frame, mask, destination, TRAVEL_SECONDS, arriving=True)
        home = render_travel(self.frame, mask, destination, TRAVEL_SECONDS, arriving=False)
        self.assertEqual(arrived[5, 5, 2], 200)
        self.assertTrue(np.array_equal(home, self.frame))

    def test_flash_peaks_mid_transition(self):
        mask = person_mask()
        destination = Destination(self.scene, 160, 90)
        peak = render_travel(self.frame, mask, destination, TRAVEL_SECONDS * 0.39, arriving=True)
        self.assertGreater(peak.mean(), 150)

    def test_missing_or_invalid_destination_is_none(self):
        self.assertIsNone(load_destination(None))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "destination.png"
            self.assertIsNone(load_destination(path))
            path.write_bytes(b"not an image")
            self.assertIsNone(load_destination(path))
            cv2.imwrite(str(path), self.scene)
            self.assertEqual(load_destination(path).shape, self.scene.shape)


if __name__ == "__main__":
    unittest.main()
