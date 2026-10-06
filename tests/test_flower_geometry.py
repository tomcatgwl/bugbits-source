"""Real flower public export acceptance; original inputs stay read-only."""
import json
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugbits import web_geometry
from bugbits.assets import data_dir, v3d


def export_scene(worlds, root, **options):
    result = web_geometry.export_flower_geometry_assets(worlds, out_dir=root, **options)
    return result, json.loads((Path(root) / result['file']).read_text())


class FlowerGeometryTests(unittest.TestCase):
    def test_uv_reference_scope_is_limited_to_normal_flower_asset(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            _, scene = export_scene(('world_01',), root,
                prop_variants_by_world={'world_01': ('normal', 'rescue')})
            normal = scene['props']['flower_a']
            rescue = scene['props']['flower_a_swap']
            self.assertIs(normal['textureVFlip'], False)
            self.assertEqual(normal['textureUvScope'], 'observed-normal-flower-a-v1')
            self.assertIs(rescue['textureVFlip'], True)
            self.assertEqual(rescue['textureUvScope'], 'engineering-explicit-v1')
            for change in ({'textureVFlip': 0}, {'textureUvScope': 'unknown'},
                           {'textureVFlip': True}, {'assetId': 'flower_a_swap'}):
                bad = copy.deepcopy(scene)
                bad['props']['flower_a'].update(change)
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'texture UV'):
                    web_geometry.validate_geometry(bad)
            for field in ('textureVFlip', 'textureUvScope'):
                bad = copy.deepcopy(scene)
                del bad['props']['flower_a'][field]
                with self.assertRaisesRegex(ValueError, 'texture UV'):
                    web_geometry.validate_geometry(bad)
            bad = copy.deepcopy(scene)
            bad['props']['flower_a_swap'].update(textureVFlip=False,
                textureUvScope='observed-normal-flower-a-v1')
            with self.assertRaisesRegex(ValueError, 'texture UV'):
                web_geometry.validate_geometry(bad)

    def test_loaded_bind_root_uses_original_float32_rotation_once(self):
        import math
        import struct
        phi = struct.unpack('<f', bytes.fromhex('db0fc9bf'))[0]
        c, s = math.cos(phi), math.sin(phi)
        expected = [1,0,0,0, 0,c,s,0, 0,-s,c,0, 0,0,0,1]
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            _, scene = export_scene(('world_01',), root)
            prop = scene['props']['flower_a']
            self.assertEqual(prop['rootPolicy'], 'original-load-bind-S-v1')
            self.assertEqual(prop['rootMatrix'], expected)
            self.assertFalse(prop['rootApplied'])
            self.assertFalse(prop['scaleApplied'])
            raw, _, _, _ = v3d.parse_v3d_groups(data_dir('models', 'props', 'flower_a.v3d'))
            self.assertEqual(prop['positions'], [float(x) for v in raw for x in v[0]])
            for matrix in ([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
                           [1,0,0,0,0,c,-s,0,0,s,c,0,0,0,0,1]):
                wrong = copy.deepcopy(scene)
                wrong['props']['flower_a']['rootMatrix'] = matrix
                with self.assertRaisesRegex(ValueError, 'prop bind policy'):
                    web_geometry.validate_geometry(wrong)

    def test_world01_five_real_flower_instances(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            result = web_geometry.export_flower_geometry_assets(('world_01',), out_dir=root)
            scene = json.loads((Path(root) / result['file']).read_text())
            instances = scene['worlds']['world_01']['propInstances']
            self.assertEqual(len(instances), 5)
            self.assertEqual({p['assetId'] for p in instances}, {'flower_a'})
            self.assertTrue(all(p['scaleFactor'] == 2.5 for p in instances))
            self.assertEqual(set(scene['units']), set())
            self.assertEqual(scene['props']['flower_a']['anchorPolicy'], 'raw-model-origin-v1')
            web_geometry.validate_geometry_sources(scene, scene['inputHashes'], require_all_units=False)

    def test_real_uv_normals_groups_and_owner_direction(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            _, scene = export_scene(('world_01',), root)
            original, groups, _, _ = v3d.parse_v3d_groups(data_dir('models', 'props', 'flower_a.v3d'))
            prop = scene['props']['flower_a']
            for field, index in (('positions', 0), ('normals', 1), ('uvs', 2)):
                self.assertEqual(prop[field], [float(x) for v in original for x in v[index]])
            for actual, (indices, texture) in zip(prop['groups'], groups):
                self.assertEqual(actual['indices'], list(indices))
                if texture:
                    self.assertEqual(scene['textures'][actual['texture']]['source'], 'textures/' + texture + '.vtx')
            flower = next(p for p in scene['worlds']['world_01']['propInstances'] if p['name'] == 'Flower2')
            self.assertEqual(flower['directionRaw'], [0,1,0])
            self.assertEqual(flower['positionYup'], [-83.6097259521,2.3150925636,-50.7187004089])
            # Independent non-symmetric raw points: scale then raw Rz(+90), then Q.
            for point, expected in (((11,23,5),(-27.5,-12.5,-57.5)),
                                    ((-7,3,21),(17.5,-52.5,-7.5)),
                                    ((2,-13,-4),(-5,10,32.5))):
                x,y,z = (v * 2.5 for v in point)
                yup = [-y,-z,x]
                owner = flower['ownerMatrix']
                actual = [sum(yup[k] * owner[k*4+j] for k in range(3)) for j in range(3)]
                self.assertEqual(actual, list(expected))
            broken = copy.deepcopy(scene); broken['props']['flower_a']['modelSHA'] = '0'*64
            with self.assertRaises(ValueError):
                web_geometry.validate_geometry_sources(broken, scene['inputHashes'], require_all_units=False)
            broken = copy.deepcopy(scene); broken['worlds']['world_01']['propInstances'][0]['ownerMatrix'][0] += .1
            with self.assertRaises(ValueError): web_geometry.validate_geometry(broken)

    def test_type2_real_export_and_unverified_rescue_binding(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            _, scene = export_scene(('world_03',), root)
            self.assertEqual(set(scene['props']), {'flower_a','flower_b'})
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            # Original type2 rescue mutates an existing model's material;
            # unknown model identity is an engineering support boundary.
            with self.assertRaisesRegex(ValueError, '^unverified original type2 rescue model binding$'):
                export_scene(('world_03',), root, rescue_worlds=('world_03',))
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_real_rescue1_and_type3_fixture_using_original_model(self):
        with tempfile.TemporaryDirectory(dir='tmp') as root:
            _, scene = export_scene(('world_01',), root, rescue_worlds=('world_01',))
            self.assertEqual(set(scene['props']), {'flower_a_swap'})
            rescue=scene['props']['flower_a_swap']
            self.assertEqual(rescue['animationScope'], 'raw-bind-only-unverified')
            self.assertNotIn('animationRig', rescue)
            self.assertNotIn('animationSkin', rescue)
            # Original49E81B loader first float is 4, unlike normal49E858=2.5.
            self.assertTrue(all(p['scaleFactor']==4.0 for p in scene['worlds']['world_01']['propInstances']))
        # An explicitly modified VSC fixture selects the real cactus model. The
        # source world_01 is never edited; this is not an original level claim.
        actual_data = Path(data_dir())
        with tempfile.TemporaryDirectory(dir='tmp') as fixture, tempfile.TemporaryDirectory(dir='tmp') as root:
            base = Path(fixture); (base/'data/worlds').mkdir(parents=True)
            for directory in ('models','textures'):
                (base/'data'/directory).symlink_to(actual_data/directory, target_is_directory=True)
            source = (actual_data/'worlds/world_01.vsc').read_text()
            (base/'data/worlds/world_01.vsc').write_text(source.replace('"FlowerType" 1.0000000000', '"FlowerType" 3.0000000000'))
            with patch.dict(os.environ, BUGBITS_DATA=str(base.resolve())):
                _, scene = export_scene(('world_01',), root)
                self.assertEqual(set(scene['props']), {'cactus_a'})
                self.assertEqual(scene['props']['cactus_a']['animationRig']['assetId'], 'cactus_a')
                self.assertEqual(scene['props']['cactus_a']['animationScope'], 'normal-flower-node-keys-v1')
                self.assertTrue(all(p['scaleFactor']==1 for p in scene['worlds']['world_01']['propInstances']))
                original, _, _, _ = v3d.parse_v3d_groups(data_dir('models','props','cactus_a.v3d'))
                self.assertEqual(scene['props']['cactus_a']['positions'], [float(x) for v in original for x in v[0]])

    def test_missing_named_texture_with_real_fixture_fails(self):
        actual_data = Path(data_dir())
        with tempfile.TemporaryDirectory(dir='tmp') as fixture, tempfile.TemporaryDirectory(dir='tmp') as root:
            base=Path(fixture); (base/'data/worlds').mkdir(parents=True); (base/'data/textures').mkdir()
            (base/'data/models').symlink_to(actual_data/'models', target_is_directory=True)
            (base/'data/worlds/world_01.vsc').write_bytes((actual_data/'worlds/world_01.vsc').read_bytes())
            with patch.dict(os.environ, BUGBITS_DATA=str(base.resolve())):
                with self.assertRaises(FileNotFoundError): export_scene(('world_01',), root)


if __name__ == '__main__':
    unittest.main()
