"""Original 402AC0 row matrix; independent directed axes and rational products."""
from fractions import Fraction as F
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from bugbits.assets import pose

I = (1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1)


class OriginalEulerPoseTests(unittest.TestCase):
    def assertVector(self, actual, expected):
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, float(e), places=12)

    def test_positive_single_axes_follow_raw_row_convention(self):
        for angles, point, expected in (
                ((math.pi/2,0,0), (0,1,0), (0,0,1)),
                ((0,math.pi/2,0), (1,0,0), (0,0,-1)),
                ((0,0,math.pi/2), (1,0,0), (0,1,0))):
            with self.subTest(angles=angles):
                self.assertVector(pose.mat_apply_dir(pose.euler_rot(*angles), point), expected)

    def test_noncommuting_rotations_match_independent_rational_axis_product(self):
        sx,cx,sy,cy,sz,cz = F(3,5),F(4,5),F(5,13),F(12,13),F(8,17),F(15,17)
        rx=((1,0,0),(0,cx,sx),(0,-sx,cx))
        ry=((cy,0,-sy),(0,1,0),(sy,0,cy))
        rz=((cz,sz,0),(-sz,cz,0),(0,0,1))
        def product(a,b):
            return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3))
                               for j in range(3)) for i in range(3))
        expected=product(product(rx,ry),rz)
        actual=pose.euler_rot(math.atan2(sx,cx),math.atan2(sy,cy),math.atan2(sz,cz))
        self.assertVector([actual[4*i+j] for i in range(3) for j in range(3)],
                          [x for row in expected for x in row])

    def test_child_translation_uses_animated_parent_and_skin_normal_same_rotation(self):
        records=[('parent',0xffffffff,0,I,0),('nektar',0,0,I,0)]
        blocks=[[(0,0,0,math.pi/2,10,20,30)],[(0,0,0,0,2,0,0)]]
        worlds=pose.worlds_at(records,blocks,0)
        self.assertVector(worlds[1][12:15],(10,22,30))
        vertices=[((2,0,0),(1,0,0),(0,0))]
        skin=[((2,0,0),(1,0,0),[(0,1)])]
        result=pose.skin_at(skin,[I],[worlds[0]],source_vertices=vertices)
        self.assertVector(result[0][0],(10,22,30))
        self.assertVector(result[0][1],(0,1,0))
        self.assertEqual(result[0][2],(0,0))


if __name__=='__main__':
    unittest.main()
