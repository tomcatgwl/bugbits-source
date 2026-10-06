"""First-level loaded coordinates and mesh delivery at public boundaries."""
import sys
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from bugbits import web_build, web_geometry, worlddb
from bugbits.assets import data_dir


class World01MeshDelivery(unittest.TestCase):
    def test_first_level_uses_loaded_entity_coordinates_once(self):
        world = worlddb.parse_world(data_dir('worlds', 'world_01.vsc'))
        self.assertEqual(world.basis_version, 'loaded-yup-v1')
        # Original StartLeft0 Position, independently permuted by Q=(-B,-C,A).
        for actual, expected in zip(world.start(0, 0).grid_pos,
                                    (-24.8668556213, -2.7717857361, -185.7672882080)):
            self.assertAlmostEqual(actual, expected, delta=1e-9)
        self.assertEqual(world.start(0, 0).direction,
                         (-0.6352288723, 0.0000001752, 0.7723239660))

    def test_first_level_has_mesh_camera_without_legacy_sprite_presets(self):
        world = worlddb.parse_world(data_dir('worlds', 'world_01.vsc'))
        self.assertEqual(web_build.camera_presets_for('world_01', world, ['ant']), {})
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as output:
            assets = web_geometry.export_geometry_assets(['ant'], ['world_01'],
                out_dir=output, pose_policy='engine-pose-v1', sample_hz=1,
                min_frames=2, max_frames=2)
            presets = web_build.mesh_presets_for({'world_01': world},
                {'world_01': ['ant']}, assets, output)
            self.assertEqual(set(presets), {'world_01'})
            record = presets['world_01']
            self.assertEqual(record['world'], 'world_01')
            self.assertEqual(record['worldBasisVersion'], 'loaded-yup-v1')
            self.assertEqual(record['geometrySHA256'], assets['sha256'])
            web_build.validate_mesh_projection_record(record, world='world_01',
                world_basis_version='loaded-yup-v1', geometry_sha256=assets['sha256'])
            for change in ({'sha256': '0'*64}, {'file': '../scene.json'}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    web_build.mesh_presets_for({'world_01': world},
                        {'world_01': ['ant']}, dict(assets, **change), output)
            scene_path = Path(output)/assets['file']
            original = json.loads(scene_path.read_bytes())
            for change in ('basis', 'world', 'schema', 'posePolicy'):
                scene = copy.deepcopy(original)
                if change == 'basis':
                    scene['worlds']['world_01']['basisVersion'] = 'legacy-grid-v1'
                elif change == 'world':
                    scene['worlds']['world_03'] = scene['worlds'].pop('world_01')
                else:
                    scene[change] = 'unsupported-contract'
                raw = json.dumps(scene).encode()
                scene_path.write_bytes(raw)
                changed = dict(assets, sha256=hashlib.sha256(raw).hexdigest())
                with self.subTest(change=change), self.assertRaises(ValueError):
                    web_build.mesh_presets_for({'world_01': world},
                        {'world_01': ['ant']}, changed, output)


if __name__ == '__main__':
    unittest.main()
