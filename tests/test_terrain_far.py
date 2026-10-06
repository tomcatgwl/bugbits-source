"""Independent LH far-boundary visibility at the agreed material-raster seam."""
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bugbits.assets.v3d import WorldMesh
from bugbits.render import bake, camera


BG = (16, 18, 22)
EMPTY = 1e9


def fixed_camera(auto_fit=False):
    if auto_fit:
        # Fit distance=2 by cot90=1, hx=hz=1, pitch0, margin1.
        return camera.StaticObliqueCamera((-1, 1, -1, 1), 128,
                                         pitch_deg=0, fov_deg=90, near=.5, far=4, margin=1)
    return camera.camera_from_spec((-1, 1, -1, 1), 128, {
        "pitchDeg": 0, "yawDeg": 0, "fovDeg": 90, "aspect": 1,
        "target": [0, 0, 0], "distance": 2, "near": 1, "far": 4})


def draw(depths, kind="opaque", texture=True, auto_fit=False):
    cam = fixed_camera(auto_fit)
    rays = ((-.75, .75), (.75, .75), (0, -.75))
    verts = [((x*z, y*z, z-2), (0,0,1), (0,0)) for (x,y),z in zip(rays,depths)]
    item = WorldMesh("fixture", "", (), verts, 1, 3, (0,1,2), "fixture", ((0,1,2),), ("fixture",))
    image = Image.new("RGB", (128,128), BG)
    depth = [[EMPTY]*128 for _ in range(128)]
    tex = Image.new("RGBA", (1,1), (200,200,200,128 if kind=="blend" else 255)) if texture else None
    bake._raster_mesh_group(item, (200,200,200), item.indices, tex, kind,
                            image.load(), depth, (0,0,1), 128, cam)
    return image, depth


class TerrainFarPlaneTests(unittest.TestCase):
    def test_beyond_far_never_changes_material_color_or_depth(self):
        # near1/far4: z5 maps to NDC16/15>1, independent of UV/alpha.
        for kind, texture in (("opaque",True),("cutout",True),("blend",True),("opaque",False)):
            with self.subTest(kind=kind, texture=texture):
                image, depth = draw((5,5,5), kind, texture)
                self.assertEqual(image.getpixel((64,48)), BG)
                self.assertEqual(depth[48][64], EMPTY)

    def test_inside_and_equal_far_keep_existing_color_and_depth(self):
        # z3 -> NDC8/9; z4 -> exactly1. Neither may be rejected.
        for z in (3,4):
            with self.subTest(camera_z=z):
                image, depth = draw((z,z,z))
                self.assertEqual(image.getpixel((64,48)), (200,200,200))
                self.assertEqual(depth[48][64], z)

    def test_crossing_far_keeps_near_probe_and_rejects_far_probe(self):
        image, depth = draw((2,6,6))
        # At (64,48), lambda all1/3 gives q=5/18, z=18/5<4.
        self.assertNotEqual(image.getpixel((64,48)), BG)
        self.assertAlmostEqual(depth[48][64], 18/5, delta=1e-12)
        # At (64,80), lambda=(1/6,1/6,2/3); q=2/9, z=9/2>4.
        self.assertEqual(image.getpixel((64,80)), BG)
        self.assertEqual(depth[80][64], EMPTY)

    def test_legacy_fit_path_obeys_its_declared_far(self):
        self.assertTrue(fixed_camera(True)._plain and fixed_camera(True)._auto_fit)
        image, depth = draw((5,5,5), auto_fit=True)
        self.assertEqual(image.getpixel((64,48)), BG)
        self.assertEqual(depth[48][64], EMPTY)


if __name__ == "__main__":
    unittest.main()
