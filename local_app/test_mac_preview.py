import io
import json
import struct
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from local_app import vanish_cam as app


class MacPreviewTests(unittest.TestCase):
    def test_normal_video_ignores_gestures_reset_and_effect_keys(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            root = Path(directory)
            controls, reset, key = root / "controls", root / "reset", root / "key"
            controls.write_text('{"effects": false, "gestures": true}')
            reset.touch()  # A pending reset from an older run must not capture on launch.
            background = root / "background.png"
            app.save_background(background, np.full((24, 40, 3), 7, np.uint8))
            args = SimpleNamespace(
                camera=0, width=40, height=24, fps=30, fullscreen=False,
                mode="all", no_mirror=True, gesture_debug=False, preview_stream=True,
                background_file=background, manual_calibration=True,
                controls_file=controls, reset_background_request=reset, key_request=key,
            )
            clock, index, previews = [0.0], [-1], []
            recognizer = Mock()
            recognizer.update.side_effect = AssertionError("Gestures must not run")

            def read():
                index[0] += 1
                i = index[0]
                clock[0] = i * 5
                if i == 0:
                    reset.touch()
                    key.write_text("1")
                if i == 2:
                    controls.write_text('{"effects": true, "gestures": false}')
                if i == 3:
                    controls.write_text('{"effects": false, "gestures": false}')
                if i == 4:
                    key.write_text("q")
                return True, np.full((24, 40, 3), 20 + i * 20, np.uint8)

            camera = Mock(width=40, height=24)
            with ExitStack() as patches:
                patches.enter_context(patch.object(app, "download_models"))
                patches.enter_context(patch.object(app, "open_camera", return_value=Mock(read=Mock(side_effect=read))))
                patches.enter_context(patch.object(app, "create_tasks", return_value=(Mock(), recognizer)))
                patches.enter_context(patch.object(app, "load_log"))
                patches.enter_context(patch.object(app, "VanishSound"))
                patches.enter_context(patch.object(app, "open_virtual_camera", return_value=camera))
                patches.enter_context(patch.object(app.time, "perf_counter", side_effect=lambda: clock[0]))
                patches.enter_context(patch.dict(app.os.environ, VANISHCAM_PREVIEW_FD="123"))
                patches.enter_context(patch.object(app.os, "fdopen", return_value=io.BytesIO()))
                patches.enter_context(patch.object(app, "write_preview", side_effect=lambda stream, frame, status: previews.append((frame.copy(), status))))
                with ExitStack() as resources:
                    self.assertEqual(app.run_camera(args, resources, "all"), 0)
            self.assertTrue((app.load_background(background) == 7).all(), "Background must never be automatically replaced")
            self.assertEqual(len(previews), 5)
            for i, (frame, status) in enumerate(previews):
                self.assertTrue((frame == 20 + i * 20).all(), "Live video must continue across mode changes")
                np.testing.assert_array_equal(camera.send.call_args_list[i].args[0], frame)
            self.assertTrue(previews[0][1].startswith("Normal video"))
            self.assertIn("Live camera", previews[2][1])
            self.assertIn("Gestures off", previews[2][1])
            self.assertTrue(previews[3][1].startswith("Normal video"))
            self.assertEqual(camera.sleep_until_next_frame.call_count, 4)

    def test_preview_packet_has_length_status_and_decodable_image(self):
        stream = io.BytesIO()
        frame = np.full((24, 40, 3), (10, 70, 200), np.uint8)
        app.write_preview(stream, frame, "Ready")
        packet = stream.getvalue()
        self.assertEqual(struct.unpack(">I", packet[:4])[0], len(packet) - 4)
        status, jpeg = packet[4:].split(b"\0", 1)
        self.assertEqual(status, b"Ready")
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, frame.shape)
        np.testing.assert_allclose(decoded, frame, atol=3)

    def test_control_requests_are_validated_and_consumed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            for value in ("1", "2", "3", "4", "r", " ", "q"):
                path.write_text(value)
                self.assertEqual(app.consume_key_request(path), ord(value))
                self.assertEqual(app.consume_key_request(path), -1)
            path.write_text("invalid")
            with self.assertRaisesRegex(RuntimeError, "Invalid app control"):
                app.consume_key_request(path)

    def test_return_and_reset_change_actual_preview_and_obs_frames(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            root = Path(directory)
            background = root / "background.png"
            reset = root / "reset"
            show = root / "show"
            key = root / "key"
            app.save_background(background, np.full((24, 40, 3), 10, np.uint8))
            args = SimpleNamespace(
                camera=0, width=40, height=24, fps=30, fullscreen=False,
                mode="all", no_mirror=True, gesture_debug=False,
                preview_stream=True, background_file=background,
                reset_background_request=reset, show_myself_request=show, key_request=key,
            )
            clock = [10.0]
            times = [10, 11, 15, 16, 17, 18, 19, 21.6, 22.1, 23, 27, 28]
            colors = [40, 60, 80, 100, 120, 140, 160, 180, 200, 220, 230, 240]
            index = [-1]

            def read():
                index[0] += 1
                i = index[0]
                clock[0] = times[i]
                if i in (0, 9):
                    key.write_text("1")
                elif i == 3:
                    show.touch()
                elif i == 5:
                    reset.touch()
                elif i == 11:
                    key.write_text("q")
                return True, np.full((24, 40, 3), colors[i], np.uint8)

            capture = Mock(read=Mock(side_effect=read))
            recognizer = Mock()
            recognizer.update.return_value = (None, 0, None)
            camera = Mock(width=40, height=24)
            preview = []
            statuses = []

            def receive_preview(stream, frame, status):
                preview.append(frame.copy())
                statuses.append(status)

            with ExitStack() as patches:
                patches.enter_context(patch.object(app, "download_models"))
                patches.enter_context(patch.object(app, "open_camera", return_value=capture))
                patches.enter_context(patch.object(app, "create_tasks", return_value=(Mock(), recognizer)))
                patches.enter_context(patch.object(app, "VanishSound"))
                patches.enter_context(patch.object(app, "load_log"))
                patches.enter_context(patch.object(app, "open_virtual_camera", return_value=camera))
                patches.enter_context(patch.object(app, "person_mask", return_value=np.ones((24, 40), np.float32)))
                patches.enter_context(patch.object(app.time, "perf_counter", side_effect=lambda: clock[0]))
                patches.enter_context(patch.dict(app.os.environ, VANISHCAM_PREVIEW_FD="123"))
                patches.enter_context(patch.object(app.os, "fdopen", return_value=io.BytesIO()))
                patches.enter_context(patch.object(app, "write_preview", side_effect=receive_preview))
                patches.enter_context(patch.object(app.cv2, "namedWindow", side_effect=AssertionError("No Python window")))
                with ExitStack() as resources:
                    self.assertEqual(app.run_camera(args, resources, "all"), 0)
            self.assertTrue((preview[2] == 10).all(), "Dissolve must show the old background")
            self.assertTrue((preview[4] == 120).all(), "Show myself must restore actual live pixels")
            self.assertTrue((app.load_background(background) == 190).all(), "Reset must save replacement pixels")
            self.assertTrue((preview[10] == 190).all(), "Next vanish must use the replacement background")
            self.assertEqual(statuses[4], "Live camera")
            self.assertIn("Background saved", statuses[8])
            self.assertIn("showing saved background", statuses[10])
            for sent, frame in zip(camera.send.call_args_list, preview):
                np.testing.assert_array_equal(sent.args[0], frame)

    def test_new_profile_and_live_framing_wait_for_explicit_background_reset(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            root = Path(directory)
            background, framing_file = root / "background.png", root / "framing.json"
            reset, key = root / "reset", root / "key"
            framing_file.write_text(json.dumps(app.Framing().__dict__))
            args = SimpleNamespace(
                camera=0, width=40, height=24, fps=30, fullscreen=False,
                mode="normal", no_mirror=True, gesture_debug=False,
                preview_stream=True, background_file=background,
                framing_file=framing_file, manual_calibration=True,
                reset_background_request=reset, key_request=key,
            )
            clock, index, statuses, frames = [0.0], [-1], [], []

            def read():
                index[0] += 1
                i = index[0]
                clock[0] = (0, 1, 2, 3, 5.7, 6.2, 7)[i]
                if i == 1:
                    framing_file.write_text(json.dumps(app.Framing(2, 1, 0).__dict__))
                elif i == 2:
                    self.assertFalse(background.exists())
                    reset.touch()
                elif i == 6:
                    key.write_text("q")
                return True, np.full((24, 40, 3), 20 + i * 10, np.uint8)

            with ExitStack() as patches:
                patches.enter_context(patch.object(app, "download_models"))
                patches.enter_context(patch.object(app, "open_camera", return_value=Mock(read=Mock(side_effect=read))))
                patches.enter_context(patch.object(app, "create_tasks", return_value=(Mock(), Mock())))
                patches.enter_context(patch.object(app, "open_virtual_camera", return_value=None))
                patches.enter_context(patch.object(app, "recognize_gesture", return_value=("No_Hand", 0)))
                patches.enter_context(patch.object(app.time, "perf_counter", side_effect=lambda: clock[0]))
                patches.enter_context(patch.dict(app.os.environ, VANISHCAM_PREVIEW_FD="123"))
                patches.enter_context(patch.object(app.os, "fdopen", return_value=io.BytesIO()))
                patches.enter_context(patch.object(app, "write_preview", side_effect=lambda stream, frame, status: (statuses.append(status), frames.append(frame.copy()))))
                with ExitStack() as resources:
                    self.assertEqual(app.run_camera(args, resources, "normal"), 0)
            self.assertTrue(all("set framing" in status for status in statuses[:3]))
            self.assertTrue(statuses[3].startswith("Step out:"))
            self.assertIn("Background saved", statuses[5])
            self.assertEqual(app.load_framing(background.with_suffix(".framing.json")), app.Framing(2, 1, 0))
            self.assertTrue((app.load_background(background) == 65).all())
            self.assertFalse(np.array_equal(frames[0], frames[1]), "Unconfigured preview must remain live")

    def test_travel_keeps_person_and_swaps_room_without_saved_background(self):
        with tempfile.TemporaryDirectory(dir=app.APP_DIR.parent / "build") as directory:
            root = Path(directory)
            destination_file, key = root / "destination.png", root / "key"
            cv2.imwrite(str(destination_file), np.full((60, 100, 3), 200, np.uint8))
            args = SimpleNamespace(
                camera=0, width=40, height=24, fps=30, fullscreen=False,
                mode="all", no_mirror=True, gesture_debug=False,
                preview_stream=True, background_file=root / "background.png",
                manual_calibration=True, key_request=key, destination_file=destination_file,
            )
            clock, index, statuses, frames = [0.0], [-1], [], []
            times = (0, 0.5, 1.2, 3.5, 3.6, 4.7, 5.0)

            def read():
                index[0] += 1
                i = index[0]
                clock[0] = times[i]
                if i in (0, 3):
                    key.write_text("4")
                elif i == 6:
                    key.write_text("q")
                return True, np.full((24, 40, 3), 50, np.uint8)

            mask = np.zeros((24, 40), np.float32)
            mask[:, :20] = 1.0
            recognizer = Mock()
            recognizer.update.return_value = (None, 0, None)

            def receive_preview(stream, frame, status):
                frames.append(frame.copy())
                statuses.append(status)

            with ExitStack() as patches:
                patches.enter_context(patch.object(app, "download_models"))
                patches.enter_context(patch.object(app, "open_camera", return_value=Mock(read=Mock(side_effect=read))))
                patches.enter_context(patch.object(app, "create_tasks", return_value=(Mock(), recognizer)))
                patches.enter_context(patch.object(app, "open_virtual_camera", return_value=None))
                patches.enter_context(patch.object(app, "VanishSound"))
                patches.enter_context(patch.object(app, "load_log"))
                patches.enter_context(patch.object(app, "person_mask", return_value=mask))
                patches.enter_context(patch.object(app.time, "perf_counter", side_effect=lambda: clock[0]))
                patches.enter_context(patch.dict(app.os.environ, VANISHCAM_PREVIEW_FD="123"))
                patches.enter_context(patch.object(app.os, "fdopen", return_value=io.BytesIO()))
                patches.enter_context(patch.object(app, "write_preview", side_effect=receive_preview))
                with ExitStack() as resources:
                    self.assertEqual(app.run_camera(args, resources, "all"), 0)
            self.assertFalse(args.background_file.exists(), "Travel must not capture a background")
            self.assertTrue((frames[0] == 50).all(), "Before travel the camera stays live")
            self.assertEqual(statuses[2], "At destination")
            self.assertTrue((frames[3][:, :20] == 50).all(), "The person stays visible")
            self.assertTrue((frames[3][:, 20:] == 200).all(), "The room becomes the destination")
            self.assertTrue((frames[5] == 50).all(), "Coming home restores the live room")


if __name__ == "__main__":
    unittest.main()
