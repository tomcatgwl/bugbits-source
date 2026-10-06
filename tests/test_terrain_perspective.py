"""Independent terrain UV/camera-z examples, not original gameplay validation.

The pre-agreed research seam is the production material rasterizer's RGB image
and z-buffer. Fixtures invert fixed screen coordinates by hand; expected values
are rational world/ray geometry, never another implementation of the rasterizer.
No original assets, world baking, browser, or on-disk image output is needed.
"""
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bugbits.assets.v3d import WorldMesh
from bugbits.render import bake, camera


SIZE = 128
BACKGROUND = (16, 18, 22)
EMPTY_DEPTH = 1e9
UVS = ((0, 0), (1, 0), (0, 1))
# Screen A(16,16), B(112,16), C(64,112), camera-z=(1,2,4).
# Fixed camPos=(0,0,-8), cot=1, right=X/up=Y/forward=Z.
WORLD_VERTICES = ((-3 / 4, 3 / 4, -7), (3 / 2, 3 / 2, -6), (0, -3, -4))
FLAT_Z2 = ((-3 / 2, 3 / 2, -6), (3 / 2, 3 / 2, -6), (0, -3 / 2, -6))


def fixed_camera():
    return camera.camera_from_spec((-4, 4, -8, 0), SIZE, {
        "pitchDeg": 0, "yawDeg": 0, "fovDeg": 90, "aspect": 1,
        "target": [0, 0, 0], "distance": 8, "near": 1, "far": 1000})


def mesh(points, uvs=UVS, indices=(0, 1, 2)):
    verts = [(point, (0, 0, 1), uv) for point, uv in zip(points, uvs)]
    return WorldMesh("fixture", "", (), verts, 1, len(indices), indices,
                     "fixture", (indices,), ("fixture",))


def uv_texture():
    texture = Image.new("RGB", (32, 32))
    for y in range(32):
        for x in range(32):
            texture.putpixel((x, y), (8 * x, 8 * y, 64))
    return texture


def raster(jobs, cam=None):
    image = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    depth = [[EMPTY_DEPTH] * SIZE for _ in range(SIZE)]
    for item, texture, kind in jobs:
        bake._raster_mesh_group(item, (200, 200, 200), item.indices,
                                texture, kind, image.load(), depth,
                                (0, 0, 1), SIZE, cam or fixed_camera())
    return image, depth


