import unittest
from types import SimpleNamespace

import numpy as np
import mediapipe as mp

from local_app.vanish_cam import (
    AppState, MultiViewGestureRecognizer, UniversalTracker, recognize_gesture, start_vanish_on_gesture,
    victory_landmark_score,
)


def hand_points(extended=(True, True, False, False)):
    points = np.zeros((21, 3))
    for base, x, opened, spread in zip(
        (5, 9, 13, 17), (-0.45, 0.0, 0.4, 0.75), extended, (-0.35, 0.25, 0.0, 0.0)
    ):
        if opened:
            points[base : base + 4] = [
                (x, 1.0, 0.0), (x + spread * 0.45, 1.7, 0.0),
                (x + spread * 0.75, 2.15, 0.0), (x + spread, 2.5, 0.0),
            ]
        else:
            points[base : base + 4] = [
                (x, 1.0, 0.0), (x, 1.5, 0.2),
                (x, 1.3, 0.5), (x, 0.95, 0.3),
            ]
    return points


def landmarks(points):
    return [SimpleNamespace(x=x, y=y, z=z) for x, y, z in points]


class VictoryGestureTests(unittest.TestCase):
    def test_victory_with_back_palm_rotation_mirror_and_scale(self):
        points = hand_points()
        for angle in (0.0, 0.7, 1.57, 2.6, np.pi):
            c, s = np.cos(angle), np.sin(angle)
            rotation = np.array(((c, -s, 0), (s, c, 0), (0, 0, 1)))
            tilt = np.array(((1, 0, 0), (0, c, -s), (0, s, c)))
            for mirror in (1, -1):
                for scale in (0.02, 1.0, 100.0):
                    with self.subTest(angle=angle, mirror=mirror, scale=scale):
                        transformed = points @ rotation @ tilt
                        transformed[:, 0] *= mirror
                        transformed = transformed * scale + (0.5, 0.3, 0.1)
                        self.assertGreater(victory_landmark_score(transformed), 0.62)

    def test_other_gestures_do_not_trigger(self):
        for fingers in (
            (False, False, False, False),  # Fist.
            (True, True, True, True),  # Open palm.
            (True, False, False, False),  # Index finger only.
            (True, False, False, True),  # Horns sign.
            (True, True, True, False),  # Three fingers.
        ):
            with self.subTest(fingers=fingers):
                self.assertEqual(victory_landmark_score(hand_points(fingers)), 0.0)

    def test_invalid_or_degenerate_landmarks(self):
        for points in (np.zeros((21, 3)), np.zeros((20, 3)), np.full((21, 3), np.nan)):
            self.assertEqual(victory_landmark_score(points), 0.0)

    def test_landmarks_trigger_without_classifier_category(self):
        result = SimpleNamespace(
            hand_world_landmarks=[landmarks(hand_points())], hand_landmarks=[], gestures=[]
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        name, score = recognize_gesture(recognizer, None, 1000)
        self.assertEqual(name, "Victory")
        self.assertGreater(score, 0.62)

    def test_normalized_landmark_fallback_handles_video_aspect_ratio(self):
        image = SimpleNamespace(width=960, height=540)
        points = hand_points() * 40 + (480, 200, 0)
        normalized = points / (image.width, image.height, image.width)
        result = SimpleNamespace(
            hand_world_landmarks=[], hand_landmarks=[landmarks(normalized)], gestures=[]
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        self.assertEqual(recognize_gesture(recognizer, image, 1000)[0], "Victory")

    def test_existing_classifier_still_works(self):
        result = SimpleNamespace(
            hand_world_landmarks=[], hand_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.9)]],
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        self.assertEqual(recognize_gesture(recognizer, None, 1000), ("Victory", 0.9))

    def test_occluded_folded_fingers_can_appear_short_and_straight(self):
        points = hand_points()
        for base in (13, 17):
            points[base : base + 4] = [
                (0.4, 1.0, 0.0), (0.4, 1.1, 0.0),
                (0.4, 1.2, 0.0), (0.4, 1.3, 0.0),
            ]
        self.assertGreater(victory_landmark_score(points), 0.62)

    def test_hidden_fingers_with_coincident_landmarks(self):
        points = hand_points()
        points[13:16] = points[13]
        points[16] = points[13]
        points[17:20] = points[17]
        points[20] = points[17]
        self.assertGreater(victory_landmark_score(points), 0.62)

    def test_visible_geometry_is_used_even_with_inaccurate_world_landmarks(self):
        image = SimpleNamespace(width=960, height=540)
        points = hand_points() * 40 + (480, 200, 0)
        world = hand_points()
        world[8] = world[6]
        self.assertEqual(victory_landmark_score(world), 0.0)
        result = SimpleNamespace(
            hand_world_landmarks=[landmarks(world)],
            hand_landmarks=[landmarks(points / (960, 540, 960))], gestures=[],
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        self.assertEqual(recognize_gesture(recognizer, image, 1000)[0], "Victory")

    def test_diagnostics_distinguish_missing_hand_and_rejected_gesture(self):
        for hands, expected in (([], "No_Hand"), ([landmarks(hand_points((False,) * 4))], "Hand_Detected")):
            result = SimpleNamespace(hand_world_landmarks=hands, hand_landmarks=[], gestures=[])
            recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
            self.assertEqual(recognize_gesture(recognizer, None, 1000)[0], expected)


class ImmediateAnimationTests(unittest.TestCase):
    def test_first_recognized_v_starts_animation_immediately(self):
        state = AppState(phase="ready")
        self.assertTrue(start_vanish_on_gesture(state, "Victory", 0.9, 12.5))
        self.assertEqual(state.phase, "vanishing")
        self.assertEqual(state.vanish_started, 12.5)

    def test_other_or_weak_gestures_do_not_vanish(self):
        for name, score in (("No_Hand", 0.0), ("Hand_Detected", 0.0), ("Victory", 0.61)):
            with self.subTest(name=name, score=score):
                state = AppState(phase="ready")
                self.assertFalse(start_vanish_on_gesture(state, name, score, 12.5))
                self.assertEqual(state.phase, "ready")
                self.assertIsNone(state.vanish_started)

    def test_only_ready_phase_responds(self):
        for phase in ("calibrating", "vanishing", "vanished"):
            state = AppState(phase=phase)
            self.assertFalse(start_vanish_on_gesture(state, "Victory", 0.9, 12.5))
            self.assertEqual(state.phase, phase)


class MultiViewTests(unittest.TestCase):
    def setUp(self):
        self.empty = SimpleNamespace(hand_world_landmarks=[], hand_landmarks=[], gestures=[])
        self.victory = SimpleNamespace(
            hand_world_landmarks=[], hand_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.9)]],
        )
        self.image = mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.zeros((32, 48, 3), dtype=np.uint8)
        )

    def test_rotated_detection_and_preferred_view_are_used(self):
        calls = []

        def recognize(image):
            calls.append((image.width, image.height))
            return self.victory if image.width == 32 else self.empty

        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.empty),
            SimpleNamespace(recognize=recognize),
        )
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "Victory")
        self.assertEqual(calls, [(48, 32), (32, 48)])
        self.assertEqual(detector.preferred_rotation, 1)
        calls.clear()
        self.assertEqual(recognize_gesture(detector, self.image, 1140)[0], "Victory")
        self.assertEqual(calls, [(32, 48)])

    def test_failed_search_is_throttled_without_reusing_old_positive(self):
        calls = []
        alternate = SimpleNamespace(recognize=lambda image: calls.append(image) or self.empty)
        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.empty), alternate
        )
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "No_Hand")
        self.assertEqual(len(calls), 3)
        recognize_gesture(detector, self.image, 1100)
        self.assertEqual(len(calls), 3)
        alternate.recognize = lambda image: self.victory
        self.assertEqual(recognize_gesture(detector, self.image, 1420)[0], "Victory")
        alternate.recognize = lambda image: self.empty
        self.assertEqual(recognize_gesture(detector, self.image, 1560)[0], "No_Hand")

    def test_primary_victory_avoids_extra_inference(self):
        calls = []
        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.victory),
            SimpleNamespace(recognize=lambda image: calls.append(image) or self.empty),
        )
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "Victory")
        self.assertEqual(calls, [])

    def test_lower_hand_crop_recovers_a_small_sideways_v(self):
        calls = []

        def recognize(image):
            calls.append((image.width, image.height))
            return self.victory if (image.width, image.height) == (37, 24) else self.empty

        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.empty),
            SimpleNamespace(recognize=recognize),
        )
        recognize_gesture(detector, self.image, 1000)
        self.assertEqual(recognize_gesture(detector, self.image, 1140)[0], "Victory")
        self.assertEqual(detector.preferred_crop, "lower_left")
        self.assertEqual(detector.preferred_rotation, 0)
        calls.clear()
        self.assertEqual(recognize_gesture(detector, self.image, 1280)[0], "Victory")
        self.assertEqual(calls, [(37, 24)])


