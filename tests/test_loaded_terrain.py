"""Public terrain producer consumes the same loaded geometry as WorldData."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugbits.assets import v3d
from bugbits.render import bake


class LiteralCamera:
    size_px = 32
    aspect = 1.0
    near = 1.0
    far = 1000.0
    cot = 1.0
    _plain = False
    _auto_fit = False

    def world_to_camera(self, x, y, z):
        return (x + 2, y - 25, z)


class LoadedTerrainProducer(unittest.TestCase):
    def fixture(self, version='loaded-yup-v1'):
        matrix=(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)
        mesh=v3d.WorldMesh('ground',-1,matrix,
            [((11,23,5),(0,0,1),(0,0)),
             ((13,23,5),(0,0,1),(1,0)),
             ((11,25,5),(0,0,1),(0,1))],
            1,3,(0,1,2),'',((0,1,2),),('',))
        world=SimpleNamespace(basis_version=version,static_position=(7,13,-2),
                              static_direction=(1,0,0),static_scale=1,
                              static_model='worlds/probe')
        return mesh,world

    def test_terrain_loader_applies_same_asymmetric_owner_chain(self):
        mesh,world=self.fixture()
        with patch('bugbits.worlddb.parse_world',return_value=world), \
             patch.object(bake.v3d,'parse_world_meshes',return_value=[mesh]):
            result=bake.terrain_meshes('world_02')
        for actual,expected in zip(result[0].verts[0][0],(-2,25,12)):
            self.assertAlmostEqual(actual,expected,delta=3e-6)
        self.assertEqual(mesh.verts[0][0],(11,23,5))
        self.assertEqual(result[0].indices,(0,1,2))
        self.assertEqual(result[0].verts[0][2],(0,0))

    def test_public_bake_renders_loaded_owner_geometry(self):
        mesh,world=self.fixture()
        with patch('bugbits.worlddb.parse_world',return_value=world), \
             patch.object(bake.v3d,'parse_world_meshes',return_value=[mesh]):
            image=bake.bake_terrain('world_02',size=32,camera=LiteralCamera())
        # Hand-projected loaded triangle: (16,16), (18.67,16), (16,13.33).
        # The raw untransformed triangle would be completely outside this view.
        self.assertNotEqual(image.getpixel((16,15)),(16,18,22))
        self.assertEqual(image.getpixel((0,0)),(16,18,22))

    def test_unknown_coordinate_version_is_rejected(self):
        mesh,world=self.fixture('ambiguous-v0')
        with patch('bugbits.worlddb.parse_world',return_value=world), \
             patch.object(bake.v3d,'parse_world_meshes',return_value=[mesh]):
            with self.assertRaises(ValueError):
                bake.terrain_meshes('world_02')


if __name__=='__main__': unittest.main()
