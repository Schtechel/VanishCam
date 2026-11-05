import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from local_app import vanish_cam as app


class CameraProfileTests(unittest.TestCase):
    def test_zoom_and_position_crop_without_mirroring(self):
        frame = np.repeat(np.arange(8, dtype=np.uint8)[None, :, None], 4, axis=0)
        frame = np.repeat(frame, 3, axis=2)
        self.assertIs(app.apply_framing(frame, app.Framing()), frame)
        left = app.apply_framing(frame, app.Framing(2, -1, 0))
        right = app.apply_framing(frame, app.Framing(2, 1, 0))
        self.assertEqual(left.shape, frame.shape)
        self.assertEqual(int(left[0, 0, 0]), 0)
        self.assertEqual(int(right[0, -1, 0]), 7)
        self.assertGreater(float(right.mean()), float(left.mean()))

    def test_framing_file_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "framing.json"
            for value in ({"zoom": 0}, {"zoom": 4}, {"horizontal": 2}, {"zoom": "2"}, {"zoom": float("nan")}):
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(RuntimeError, "Cannot read camera framing"):
                    app.load_framing(path)
            path.write_text(json.dumps({"zoom": 1.5, "horizontal": -0.5, "vertical": 0.25}))
            self.assertEqual(app.load_framing(path), app.Framing(1.5, -0.5, 0.25))
            path.write_text("invalid")
            with self.assertRaises(RuntimeError):
                app.load_framing(path)

    def test_native_four_by_three_image_is_cropped_not_stretched(self):
        frame = np.zeros((12, 16, 3), np.uint8)
        frame[:2] = 255
        frame[-2:] = 255
        output = app.apply_framing(frame, app.Framing(), (16, 9))
        self.assertEqual(output.shape, (9, 16, 3))
        self.assertLess(float(output.mean()), 30)

    def test_native_resolution_is_passed_to_camera_without_fallback(self):
        process = Mock()
        process.poll.return_value = 1
        with patch.object(app.shutil, "which", return_value="/usr/bin/ffmpeg"), \
             patch.object(app.threading, "Thread"), \
             patch.object(app.subprocess, "Popen", return_value=process) as opening:
            camera = app.NamedMacCamera("Logitech BRIO", 1920, 1080, 30, "1920x1080")
            camera.release()
            command = opening.call_args.args[0]
            self.assertEqual(command[command.index("-video_size") + 1], "1920x1080")
            self.assertIn("Logitech BRIO:none", command)


if __name__ == "__main__":
    unittest.main()