class TerrainPerspectiveTests(unittest.TestCase):
    def test_independent_world_vertices_and_ray_point_project_to_probe(self):
        cam = fixed_camera()
        expected = ((16, 16, 1), (112, 16, 2), (64, 112, 4))
        for point, projection in zip(WORLD_VERTICES, expected):
            with self.subTest(point=point):
                for actual, wanted in zip(cam.world_to_pixel_depth(*point), projection):
                    self.assertAlmostEqual(actual, wanted, delta=1e-10)
        # Object barycentrics=(4/7,2/7,1/7); this point also lies at t=12/7
        # on ray (0,1/4,1) from camPos. It is NOT a pixel_to_ground fixture.
        for actual, wanted in zip(cam.world_to_pixel_depth(0, 3 / 7, -44 / 7),
                                  (64, 48, 12 / 7)):
            self.assertAlmostEqual(actual, wanted, delta=1e-10)

    def test_uv_texel_and_camera_depth_follow_independent_rationals(self):
        image, depth = raster([(mesh(WORLD_VERTICES), uv_texture(), "opaque")])
        # At screen centroid lambda=(1/3,1/3,1/3), q=7/12.
        with self.subTest(quantity="camera-z"):
            self.assertAlmostEqual(depth[48][64], 12 / 7, delta=1e-12)
        # UV=(2/7,1/7) -> texel(9,27) RGB(72,216,64). Face normal is
        # (2,-2,-3)/sqrt(17); light=(0,0,1) gives lam=3/sqrt(17).
        with self.subTest(quantity="lit UV texel"):
            self.assertEqual(image.getpixel((64, 48)), (52, 157, 46))

    def test_varying_depth_occludes_constant_z2_in_both_orders(self):
        varying = (mesh(WORLD_VERTICES), Image.new("RGB", (1, 1), (210, 40, 20)), "opaque")
        constant = (mesh(FLAT_Z2), Image.new("RGB", (1, 1), (20, 40, 210)), "opaque")
        for jobs in ((varying, constant), (constant, varying)):
            with self.subTest(first="varying" if jobs[0] is varying else "constant"):
                image, depth = raster(jobs)
                self.assertEqual(image.getpixel((64, 48)), (152, 29, 14))
                self.assertAlmostEqual(depth[48][64], 12 / 7, delta=1e-12)

    def test_near_clip_matches_hand_clipped_faces_and_independent_inside_point(self):
        # A.z=.5, B.z=C.z=2; low->high intersection t=1/3, near=1.
        cross = mesh(((-3 / 8, 3 / 8, -15 / 2),
                      (3 / 2, 3 / 2, -6), (0, -3 / 2, -6)))
        # Hand D(1/4,3/4,1), E(-1/4,-1/4,1) in camera space;
        # triangles DBC,DCE, with UV_D=(1/3,0), UV_E=(0,1/3).
        manual = mesh(((1 / 4, 3 / 4, -7), (3 / 2, 3 / 2, -6),
                       (0, -3 / 2, -6), (-1 / 4, -1 / 4, -7)),
                      ((1 / 3, 0), (1, 0), (0, 1), (0, 1 / 3)),
                      (0, 1, 2, 0, 2, 3))
        texture = uv_texture()
        actual, actual_depth = raster([(cross, texture, "opaque")])
        expected, expected_depth = raster([(manual, texture, "opaque")])
        # (64,48) is ON the near edge. (64,64) is strictly inside, with
        # screen weights=(1/4,1/4,1/2), q=7/8, UV=(1/7,2/7).
        with self.subTest(quantity="independent near camera-z"):
            self.assertAlmostEqual(actual_depth[64][64], 8 / 7, delta=1e-12)
        # 32x32 texel=(4,22) -> RGB(32,176,64); face unit normal is
        # (8,-4,-7)/sqrt(129), so lightZ lam=7/sqrt(129).
        with self.subTest(quantity="independent near lit UV texel"):
            self.assertEqual(actual.getpixel((64, 64)), (19, 108, 39))
        for x, y in ((64, 64), (64, 72), (64, 80)):
            with self.subTest(manual_clip_probe=(x, y)):
                self.assertLess(actual_depth[y][x], EMPTY_DEPTH)
                self.assertAlmostEqual(actual_depth[y][x], expected_depth[y][x], delta=1e-10)
                self.assertEqual(actual.getpixel((x, y)), expected.getpixel((x, y)))

    def test_untextured_material_uses_correct_camera_depth(self):
        image, depth = raster([(mesh(WORLD_VERTICES), None, "opaque")])
        self.assertAlmostEqual(depth[48][64], 12 / 7, delta=1e-12)
        self.assertEqual(image.getpixel((64, 48)), (145, 145, 145))

    def test_legacy_auto_fit_path_uses_same_perspective_attributes(self):
        # Existing plain/auto-fit path skips clipping; positive depths still
        # require perspective interpolation. No test-only camera flags are set.
        cam = camera.StaticObliqueCamera((-1, 1, -1, 1), SIZE,
                                          pitch_deg=0, fov_deg=90, near=0.25, margin=1)
        self.assertTrue(cam._plain and cam._auto_fit)
        # Independent fitted distance=2 and camera origin=(0,0,-2).
        item = mesh(((-3 / 4, 3 / 4, -1), (3 / 2, 3 / 2, 0), (0, -3, 2)))
        image, depth = raster([(item, uv_texture(), "opaque")], cam)
        self.assertAlmostEqual(depth[48][64], 12 / 7, delta=1e-12)
        self.assertEqual(image.getpixel((64, 48)), (52, 157, 46))

    def test_cutout_alpha_63_skips_and_64_writes_color_and_depth(self):
        item = mesh(FLAT_Z2, ((3 / 4, 1 / 2),) * 3)
        for alpha in (63, 64):
            with self.subTest(alpha=alpha):
                texture = Image.new("RGBA", (2, 1), (100, 80, 60, 255))
                texture.putpixel((1, 0), (100, 80, 60, alpha))
                self.assertEqual(bake._texture_kind(texture), "cutout")
                image, depth = raster([(item, texture, "cutout")])
                self.assertEqual(image.getpixel((64, 48)),
                                 BACKGROUND if alpha == 63 else (100, 80, 60))
                self.assertEqual(depth[48][64], EMPTY_DEPTH if alpha == 63 else 2)

    def test_blend_preserves_alpha_and_no_depth_write_contract(self):
        for alpha, wanted_color, wanted_depth in (
                (0, BACKGROUND, EMPTY_DEPTH),
                (128, (58, 49, 41), EMPTY_DEPTH),
                (255, (100, 80, 60), 2)):
            with self.subTest(alpha=alpha):
                texture = Image.new("RGBA", (1, 1), (100, 80, 60, alpha))
                image, depth = raster([(mesh(FLAT_Z2), texture, "blend")])
                self.assertEqual(image.getpixel((64, 48)), wanted_color)
                self.assertEqual(depth[48][64], wanted_depth)
        # Corrected depth must pass the opaque z2 test, but alpha128 must
        # leave that opaque depth intact. This catches a misplaced z-write.
        back = (mesh(FLAT_Z2), Image.new("RGB", (1, 1), (20, 40, 210)), "opaque")
        front = (mesh(WORLD_VERTICES), Image.new("RGBA", (1, 1), (210, 40, 20, 128)), "blend")
        image, depth = raster((back, front))
        self.assertEqual(image.getpixel((64, 48)), (86, 34, 111))
        self.assertEqual(depth[48][64], 2)

    def test_all_behind_near_and_degenerate_faces_write_nothing(self):
        # "Behind" means all camera-z < near, not reverse winding. The
        # explicit-distance production camera takes the real clipping path.
        behind = ((-1 / 4, 1 / 4, -15 / 2),
                  (1 / 4, 1 / 4, -15 / 2), (0, -1 / 4, -15 / 2))
        degenerate = ((-1, 0, -6), (0, 0, -6), (1, 0, -6))
        for points in (behind, degenerate):
            with self.subTest(points=points):
                image, depth = raster([(mesh(points), None, "opaque")])
                self.assertEqual(image.getextrema(), tuple((ch, ch) for ch in BACKGROUND))
                self.assertTrue(all(value == EMPTY_DEPTH for row in depth for value in row))

    def test_equal_depth_keeps_first_write_and_reverse_winding_still_renders(self):
        for indices in ((0, 1, 2), (0, 2, 1)):
            with self.subTest(indices=indices):
                item = mesh(FLAT_Z2, indices=indices)
                first = (item, Image.new("RGB", (1, 1), (100, 80, 60)), "opaque")
                second = (item, Image.new("RGB", (1, 1), (20, 40, 210)), "opaque")
                image, depth = raster((first, second))
                self.assertEqual(image.getpixel((64, 48)), (100, 80, 60))
                self.assertEqual(depth[48][64], 2)


if __name__ == "__main__":
    unittest.main()
