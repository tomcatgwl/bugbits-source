"""Normal flower packet closure, independent of browser/render execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bugbits import web_geometry as geometry


class FlowerPoseExportTests(unittest.TestCase):
    def scene(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            result = geometry.export_flower_geometry_assets(('world_03',), out_dir=root)
            return json.loads((Path(root) / result['file']).read_text()), result

    def test_normal_rig_skin_sources_and_bind_attachment(self):
        scene, result = self.scene()
        for asset, prop in scene['props'].items():
            self.assertEqual(prop['animationScope'], 'normal-flower-node-keys-v1')
            rig = prop['animationRig']
            self.assertEqual(rig['assetId'], asset)
            self.assertEqual(rig['nektarNode'], prop['attachments']['nektar']['node'])
            self.assertEqual(len(prop['animationSkin']), len(prop['positions']) // 3)
            self.assertEqual(scene['inputHashes'][rig['animationSource']], rig['animationSHA'])
            self.assertTrue(any(p.endswith(rig['animationSource']) for p in result['source_paths']))
        geometry.validate_geometry_sources(scene, scene['inputHashes'], require_all_units=False)

    def test_malformed_skin_and_rig_are_rejected(self):
        scene, _ = self.scene()
        def mutate_skin(p): p['animationSkin'][0][0][0] += 1
        def mutate_bone(p): p['animationSkin'][0][2][0][0] = p['nodeCount']
        def mutate_weight(p): p['animationSkin'][0][2][0][1] = float('nan')
        def mutate_count(p): p['animationSkin'].pop()
        def mutate_scope(p): p['animationScope'] = 'raw-bind-only-unverified'
        def mutate_rig(p): p['animationRig']['assetId'] = 'flower_b'
        def mutate_attachment(p): p['attachments']['nektar']['positionRaw'][0] += 1
        for change in (mutate_skin, mutate_bone, mutate_weight, mutate_count,
                       mutate_scope, mutate_rig, mutate_attachment):
            bad = copy.deepcopy(scene)
            change(bad['props']['flower_a'])
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                geometry.validate_geometry(bad)
        bad = copy.deepcopy(scene)
        del bad['inputHashes'][bad['props']['flower_a']['animationRig']['animationSource']]
        with self.assertRaises(ValueError):
            geometry.validate_geometry_sources(bad, scene['inputHashes'], require_all_units=False)
        bad = copy.deepcopy(scene)
        del bad['props']['flower_a']['animationRig']
        with self.assertRaises(ValueError):
            geometry.validate_geometry_sources(bad, scene['inputHashes'], require_all_units=False)

    def test_missing_van_fails_before_unit_sampling_or_output(self):
        resolve = geometry.bake._resolve_model
        def missing(name, suffix):
            return None if name == 'props/flower_a' and suffix == '.van' else resolve(name, suffix)
        with tempfile.TemporaryDirectory(dir='tmp') as root, patch.object(
                geometry.bake, '_resolve_model', side_effect=missing), patch.object(
                geometry.pose, 'worlds_at', side_effect=AssertionError('unit sampling reached')):
            with self.assertRaises(FileNotFoundError):
                geometry.export_geometry_assets(('ant',), ('world_01',),
                    pose_policy=geometry.POSE_POLICY, out_dir=root)
            self.assertEqual(list(Path(root).iterdir()), [])
