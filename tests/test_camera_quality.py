from __future__ import annotations

import unittest

from utils.camera import CameraProfile, configure_capture, profile_from_config


class _FakeCV2:
    CAP_PROP_FOURCC = 1
    CAP_PROP_FRAME_WIDTH = 2
    CAP_PROP_FRAME_HEIGHT = 3
    CAP_PROP_FPS = 4
    CAP_PROP_BUFFERSIZE = 5
    CAP_PROP_AUTOFOCUS = 6
    CAP_PROP_AUTO_EXPOSURE = 7

    @staticmethod
    def VideoWriter_fourcc(*_chars):
        return 1234


class _FakeCapture:
    def __init__(self):
        self.values = {}

    def set(self, prop, value):
        self.values[prop] = value
        return True

    def get(self, prop):
        return self.values.get(prop, 0)


class CameraQualityTests(unittest.TestCase):
    def test_default_profile_requests_full_hd(self):
        self.assertEqual(profile_from_config(), CameraProfile())

    def test_profile_values_are_safely_bounded(self):
        profile = profile_from_config({
            "camera_width": 9000,
            "camera_height": 20,
            "camera_fps": 200,
            "camera_jpeg_quality": 10,
        })
        self.assertEqual((profile.width, profile.height), (3840, 480))
        self.assertEqual((profile.fps, profile.jpeg_quality), (60, 80))

    def test_capture_is_configured_for_quality_and_low_latency(self):
        cap = _FakeCapture()
        actual = configure_capture(cap, _FakeCV2, CameraProfile())
        self.assertEqual(cap.values[_FakeCV2.CAP_PROP_FRAME_WIDTH], 1920.0)
        self.assertEqual(cap.values[_FakeCV2.CAP_PROP_FRAME_HEIGHT], 1080.0)
        self.assertEqual(cap.values[_FakeCV2.CAP_PROP_FPS], 30.0)
        self.assertEqual(cap.values[_FakeCV2.CAP_PROP_BUFFERSIZE], 1.0)
        self.assertEqual(actual, {"width": 1920.0, "height": 1080.0, "fps": 30.0})


if __name__ == "__main__":
    unittest.main()
