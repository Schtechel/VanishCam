import subprocess
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from local_app import vanish_cam as app


class AvFoundationCameraTests(unittest.TestCase):
    def test_open_camera_uses_avfoundation_backend_on_macos(self):
        capture = Mock()
        capture.isOpened.return_value = True
        with patch.object(app.platform, "system", return_value="Darwin"), \
             patch.object(app.cv2, "VideoCapture", return_value=capture) as open_capture:
            self.assertIs(app.open_camera(2, 960, 540), capture)
        open_capture.assert_called_once_with(2, app.cv2.CAP_AVFOUNDATION)

    def test_lists_video_devices_from_ffmpeg_output(self):
        output = "\n".join((
            "[AVFoundation indev @ 0x1234] AVFoundation video devices:",
            "[AVFoundation indev @ 0x1234] [0] OBS Virtual Camera",
            "[AVFoundation indev @ 0x1234] [1] Camo Camera",
            "[AVFoundation indev @ 0x1234] [2] FaceTime HD Camera",
            "[AVFoundation indev @ 0x1234] AVFoundation audio devices:",
            "[AVFoundation indev @ 0x1234] [0] MacBook Microphone",
        ))
        result = SimpleNamespace(stderr=output, stdout="")
        with patch.object(app.shutil, "which", return_value="/opt/homebrew/bin/ffmpeg"), \
             patch.object(app.subprocess, "run", return_value=result) as run:
            self.assertEqual(
                app.list_avfoundation_cameras(),
                [(0, "OBS Virtual Camera"), (1, "Camo Camera"), (2, "FaceTime HD Camera")],
            )
        self.assertEqual(run.call_args.args[0][-4:], ["-list_devices", "true", "-i", ""])
        self.assertFalse(run.call_args.kwargs["check"])

    def test_resolves_exact_camo_name_after_device_indexes_shift(self):
        devices = [(0, "OBS Virtual Camera"), (1, "Camo Camera"), (2, "FaceTime HD Camera")]
        with patch.object(app.platform, "system", return_value="Darwin"), \
             patch.object(app, "list_avfoundation_cameras", return_value=devices), \
             patch("builtins.print"):
            self.assertEqual(app.resolve_camera_name("Camo Camera"), 1)

    def test_missing_camera_fails_without_falling_back(self):
        devices = [(0, "OBS Virtual Camera"), (1, "FaceTime HD Camera")]
        with patch.object(app.platform, "system", return_value="Darwin"), \
             patch.object(app, "list_avfoundation_cameras", return_value=devices):
            with self.assertRaisesRegex(RuntimeError, "Camera 'Camo Camera' was not found"):
                app.resolve_camera_name("Camo Camera")

    def test_camera_name_rejected_off_macos(self):
        with patch.object(app.platform, "system", return_value="Linux"):
            with self.assertRaisesRegex(RuntimeError, "only on macOS"):
                app.resolve_camera_name("Camo Camera")

    def test_camera_enumeration_timeout_is_reported(self):
        with patch.object(app.shutil, "which", return_value="/opt/homebrew/bin/ffmpeg"), \
             patch.object(
                 app.subprocess, "run",
                 side_effect=subprocess.TimeoutExpired("ffmpeg", 10),
             ):
            with self.assertRaisesRegex(RuntimeError, "Timed out"):
                app.list_avfoundation_cameras()


class ObsExtensionTests(unittest.TestCase):
    extension_id = "com.obsproject.obs-studio.mac-camera-extension"

    def run_extension_check(self, status):
        result = SimpleNamespace(
            stdout=f"* * TEAM {self.extension_id} (33.0.1) OBS Virtual Camera [{status}]",
            stderr="",
        )
        with patch.object(app.shutil, "which", return_value="/usr/bin/systemextensionsctl"), \
             patch.object(app.subprocess, "run", return_value=result):
            app.ensure_obs_virtual_camera_ready()

    def test_waiting_for_user_is_reported_before_native_backend_open(self):
        with self.assertRaisesRegex(RuntimeError, "waiting for macOS approval"):
            self.run_extension_check("activated waiting for user")

    def test_active_extension_passes_preflight(self):
        self.run_extension_check("activated enabled")

    def test_unregistered_extension_is_reported(self):
        result = SimpleNamespace(stdout="No extensions", stderr="")
        with patch.object(app.shutil, "which", return_value="/usr/bin/systemextensionsctl"), \
             patch.object(app.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "not registered"):
                app.ensure_obs_virtual_camera_ready()


class NamedMacCameraTests(unittest.TestCase):
    def test_named_input_and_partial_frame_reads(self):
        process = Mock()
        process.poll.return_value = None
        process.stdout.fileno.return_value = 42
        with patch.object(app.shutil, "which", return_value="/usr/bin/ffmpeg"), \
             patch.object(app.subprocess, "Popen", return_value=process) as opening, \
             patch.object(app.threading, "Thread"), \
             patch.object(app.select, "select", return_value=([42], [], [])), \
             patch.object(app.os, "read", side_effect=[b"\x07" * 3, b"\x07" * 9]):
            camera = app.NamedMacCamera("Camo Camera", 2, 2, 30)
            try:
                frame = camera._read_frame()
                camera._frame = frame
                ok, frame = camera.read()
                self.assertTrue(ok)
                np.testing.assert_array_equal(frame, np.full((2, 2, 3), 7, np.uint8))
            finally:
                camera.release()
                camera.release()
        self.assertIn("Camo Camera:none", opening.call_args.args[0])
        command = opening.call_args.args[0]
        self.assertEqual(command[command.index("-fps_mode") + 1], "passthrough")
        process.terminate.assert_called_once()
        process.stdout.close.assert_called_once()

    def test_missing_frames_fail_clearly(self):
        process = Mock()
        process.poll.return_value = 1
        process.stdout.fileno.return_value = 42
        with patch.object(app.shutil, "which", return_value="/usr/bin/ffmpeg"), \
             patch.object(app.subprocess, "Popen", return_value=process), \
             patch.object(app.threading, "Thread"), \
             patch.object(app.select, "select", return_value=([42], [], [])), \
             patch.object(app.os, "read", return_value=b""):
            camera = app.NamedMacCamera("Camo Camera", 2, 2, 30)
            try:
                camera._read_frames()
                with self.assertRaisesRegex(RuntimeError, "capture stopped"):
                    camera.read()
            finally:
                camera.release()

    def test_slow_consumer_gets_latest_frame_not_queued_history(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "rb", buffering=0)
        process = Mock(stdout=stream)
        process.poll.return_value = 1
        try:
            with patch.object(app.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                 patch.object(app.subprocess, "Popen", return_value=process):
                camera = app.NamedMacCamera("Test Camera", 2, 2, 30)
            try:
                for value in (1, 2, 3):
                    os.write(write_fd, bytes([value]) * 12)
                    with camera._condition:
                        self.assertTrue(camera._condition.wait_for(
                            lambda: camera._frame is not None and camera._frame[0, 0, 0] == value,
                            timeout=2,
                        ), "Reader must drain input even while consumer does not read")
                ok, frame = camera.read()
                self.assertTrue(ok)
                self.assertTrue((frame == 3).all(), "Old frames must be dropped, not replayed")
                self.assertIsNone(camera._frame)
            finally:
                camera.release()
            self.assertFalse(camera._reader.is_alive())
            with self.assertRaisesRegex(RuntimeError, "closed"):
                camera.read()
        finally:
            os.close(write_fd)
            if not stream.closed:
                stream.close()


if __name__ == "__main__":
    unittest.main()
