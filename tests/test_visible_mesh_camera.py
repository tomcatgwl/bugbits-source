"""A native spawn view must cover real lane starts without changing unit scale."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bugbits import web_build,worlddb
from bugbits.assets import data_dir

class VisibleMeshCameraTests(unittest.TestCase):
    def test_real_friendly_spawns_and_flying_height_fit_in_visible_content(self):
        for name in ('world_01','world_02','world_03'):
            world=worlddb.parse_world(data_dir('worlds',name+'.vsc'))
            cam=web_build.mesh_birth_camera(world,(15,-10,15))
            fly=float(world.props['FlyHeight'][0])
            for start in world.starts:
                if start.side_id!=0:continue
                for dx in (-15,15):
                    for dy in (-10,fly+15):
                        for dz in (-15,15):
                            px,py,z=cam.world_to_pixel_depth(start.grid_pos[0]+dx,start.grid_pos[1]+dy,start.grid_pos[2]+dz)
                            with self.subTest(world=name,start=start.index,offset=(dx,dy,dz)):
                                self.assertGreaterEqual(z,cam.near);self.assertLessEqual(z,cam.far)
                                self.assertGreater(px,cam.size_px*cam.aspect*.09)
                                self.assertLess(px,cam.size_px*cam.aspect*.91)
                                self.assertGreater(py,cam.size_px*.13);self.assertLess(py,cam.size_px*.87)
            self.assertEqual(cam.near,1);self.assertEqual(cam.far,1000)

    def test_invalid_volume_is_rejected(self):
        world=worlddb.parse_world(data_dir('worlds','world_02.vsc'))
        for value in ((-1,0,1),(1,2,1),(math.nan,0,1),(True,0,1)):
            with self.subTest(value=value),self.assertRaises(ValueError):
                web_build.mesh_birth_camera(world,value)