class UniversalTrackerTests(unittest.TestCase):
    def setUp(self):
        self.image = mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.zeros((480, 640, 3), dtype=np.uint8)
        )

    def test_goku_charging_and_trigger(self):
        face = [SimpleNamespace(x=0.5, y=0.35) for _ in range(468)]
        face[10] = SimpleNamespace(x=0.5, y=0.20)
        face[152] = SimpleNamespace(x=0.5, y=0.50)
        face[109] = SimpleNamespace(x=0.42, y=0.22)
        face[338] = SimpleNamespace(x=0.58, y=0.22)

        goku_pts = [SimpleNamespace(x=0.42, y=0.48) for _ in range(21)]
        goku_pts[5] = SimpleNamespace(x=0.41, y=0.40)
        goku_pts[6] = SimpleNamespace(x=0.41, y=0.32)
        goku_pts[8] = SimpleNamespace(x=0.41, y=0.22)
        goku_pts[9] = SimpleNamespace(x=0.43, y=0.40)
        goku_pts[10] = SimpleNamespace(x=0.43, y=0.32)
        goku_pts[12] = SimpleNamespace(x=0.43, y=0.22)

        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[face]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[goku_pts], hand_world_landmarks=[], gestures=[]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        # First call: charging started
        action, prog, tip = tracker.update(self.image, 100, 10.0)
        self.assertEqual(action, "goku_charging")
        self.assertGreaterEqual(prog, 0.0)
        self.assertIsNotNone(tip)

        # Mid call: charging progress > 0
        action, prog, tip = tracker.update(self.image, 250, 10.20)
        self.assertEqual(action, "goku_charging")
        self.assertGreater(prog, 0.0)
        self.assertIsNotNone(tip)

        # After hold duration: triggered!
        action, prog, tip = tracker.update(self.image, 550, 10.45)
        self.assertEqual(action, "goku")
        self.assertEqual(prog, 1.0)
        self.assertIsNotNone(tip)

    def test_naruto_joined_hands_trigger(self):
        def make_naruto_hand(cx):
            pts = [SimpleNamespace(x=cx, y=0.53) for _ in range(21)]
            pts[0] = SimpleNamespace(x=cx, y=0.70)
            for idx, off in ((5, -0.045), (9, -0.015), (13, 0.015), (17, 0.045)):
                pts[idx] = SimpleNamespace(x=cx + off, y=0.54)
            for idx, off in ((8, -0.045), (12, -0.015), (16, 0.015), (20, 0.045)):
                pts[idx] = SimpleNamespace(x=cx + off, y=0.34)
            return pts

        h1, h2 = make_naruto_hand(0.45), make_naruto_hand(0.55)
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[h1, h2], hand_world_landmarks=[], gestures=[]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, prog, tip = tracker.update(self.image, 100, 10.0)
        self.assertEqual(action, "naruto")
        self.assertEqual(prog, 1.0)

    def test_normal_v_sign_trigger(self):
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[], hand_world_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.92)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, score, tip = tracker.update(self.image, 100, 10.0)
        self.assertEqual(action, "normal")
        self.assertAlmostEqual(score, 0.92, places=2)

    def test_no_gesture_returns_none(self):
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[], hand_world_landmarks=[], gestures=[]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, val, tip = tracker.update(self.image, 100, 10.0)
        self.assertIsNone(action)
        self.assertEqual(val, 0.0)

    def test_peace_sign_in_chest_region_only_vanishes_never_triggers_naruto(self):
        # A single hand making peace sign at chest/torso height held still
        p_pts = hand_points((True, True, False, False))
        # Place hand at chest/torso height (y ~ 0.55)
        p_pts_norm = p_pts / 3.0 + (0.5, 0.45, 0.0)
        hand_p = [SimpleNamespace(x=float(x), y=float(y), z=float(z)) for x, y, z in p_pts_norm]
        world_p = [SimpleNamespace(x=float(x), y=float(y), z=float(z)) for x, y, z in p_pts]

        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[hand_p],
            hand_world_landmarks=[world_p],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.92)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        # First call starts the stillness hold timer
        tracker.update(self.image, 100, 10.0)
        # Calling after the hold duration confirms still V position and triggers vanish
        action, score, tip = tracker.update(self.image, 400, 10.30)
        self.assertEqual(action, "normal")
        self.assertNotEqual(action, "naruto")
        self.assertGreater(score, 0.62)

    def test_moving_hand_never_triggers_peace_sign(self):
        # Hand moving across screen (e.g. swept in to perform Naruto) must NOT trigger peace sign
        p_pts = hand_points((True, True, False, False))
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))

        h1 = [SimpleNamespace(x=float(x)/3.0 + 0.25, y=float(y)/3.0 + 0.45, z=float(z)) for x, y, z in p_pts]
        h2 = [SimpleNamespace(x=float(x)/3.0 + 0.40, y=float(y)/3.0 + 0.45, z=float(z)) for x, y, z in p_pts]

        gest_state = [h1]
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=gest_state,
            hand_world_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.92)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action1, _, _ = tracker.update(self.image, 100, 10.00)
        self.assertIsNone(action1)

        # Move hand across screen by 0.15 normalized units (rapid motion)
        gest_state = [h2]
        action2, _, _ = tracker.update(self.image, 200, 10.10)
        self.assertIsNone(action2)

    def test_two_hands_in_frame_never_trigger_peace_sign(self):
        # When 2 hands are present, Peace Sign is strictly disabled
        p_pts = hand_points((True, True, False, False))
        h1 = [SimpleNamespace(x=float(x)/3.0 + 0.30, y=float(y)/3.0 + 0.45, z=float(z)) for x, y, z in p_pts]
        h2 = [SimpleNamespace(x=float(x)/3.0 + 0.70, y=float(y)/3.0 + 0.45, z=float(z)) for x, y, z in p_pts]

        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[h1, h2],
            hand_world_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.92)],
                      [SimpleNamespace(category_name="Victory", score=0.92)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, _, _ = tracker.update(self.image, 100, 10.00)
        self.assertNotEqual(action, "normal")
        action, _, _ = tracker.update(self.image, 400, 10.30)
        self.assertNotEqual(action, "normal")

    def test_joined_palms_only_triggers_naruto_never_normal(self):
        # Two hands with palms joined together
        def make_naruto_hand(cx):
            pts = [SimpleNamespace(x=cx, y=0.53) for _ in range(21)]
            pts[0] = SimpleNamespace(x=cx, y=0.70)
            for idx, off in ((5, -0.045), (9, -0.015), (13, 0.015), (17, 0.045)):
                pts[idx] = SimpleNamespace(x=cx + off, y=0.54)
            for idx, off in ((8, -0.045), (12, -0.015), (16, 0.015), (20, 0.045)):
                pts[idx] = SimpleNamespace(x=cx + off, y=0.34)
            return pts

        h1, h2 = make_naruto_hand(0.48), make_naruto_hand(0.52)
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[h1, h2],
            hand_world_landmarks=[],
            gestures=[[SimpleNamespace(category_name="None", score=0.85)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, score, tip = tracker.update(self.image, 100, 10.0)
        self.assertEqual(action, "naruto")
        self.assertNotEqual(action, "normal")
        self.assertEqual(score, 1.0)

    def test_single_hand_never_triggers_naruto(self):
        # A single hand can NEVER activate the Naruto move - both palms must join
        pts = [SimpleNamespace(x=0.48, y=0.53) for _ in range(21)]
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[pts],
            hand_world_landmarks=[],
            gestures=[[SimpleNamespace(category_name="None", score=0.85)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, score, tip = tracker.update(self.image, 100, 10.0)
        self.assertNotEqual(action, "naruto")

    def test_separated_palms_never_trigger_naruto(self):
        # Two hands that are separated (not joined) must not activate Naruto
        def make_separated_hand(cx):
            pts = [SimpleNamespace(x=cx, y=0.53) for _ in range(21)]
            pts[0] = SimpleNamespace(x=cx, y=0.70)
            for idx, off in ((5, -0.045), (9, -0.015), (13, 0.015), (17, 0.045)):
                pts[idx] = SimpleNamespace(x=cx + off, y=0.54)
            for idx, off in ((8, -0.045), (12, -0.015), (16, 0.015), (20, 0.045)):
                pts[idx] = SimpleNamespace(x=cx + off, y=0.34)
            return pts

        h1, h2 = make_separated_hand(0.20), make_separated_hand(0.80)
        mock_face = SimpleNamespace(detect_for_video=lambda img, ts: SimpleNamespace(face_landmarks=[]))
        mock_gest = SimpleNamespace(recognize_for_video=lambda img, ts: SimpleNamespace(
            hand_landmarks=[h1, h2],
            hand_world_landmarks=[],
            gestures=[[SimpleNamespace(category_name="None", score=0.85)]]
        ))

        tracker = UniversalTracker(mock_gest, mock_face)
        action, score, tip = tracker.update(self.image, 100, 10.0)
        self.assertNotEqual(action, "naruto")


if __name__ == "__main__":
    unittest.main()
