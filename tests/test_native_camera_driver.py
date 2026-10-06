"""Camera state through real loaded-world Bridge and public host consumers."""
import unittest
import json
import subprocess
import math
from pathlib import Path

from bugbits import level, unitdb, web_data, worlddb
from bugbits.web_bridge import WebBridge

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'analyze/extracted/ccdzz/data'


class NativeCameraDriver(unittest.TestCase):
    def opened(self):
        world = worlddb.parse_world(DATA / 'worlds/world_01.vsc', basis='loaded-yup-v1')
        lv = level.parse_level(DATA / 'scripts/levels/level_01.vsc')
        payload = (web_data.level_to_dict(lv), web_data.world_to_dict(world),
                   {'ant': web_data.unit_to_dict(unitdb.load_unit('ant'))}, {'buyable': ['ant']})
        bridge = WebBridge()
        bridge.init('level_01', 2026, *payload)
        return bridge, payload

    def test_loaded_first_level_primes_camera_before_publishing_state(self):
        bridge, _ = self.opened()
        camera = bridge.snapshot()['nativeCamera']
        self.assertEqual(camera['scope'], 'normal-camera-static-branches-outer20hz-v1')
        self.assertEqual(camera['distance'], 309.6282958984375)
        self.assertEqual(camera['goalDistance'], 275.1153869628906)
        self.assertEqual(camera['targetRaw'], [0., -25., 0.])
        self.assertEqual(camera['virtualWidth'], 1600)
        self.assertIsNone(camera['trackedId'])
        self.assertEqual(camera['cameraMode'], 3)
        self.assertEqual(camera['preDriverMode'], 0)
        self.assertEqual(camera['generation'], 0)
        self.assertEqual(camera['view']['basisGeneration'], 0)
        self.assertEqual(bridge.audit_state()['nativeCamera'], camera)

    def test_script_focus_advances_before_physics_and_keeps_distinct_view_generations(self):
        bridge,payload=self.opened()
        initial=bridge.snapshot()['nativeCamera']
        bridge.advance(1)
        first=bridge.snapshot()
        actor=first['bugs'][0]
        camera=first['nativeCamera']
        self.assertEqual(camera['trackedId'],actor['id'])
        self.assertEqual(camera['preDriverMode'],1)  # Native normal-play script precedes world.
        self.assertEqual(camera['generation'],1)
        self.assertEqual(camera['view'],camera['worldView'])
        self.assertNotEqual(camera['view'],initial['view'])
        self.assertEqual((camera['worldView']['basisGeneration'],camera['worldView']['eyeGeneration']),(0,1))
        bridge.advance(1)
        camera=bridge.snapshot()['nativeCamera']
        self.assertEqual(camera['preDriverMode'],1)
        self.assertEqual((camera['view']['basisGeneration'],camera['view']['eyeGeneration']),(1,2))
        self.assertEqual((camera['worldView']['basisGeneration'],camera['worldView']['eyeGeneration']),(1,2))
        self.assertEqual(camera['e8Generation'],2)
        self.assertNotEqual(camera['targetRaw'],initial['targetRaw'])
        camera['view']['cameraPosition'][0]=99999
        self.assertNotEqual(bridge.audit_state()['nativeCamera']['view']['cameraPosition'][0],99999)
        bridge.reset('level_01',2026,*payload)
        self.assertEqual(bridge.snapshot()['nativeCamera'],initial)

    def test_native_tracked_half_width_clamp_and_literal_stores(self):
        from bugbits.sim.camera import NativeCamera
        props={k:[str(v)] for k,v in dict(MinCamDistance=180,MaxCamDistance=400,
            MinAngle=.7,MaxYaw=.4,Width=350,Height=200).items()}
        props['Offset']=['0','0','0']
        camera=NativeCamera(props,virtual_width=1280)
        camera.distance=180.
        camera.target_raw=(0.,0.,0.)
        camera.focus(7)
        sample={'id':7,'positionRaw':(200.,23.,0.),'dialogueDuration':10.,'dialogueElapsed':7.}
        camera.advance(.125,sample)
        self.assertEqual(camera.snapshot()['targetRaw'][0],32.8125)
        camera.distance=600.
        camera.target_raw=(.10000000149011612,0.,0.)
        camera.yaw=0.
        sample['positionRaw']=(11.,23.,0.)
        camera.advance(.125,sample)
        state=camera.snapshot()
        self.assertEqual(state['distance'],435.9375)
        self.assertEqual(state['targetRaw'],[.8869141340255737,1.6845703125,0.])
        self.assertEqual(state['pitch'],.2734375)
        self.assertEqual(state['yaw'],-.00033147321664728224)
        self.assertEqual(state['trackedId'],7)
        sample['dialogueElapsed']=7.125
        camera.advance(0.,sample)
        self.assertIsNone(camera.snapshot()['trackedId'])
        self.assertEqual(camera.snapshot()['preDriverMode'],1)
        camera.advance(0.)
        self.assertEqual(camera.snapshot()['preDriverMode'],0)

    def test_actual_host_frame_consumes_submitted_view_and_selects_dynamic_preset(self):
        from bugbits import web_build
        from test_mesh_zoom_controls import SETUP
        bridge,payload=self.opened()
        bridge.advance(3)
        snapshot=bridge.snapshot()
        world=web_data.restore_world(payload[1])
        preset=web_build.native_camera_record(world,geometry_sha256='1'*64)
        js=SETUP+r'''
const input=JSON.parse(fs.readFileSync(0,'utf8'));
vm.runInContext(host.slice(0,host.indexOf('// Captured camera contract end')),scope);
render.activePreset=input.preset;render.activePresetKey='native_camera';
state.lastSnapshot={...input.snapshot,bugs:[],flowers:[]};
scope.NEAR_CAMERA_PRESET='near_camera';
vm.runInContext(host.slice(host.indexOf('function defaultCameraPresetFor('),host.indexOf('// Default camera selection end')),scope);
render.meshAssets.units.ant={clips:{walk:{kind:'sampled',frames:[{}],duration:1}}};
scope.renderFrame(50);
assert.deepEqual(Array.from(frames.at(-1).basis9),input.snapshot.nativeCamera.view.basis9);
assert.deepEqual(Array.from(frames.at(-1).cameraPosition),input.snapshot.nativeCamera.view.cameraPosition);
const before=JSON.stringify(state.lastSnapshot.nativeCamera);
scope.renderFrame(999999);scope.window.devicePixelRatio=2;scope.renderFrame(5000000);
assert.equal(JSON.stringify(state.lastSnapshot.nativeCamera),before);
assert.deepEqual(Array.from(frames.at(-1).cameraPosition),input.snapshot.nativeCamera.view.cameraPosition);
assert.equal(scope.defaultCameraPresetFor('world_01',{native_camera:input.preset},'level_01','gather'),'native_camera');
assert.equal(scope.defaultCameraPresetFor('world_01',{native_camera:input.preset},'level_01','gather',true),null);
'''
        result=subprocess.run(['node','-e',js],cwd=ROOT,text=True,capture_output=True,
            input=json.dumps({'preset':preset,'snapshot':snapshot}),timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_nonzero_yaw_projection_matches_independent_raw_point_literal(self):
        from bugbits.sim.camera import NativeCamera
        props={k:[str(v)] for k,v in dict(MinCamDistance=100,MaxCamDistance=400,
            MinAngle=math.pi/6,MaxYaw=.4,Width=350,Height=200).items()}
        props['Offset']=['0','0','0']
        camera=NativeCamera(props,virtual_width=1280)
        camera.distance=100.
        camera.target_raw=(11.,23.,5.)
        camera.yaw=math.pi/2
        camera.focus(7)
        sample={'id':7,'positionRaw':(11.,23.,5.),'dialogueDuration':10.,'dialogueElapsed':7.}
        for _ in range(2):
            camera.advance(0.,sample)
            camera.finish_frame()
        view=camera.snapshot()['view']
        for actual,expected in zip(view['cameraPosition'],(-23.,50*math.sqrt(3)-5,61.)):
            self.assertAlmostEqual(actual,expected,delta=5e-5)
        js=r'''
const fs=require('node:fs'),camera=require('./web/camera_projection.js');
const view=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(camera.cameraSpace({...view,kind:'matrix-yup-v1',
  size:768,cot:Math.sqrt(3),aspect:4/3,near:1,far:1000},[-26,-9,13])));
'''
        result=subprocess.run(['node','-e',js],cwd=ROOT,text=True,capture_output=True,
                              input=json.dumps(view),timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        for actual,expected in zip(json.loads(result.stdout),(3.,-math.sqrt(3)-2,99+2*math.sqrt(3))):
            self.assertAlmostEqual(actual,expected,delta=5e-5)

    def test_parent_domain_rejects_scale_and_reflection_before_publication(self):
        from bugbits.sim.camera import NativeCamera, IDENTITY
        _,payload=self.opened()
        for coefficient in (2.,-1.):
            parent=list(IDENTITY)
            parent[0]=coefficient
            with self.subTest(coefficient=coefficient),self.assertRaises(ValueError):
                NativeCamera(payload[1]['props'],incoming_world=parent)

    def test_native_packet_validator_and_host_reject_mislabelled_frustum(self):
        from bugbits import web_build
        from test_mesh_zoom_controls import SETUP
        _,payload=self.opened()
        world=web_data.restore_world(payload[1])
        valid=web_build.native_camera_record(world,geometry_sha256='1'*64)
        for field,value in (('nativeCameraContract','wrong'),('nativeCameraQualification','wrong')):
            bad=json.loads(json.dumps(valid));bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                web_build.validate_native_camera_record(bad,world)
        missing=json.loads(json.dumps(valid));missing.pop('nativeCameraContract')
        with self.assertRaises(ValueError):web_build.validate_native_camera_record(missing,world)
        bad=json.loads(json.dumps(valid));bad['projection']['aspect']=1.6;bad['camera']['aspect']=1.6
        with self.assertRaises(ValueError):web_build.validate_native_camera_record(bad,world)
        pose=json.loads(json.dumps(valid));pose['projection']['cameraPosition'][0]+=1
        pose['camera']['cameraPosition'][0]+=1
        with self.assertRaises(ValueError):web_build.validate_native_camera_record(pose,world)
        js=SETUP+r'''
const preset=JSON.parse(fs.readFileSync(0,'utf8'));
vm.runInContext(host.slice(0,host.indexOf('// Captured camera contract end')),scope);
scope.NEAR_CAMERA_PRESET='near_camera';
vm.runInContext(host.slice(host.indexOf('function defaultCameraPresetFor('),host.indexOf('// Default camera selection end')),scope);
assert.equal(scope.defaultCameraPresetFor('world_01',{native_camera:preset},'level_01','gather'),null);
'''
        result=subprocess.run(['node','-e',js],cwd=ROOT,text=True,capture_output=True,
                              input=json.dumps(bad),timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
