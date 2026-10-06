"""LP14: public camera target-centering contract, independent of engine fidelity."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from bugbits.render.camera import camera_from_spec  # noqa: E402


class TestCameraTargetHeight(unittest.TestCase):
    BOUNDS = (-100, 100, -100, 100)
    SIZE = 128

    def test_target_is_orbit_and_projection_center_at_either_height(self):
        # The orbit centre has zero lateral/vertical displacement and depth d.
        # These literal expectations use the public target/distance contract.
        for height in (5.0, -5.0):
            for aspect, yaw in ((1.0, 0.0), (1.6, 0.0), (1.0, 25.0)):
                with self.subTest(height=height, aspect=aspect, yaw=yaw):
                    target = (11.0, height, 23.0)
                    cam = camera_from_spec(self.BOUNDS, self.SIZE, {
                        "target": target, "distance": 180.0, "pitchDeg": 40.0,
                        "aspect": aspect, "yawDeg": yaw,
                    })
                    for actual, expected in zip(cam.world_to_camera(*target), (0, 0, 180)):
                        self.assertAlmostEqual(actual, expected, delta=1e-10)
                    for actual, expected in zip(cam.world_to_pixel_depth(*target),
                                                (64 * aspect, 64, 180)):
                        self.assertAlmostEqual(actual, expected, delta=1e-10)

    def test_center_ground_ray_follows_independent_height_triangle(self):
        # At yaw0 the ray descends at 40 degrees. Continuing from the target
        # to y=0 changes z by height*cot40, independent of orbit distance.
        for height in (5.0, -5.0):
            for aspect in (1.0, 1.6):
                for distance in (180.0, 250.0):
                    with self.subTest(height=height, aspect=aspect, distance=distance):
                        cam = camera_from_spec(self.BOUNDS, self.SIZE, {
                            "target": (11.0, height, 23.0), "distance": distance,
                            "pitchDeg": 40.0, "aspect": aspect,
                        })
                        gx, gz = cam.pixel_to_ground(64 * aspect, 64)
                        self.assertAlmostEqual(gx, 11.0, delta=1e-10)
                        self.assertAlmostEqual(gz, 23 + height / math.tan(math.radians(40)),
                                               delta=1e-10)

    def test_nonzero_target_height_ground_projection_roundtrip(self):
        # Roundtrip supplements independent centering/triangle oracles above;
        # by itself a mutually wrong forward/inverse pair would be insufficient.
        for height in (5.0, -5.0):
            for aspect, yaw in ((1.0, 0.0), (1.6, 0.0), (1.0, 25.0)):
                cam = camera_from_spec(self.BOUNDS, self.SIZE, {
                    "target": (11.0, height, 23.0), "distance": 180.0,
                    "pitchDeg": 40.0, "aspect": aspect, "yawDeg": yaw,
                })
                for x, z in ((-30, -25), (11, 23), (40, 70)):
                    with self.subTest(height=height, aspect=aspect, yaw=yaw, point=(x, z)):
                        px, py = cam.world_to_pixel(x, 0.0, z)
                        gx, gz = cam.pixel_to_ground(px, py)
                        self.assertAlmostEqual(gx, x, delta=1e-10)
                        self.assertAlmostEqual(gz, z, delta=1e-10)


if __name__ == "__main__":
    unittest.main()
