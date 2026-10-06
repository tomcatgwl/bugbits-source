"""Original raw V/P expectations, scoped production preset and host selection."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bugbits import web_build


class CapturedFirstLevelCameraTests(unittest.TestCase):
    def test_host_source_capsule_keeps_classic_script_strict_mode(self):
        script = r"""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const host=fs.readFileSync('web/host.js','utf8');
const prefix=host.slice(0,host.indexOf('// BugBits Web 宿主'));
const context=vm.createContext({});
assert.throws(()=>vm.runInContext(prefix+'\n__bb_undeclared_strict_probe=7;',context),
              error=>error.name==='ReferenceError');
assert.strictEqual(Object.hasOwn(context,'__bb_undeclared_strict_probe'),false);
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def packet(self):
        from bugbits.captured_camera import captured_packet
        return captured_packet()

    def record(self):
        source = self.packet()['cameraSource']['inputs']
        raw_hashes = {k.split('/data/')[1]: v for k, v in source.items() if '/data/' in k}
        return web_build.captured_first_level_camera_record(level_id='level_01', level_type='gather',
            world='world_01', world_basis_version='loaded-yup-v1', geometry_sha256='a'*64,
            input_hashes=raw_hashes), raw_hashes

    def test_production_projection_against_original_four_dimensional_rows(self):
        record, hashes = self.record()
        source = record['cameraSource']
        v = struct.unpack('<16f', bytes.fromhex(source['viewRawHex']))
        p = struct.unpack('<16f', bytes.fromhex(source['projectionRawHex']))
        cam = web_build.matrix_projection_camera(record['projection'])
        for point in ((0,0,0), (11,23,5), (-211,30,-10), (20,-11,17)):
            view = [sum((*point,1)[k]*v[4*k+j] for k in range(4)) for j in range(4)]
            clip = [sum(view[k]*p[4*k+j] for k in range(4)) for j in range(4)]
            expected = ((1+clip[0]/clip[3])*768*(p[5]/p[0])/2,
                        (1-clip[1]/clip[3])*768/2, view[2])
            actual = cam.world_to_pixel_depth(-point[1],-point[2],point[0])
            for a, b in zip(actual, expected):
                self.assertAlmostEqual(a, b, delta=1e-7)
        self.assertNotIn('meshView', record)
        self.assertFalse(source['atomicFrame'])
        self.assertFalse(source['originalDynamicFollowVerified'])
        self.assertEqual(self.record()[0], record)
        record['cameraSource']['inputs'].clear()
        self.assertTrue(self.record()[0]['cameraSource']['inputs'])

    def test_bad_scope_sources_and_projection_are_rejected(self):
        record, hashes = self.record()
        base = dict(level_id='level_01', level_type='gather', world='world_01',
                    world_basis_version='loaded-yup-v1', geometry_sha256='a'*64, input_hashes=hashes)
        for key, value in (('level_id','rescue_01'), ('level_type','rescue'),
                           ('world','world_02'), ('world_basis_version','legacy-grid-v1')):
            with self.subTest(field=key), self.assertRaises(ValueError):
                web_build.captured_first_level_camera_record(**{**base, key:value})
        for key in hashes:
            with self.assertRaises(ValueError):
                web_build.captured_first_level_camera_record(**{**base,'input_hashes':{**hashes,key:'0'*64}})
        for mutate in ('source','matrix','scope','view','missing-source','missing-scope'):
            bad = copy.deepcopy(record)
            if mutate == 'source': bad['cameraSource']['sampleSHA256'] = '0'*64
            if mutate == 'matrix': bad['projection']['cameraPosition'][0] += 1; bad['camera'] = copy.deepcopy(bad['projection'])
            if mutate == 'scope': bad['applicability']['variant'] = 'rescue'
            if mutate == 'view': bad['meshView'] = {'targetYup':[0,0,0], 'distance':1}
            if mutate == 'missing-source': del bad['cameraSource']
            if mutate == 'missing-scope': del bad['applicability']
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                web_build.validate_mesh_projection_record(bad, world='world_01',
                    world_basis_version='loaded-yup-v1', geometry_sha256='a'*64)

    def test_host_selects_only_matching_normal_first_level_and_rejects_mutation(self):
        record, _ = self.record()
        js = """
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const packet=JSON.parse(fs.readFileSync(0,'utf8'));
const host=fs.readFileSync('web/host.js','utf8'),ctx=vm.createContext({});
vm.runInContext(host.slice(host.indexOf('const CAPTURED_FIRST_LEVEL_CAMERA'),host.indexOf('// Captured camera contract end')),ctx);
vm.runInContext(host.slice(host.indexOf('const NEAR_CAMERA_PRESET'),host.indexOf('// A16')),ctx);
vm.runInContext(host.slice(host.indexOf('function defaultCameraPresetFor('),host.indexOf('// Default camera selection end')),ctx);
assert(ctx.capturedCameraApplicable(packet,'level_01','gather','world_01'));
const presets={original_static_01:packet,mesh_cam:{}};
assert.strictEqual(ctx.defaultCameraPresetFor('world_01',presets,'level_01','gather'),'original_static_01');
assert.strictEqual(ctx.defaultCameraPresetFor('world_01',presets,'rescue_01','rescue'),'mesh_cam');
assert.strictEqual(ctx.defaultCameraPresetFor('world_02',presets,'level_02','battle'),'mesh_cam');
for(const change of [x=>x.cameraSource.sampleSHA256='bad',x=>x.projection.cameraPosition[0]++,x=>x.applicability.variant='rescue',x=>x.meshView={}]){
const bad=structuredClone(packet);change(bad);assert(!ctx.capturedCameraApplicable(bad,'level_01','gather','world_01'));}
"""
        result = subprocess.run(['node','-e',js], cwd=ROOT, input=json.dumps(record),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
