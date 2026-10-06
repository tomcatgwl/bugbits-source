"""Exercise the actual host camera selector with an already verified scene."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MeshCameraSceneReuse(unittest.TestCase):
    def test_same_geometry_switch_is_atomic_without_reloading_assets(self):
        # The source capsule is read through the same JS binding used by the host.
        start = (ROOT / 'web/host.js').read_text().index('const CAPTURED_FIRST_LEVEL_CAMERA')
        end = (ROOT / 'web/host.js').read_text().index(';', start) + 1
        capsule = (ROOT / 'web/host.js').read_text()[start:end]
        js = r"""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const host=fs.readFileSync('web/host.js','utf8'),camera=require('./web/camera_projection.js');
""" + capsule + r"""
const original={...JSON.parse(JSON.stringify(CAPTURED_FIRST_LEVEL_CAMERA)),world:'world_01',
 worldBasisVersion:'loaded-yup-v1',applicability:{levelId:'level_01',variant:'normal',worldId:'world_01'},
 presentationScope:'engine-mesh-v1',meshContractVersion:'engine-mesh-v1',geometryFile:'scene.json',geometrySHA256:'a'.repeat(64)};
original.camera=original.projection;
const mesh={...original,projection:{...original.projection,aspect:1.6,cameraPosition:[1,200,3]},
 meshView:{targetYup:[1,0,3],distance:200}};
delete mesh.cameraSource;delete mesh.applicability;
let fetches=0,prepares=0,disposes=0,projections=[];
const scene={setProjection(p){camera.validateProjection(p);projections.push(JSON.parse(JSON.stringify(p)));},dispose(){disposes++;}};
const assets={worlds:{world_01:{basisVersion:'loaded-yup-v1'}}};
const render={worldPresets:{original_static_01:original,mesh_cam:mesh},activePreset:original,
 activePresetKey:'original_static_01',meshScene:scene,meshAssets:assets,meshSceneGeneration:1,presetReqSeq:0,presetController:null,
 presetTerrain:null,meshProjection:{},meshFollowId:'auto',meshZoomFactor:2,meshTargetYup:[9,9,9]};
const state={generation:1,world:'world_01',worldBasisVersion:'loaded-yup-v1',levelId:'level_01',manifest:{levels:[{id:'level_01',type:'gather'}]}};
const ctx=vm.createContext({render,state,BugBitsCameraProjection:camera,CAPTURED_FIRST_LEVEL_CAMERA,
 BugBitsMeshScene:{prepareMeshScene:async()=>{prepares++;throw Error('unexpected prepare');}},
 fetch:async()=>{fetches++;throw Error('unexpected fetch');},AbortController,DOMException,
 setTimeout,clearTimeout,CAMERA_LOAD_TIMEOUT_MS:8000,$:()=>null,
 syncStageGeometry(){},CANVAS_SIZE:640});
vm.runInContext(host.slice(host.indexOf('function capturedCameraApplicable('),host.indexOf('// Captured camera contract end')),ctx);
vm.runInContext(host.slice(host.indexOf('function closePresetBitmap('),host.indexOf('// ── 音频')),ctx);
// Keep real commitCameraView, only stage/DOM publication is external to this seam.
ctx.syncStageGeometry=()=>{};
ctx.$=()=>null;
(async()=>{
 assert.strictEqual(await ctx.setCameraPreset('mesh_cam'),true,'same verified geometry must switch without reload');
 assert.strictEqual(render.activePresetKey,'mesh_cam');assert.strictEqual(render.meshScene,scene);
 assert.strictEqual(render.meshAssets,assets);assert.strictEqual(render.meshProjection,null);
 assert.strictEqual(render.meshFollowId,null);assert.strictEqual(render.meshZoomFactor,1);
 assert.strictEqual(projections.at(-1).aspect,1.6);
 assert.strictEqual(await ctx.setCameraPreset('original_static_01'),true);
 assert.strictEqual(render.activePresetKey,'original_static_01');
 assert.deepStrictEqual(projections.at(-1),original.projection);
 const old=render.activePreset;scene.setProjection=()=>{throw Error('context lost');};
 assert.strictEqual(await ctx.setCameraPreset('mesh_cam'),false);
 assert.strictEqual(render.activePreset,old);assert.strictEqual(render.meshScene,scene);
 original.cameraSource.sampleSHA256='b'.repeat(64);
 assert.strictEqual(await ctx.setCameraPreset('original_static_01'),false);
 assert.strictEqual(render.activePreset,old);
 assert.strictEqual(fetches,0);assert.strictEqual(prepares,0);assert.strictEqual(disposes,0);
 original.cameraSource=JSON.parse(JSON.stringify(CAPTURED_FIRST_LEVEL_CAMERA.cameraSource));
 scene.setProjection=p=>projections.push(p);
 for(const [field,value] of [['geometrySHA256','c'.repeat(64)],['geometryFile','foreign.json'],['world','world_02'],['worldBasisVersion','legacy-grid-v1']]){
   const before=mesh[field];mesh[field]=value;
   assert.strictEqual(await ctx.setCameraPreset('mesh_cam'),false);
   assert.strictEqual(render.activePreset,old);mesh[field]=before;
 }
 assert.strictEqual(projections.length,2,'foreign binding must not mutate verified scene');
 render.meshSceneGeneration=0;
 assert.strictEqual(await ctx.setCameraPreset('mesh_cam'),false);
 assert.strictEqual(projections.length,2,'previous generation must not reuse scene');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
