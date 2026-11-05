"""Frozen, windowless video engine owned by the native macOS app."""

import os
import signal
import sys


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    if "--preview-stream" in sys.argv:
        descriptor = os.dup(sys.stdout.fileno())
        os.environ["VANISHCAM_PREVIEW_FD"] = str(descriptor)
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        sys.stdout.reconfigure(line_buffering=True)
    if getattr(sys, "frozen", False):
        os.environ["PATH"] = sys._MEIPASS + os.pathsep + "/usr/bin:/bin"
    signal.signal(signal.SIGTERM, interrupted)
    from vanish_cam import main

    raise SystemExit(main())
