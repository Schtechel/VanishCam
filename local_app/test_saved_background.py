import tempfile
import unittest
from pathlib import Path

import numpy as np

from local_app import vanish_cam as app


class SavedBackgroundTests(unittest.TestCase):
    def test_background_round_trip_and_replacement(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            path = Path(directory) / "background.png"
            self.assertIsNone(app.load_background(path))
            for value in (23, 89):
                frame = np.full((24, 40, 3), value, dtype=np.uint8)
                app.save_background(path, frame)
                np.testing.assert_array_equal(app.load_background(path), frame)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_name("background.part.png").exists())

    def test_corrupt_background_reports_error(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            path = Path(directory) / "background.png"
            path.write_bytes(b"invalid image")
            with self.assertRaisesRegex(RuntimeError, "Cannot read saved background"):
                app.load_background(path)

    def test_reset_request_is_consumed_once(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            path = Path(directory) / "reset-background"
            path.touch()
            self.assertTrue(app.consume_background_reset(path))
            self.assertFalse(app.consume_background_reset(path))

    def test_persistence_is_optional(self):
        self.assertIsNone(app.load_background(None))
        app.save_background(None, np.zeros((24, 40, 3), dtype=np.uint8))
        self.assertFalse(app.consume_background_reset(None))


if __name__ == "__main__":
    unittest.main()
