"""Public matrix camera invariants with independent coordinate literals."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugbits.render.camera import MatrixWorldCamera


class LoadedMatrixCameraTests(unittest.TestCase):
    # Ry(pi/2) Rx(pi/2), exact quarterturn entries, in original coordinates.
    ORIGINAL = ((0, 1, 0), (0, 0, -1), (-1, 0, 0))

    def camera(self, **changes):
        options = dict(size_px=100, aspect=2, fov_y=math.pi/2, near=1, far=100)
        options.update(changes)
        return MatrixWorldCamera.from_original(self.ORIGINAL, (11, 23, -5), **options)

    def test_original_camera_center_and_rotation_share_the_world_basis(self):
        # Q(C)=(-23,5,11), RY=diag(-1,1,-1), Y-C=(4,-5,-20).
        camera = self.camera()
        self.assertEqual(camera.world_to_camera(-19, 0, -9), (-4, -5, 20))
        self.assertEqual(camera.world_to_camera(-19, 3, -9), (-4, -2, 20))

    def test_projection_and_ground_inverse_preserve_height_and_translation(self):
        camera = self.camera()
        for actual, expected in zip(camera.world_to_pixel_depth(-19, 0, -9), (90,62.5,20)):
            self.assertAlmostEqual(actual, expected, delta=1e-12)
        for actual, expected in zip(camera.world_to_pixel(-19, 3, -9), (90,55)):
            self.assertAlmostEqual(actual, expected, delta=1e-12)
        for actual, expected in zip(camera.pixel_to_ground(90,62.5), (-19,-9)):
            self.assertAlmostEqual(actual, expected, delta=1e-12)
        # Ground parallel centre ray and upward ray have no forward ground hit.
        self.assertIsNone(camera.pixel_to_ground(100,50))
        self.assertIsNone(camera.pixel_to_ground(100,0))

    def test_rejects_invalid_rotation_frustum_and_nonfinite_public_points(self):
        for rotation in [((2,0,0),(0,1,0),(0,0,1)),
                         ((1,.1,0),(0,1,0),(0,0,1)),
                         ((1,0,0),(0,1,0),(0,0,-1)), ((1,0,0),),
                         ((float('nan'),0,0),(0,1,0),(0,0,1)),
                         ((True,0,0),(0,1,0),(0,0,1))]:
            with self.subTest(rotation=rotation), self.assertRaises(ValueError):
                MatrixWorldCamera.from_original(rotation, (11,23,-5), size_px=100,
                    aspect=2, fov_y=math.pi/2, near=1, far=100)
        for changes in [dict(size_px=0), dict(aspect=0), dict(aspect=float('inf')),
                        dict(fov_y=math.pi), dict(fov_y=0), dict(near=0),
                        dict(far=1), dict(size_px=True)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.camera(**changes)
        camera = self.camera()
        for bad in (float('nan'),float('inf'),True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): camera.world_to_camera(bad,0,0)
                with self.assertRaises(ValueError): camera.pixel_to_ground(bad,50)
        for z in (11,12,-90):
            with self.subTest(z=z), self.assertRaises(ValueError):
                camera.world_to_pixel(-23,5,z)
        self.assertIsNone(camera.pixel_to_ground(100,50.01))  # hit past far

    def test_nonzero_yaw_matches_scalar_original_rotation_and_ground_inverse(self):
        # Scalar original coordinates rotate rightmost-first: Rx(theta),
        # Ry(yaw), Rx(alpha). The adapter receives independent matrix rows.
        alpha, theta = -.87, 1.57
        for yaw in (.4,-.4):
            ca, sa, ct, st, cy, sy = (math.cos(alpha),math.sin(alpha),
                math.cos(theta),math.sin(theta),math.cos(yaw),math.sin(yaw))
            rows = ((cy,sy*st,sy*ct),
                    (sa*sy,ca*ct-sa*cy*st,-ca*st-sa*cy*ct),
                    (-ca*sy,sa*ct+ca*cy*st,-sa*st+ca*cy*ct))
            for aspect in (.75,2):
                cam = MatrixWorldCamera.from_original(rows,(11,23,-5),size_px=100,
                    aspect=aspect,fov_y=math.pi/2,near=1,far=100)
                # raw point=(27,35,0); Q=(-35,0,27), raw delta=(16,12,5).
                a,b,c = 16,12,5
                b,c = ct*b-st*c, st*b+ct*c
                a,c = cy*a+sy*c, -sy*a+cy*c
                b,c = ca*b-sa*c, sa*b+ca*c
                for got,want in zip(cam.world_to_camera(-35,0,27),(a,b,c)):
                    self.assertAlmostEqual(got,want,delta=1e-12)
                px,py = cam.world_to_pixel(-35,0,27)
                for got,want in zip(cam.pixel_to_ground(px,py),(-35,27)):
                    self.assertAlmostEqual(got,want,delta=1e-10)

    def test_projection_dictionary_records_complete_matrix_not_euler_angles(self):
        projection = self.camera().projection_dict()
        self.assertEqual(projection['kind'],'matrix-yup-v1')
        self.assertEqual(projection['basis9'],[-1,0,0,0,1,0,0,0,-1])
        self.assertEqual(projection['cameraPosition'],[-23,5,11])
        self.assertEqual([projection[k] for k in ('size','aspect','near','far')],
                         [100,2,1,100])
        self.assertAlmostEqual(projection['cot'],1,delta=1e-15)




if __name__ == '__main__':
    unittest.main()
