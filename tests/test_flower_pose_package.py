"""Real world JSON and copied original sources at the package closure seams.

No rendering, original input mutation, or mocked source hashes. These tests
exercise the same public closure functions called by export and validate;
they are not a full resource package/build acceptance test.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch

from bugbits import web_build, web_data, worlddb
from bugbits.assets import data_dir


class FlowerPosePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=worlddb.parse_world(data_dir('worlds','world_01.vsc'))
        cls.packet=web_data.world_to_dict(cls.world)
        cls.hashes={rig[k+'Source']:rig[k+'SHA']
                    for rig in cls.world.flower_rigs.values() for k in ('model','animation')}

    def test_serialized_world_cannot_remove_identity_and_rigs(self):
        with tempfile.TemporaryDirectory(dir='tmp') as directory:
            root=Path(directory);(root/'worlds').mkdir()
            path=root/'worlds/world_01.json'
            manifest={'levels':[{'deps':{'world':'world_01'}}], 'inputHashes':self.hashes}
            path.write_text(json.dumps(self.packet))
            self.assertEqual(web_build.validate_package_worlds(root,manifest),[])
            stripped=copy.deepcopy(self.packet)
            stripped.pop('worldId')
            stripped.update(flowerRigs={},flowerRigContract=None)
            # Generic historical migration remains supported, package use does not.
            self.assertIsNone(web_data.restore_world(stripped).world_id)
            path.write_text(json.dumps(stripped))
            self.assertEqual(web_build.validate_package_worlds(root,manifest),
                ['world_01: world ID differs from level dependency'])

    def test_final_fingerprint_rejects_survey_source_drift_and_missing_source(self):
        original=Path(data_dir())
        with tempfile.TemporaryDirectory(dir='tmp') as directory:
            root=Path(directory).resolve();paths=[]
            for relative in self.hashes:
                target=root/'data'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(original/relative,target);paths.append(str(target))
            with patch.dict(os.environ,BUGBITS_DATA=str(root)):
                hashes,_=web_build.finalize_world_inputs(paths,'slice',{'world_01':self.world})
                self.assertEqual(dict(hashes),self.hashes)
                animation=next(Path(p) for p in paths if p.endswith('.van'))
                original_bytes=animation.read_bytes()
                # Survey retained original keys/SHA. Final fingerprint sees a
                # real changed file, independent of geometry's later read.
                animation.write_bytes(original_bytes[:-1]+bytes([original_bytes[-1]^1]))
                with self.assertRaisesRegex(ValueError,'world flower rig outside original input closure'):
                    web_build.finalize_world_inputs(paths,'slice',{'world_01':self.world})
                animation.unlink()
                with self.assertRaises(FileNotFoundError):
                    web_build.finalize_world_inputs(paths,'slice',{'world_01':self.world})

    def test_package_missing_source_digest_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='tmp') as directory:
            root=Path(directory);(root/'worlds').mkdir()
            (root/'worlds/world_01.json').write_text(json.dumps(self.packet))
            manifest={'levels':[{'deps':{'world':'world_01'}}], 'inputHashes':dict(self.hashes)}
            manifest['inputHashes'].pop('models/props/flower_a.van')
            self.assertEqual(web_build.validate_package_worlds(root,manifest),
                ['world_01: world flower rig outside original input closure'])

    def test_world_survives_actual_javascript_json_transport_with_original_rig_stores(self):
        result = subprocess.run(['node', '-e',
            "const fs=require('node:fs');console.log(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8'))));"],
            input=json.dumps(self.packet), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        wire = json.loads(result.stdout)
        restored = web_data.restore_world(wire)
        for asset, original in self.world.flower_rigs.items():
            actual = restored.flower_rigs[asset]
            self.assertEqual(actual['rigSHA256'], original['rigSHA256'])
            for expected_node, actual_node in zip(original['nodes'], actual['nodes']):
                self.assertEqual(struct.pack('<16f', *actual_node['bind']),
                                 struct.pack('<16f', *expected_node['bind']))
                for expected_key, actual_key in zip(expected_node['keys'], actual_node['keys']):
                    self.assertEqual(struct.pack('<7f', *actual_key), struct.pack('<7f', *expected_key))
        changed = copy.deepcopy(wire)
        changed['flowerRigs']['flower_a']['nodes'][0]['bind'][15] = True
        with self.assertRaisesRegex(ValueError, 'source text values differ'):
            web_data.restore_world(changed)
        changed = copy.deepcopy(wire)
        changed['flowerRigs']['flower_a']['nodes'][0]['bind'][12] += .000001
        with self.assertRaisesRegex(ValueError, 'source text values differ'):
            web_data.restore_world(changed)
        changed = copy.deepcopy(wire)
        changed['flowerRigs']['flower_a']['rigSHA256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'rig digest mismatch'):
            web_data.restore_world(changed)

    def test_current_package_requires_source_text_for_worker_transport(self):
        historical = copy.deepcopy(self.packet)
        historical.pop('flowerRigJsons')
        # The direct historical Python decoder remains strict and supported.
        self.assertEqual(web_data.restore_world(historical).flower_rigs, self.world.flower_rigs)
        with tempfile.TemporaryDirectory(dir='tmp') as directory:
            root = Path(directory)
            (root / 'worlds').mkdir()
            (root / 'worlds/world_01.json').write_text(json.dumps(historical))
            manifest = {'levels': [{'deps': {'world': 'world_01'}}], 'inputHashes': self.hashes}
            self.assertEqual(web_build.validate_package_worlds(root, manifest),
                             ['world_01: flower rig source text required for worker transport'])

    def test_wire_rig_source_text_must_keep_original_canonical_bytes(self):
        changed = copy.deepcopy(self.packet)
        changed['flowerRigJsons']['flower_a'] = ' ' + changed['flowerRigJsons']['flower_a']
        with self.assertRaisesRegex(ValueError, 'canonical source text required'):
            web_data.restore_world(changed)


if __name__=='__main__':unittest.main()
