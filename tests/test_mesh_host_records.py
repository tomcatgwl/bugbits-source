"""Host adapter behavior: world heading, snapshot height and game-time animation."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MeshHostRecords(unittest.TestCase):
    def node(self, js):
        result = subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_body_heading_is_visible_at_rest_and_independent_of_drift(self):
        self.node("""
const assert=require('assert'),fs=require('fs'),vm=require('vm');
const host=fs.readFileSync('web/host.js','utf8');
const start=host.indexOf('function attackElapsedSeconds(');
const stop=host.indexOf('// Mesh snapshot adapter end',start);
const api=require('./web/mesh_scene.js');
const unit={anchor:[0,0,0],scaleFactor:1,rootMatrix:[1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1],clips:{walk:{kind:'animated',frames:[{}],duration:1}}};
const render={meshAssets:{units:{ant:unit}},meshHeading:{},meshLastPos:{}};
const ctx=vm.createContext({render,TICK_HZ:20,unitScale:()=>1,clipFor:()=>'walk'});
vm.runInContext(host.slice(start,stop),ctx);
const frame=(tick,pos,direction)=>({tick,bugs:[{id:7,unit:'ant',pos,direction,dead:false}]});
let record=ctx.meshDrawRecords(frame(1,[0,0,0],[1,0,0]))[0];
assert.strictEqual(record.bodyYawRadians,Math.PI/2,'birth heading without movement');
assert.deepStrictEqual(api.transformNormal([0,0,1],unit,record),[1,0,0]);
record=ctx.meshDrawRecords(frame(2,[1,0,0],[0,0,-1]))[0];
assert.strictEqual(record.bodyYawRadians,Math.PI,'body turns while old velocity drifts east');
assert.deepStrictEqual(api.transformNormal([0,0,1],unit,record),[0,0,-1]);
record=ctx.meshDrawRecords(frame(3,[1,0,0],[0,0,1]))[0];
assert.strictEqual(record.bodyYawRadians,0,'body turns at rest');
assert.deepStrictEqual(api.transformNormal([0,0,1],unit,record),[0,0,1]);
""")

    def test_flower_mesh_adapter_binds_names_and_preserves_snapshot_height(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const instance={name:'Flower',assetId:'flower_a',flowerType:1,positionYup:[1,2,3],
 scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
const render={meshAssets:{props:{flower_a:{}},worlds:{w:{propInstances:[instance]}}}},state={world:'w'};
const ctx=vm.createContext({render,state});const source=fs.readFileSync('web/host.js','utf8');
vm.runInContext(source.slice(source.indexOf('function meshPropRecords('),source.indexOf('// Mesh prop adapter end')),ctx);
const snapshot={flowers:[{name:'Flower',type:1,pos:[11,23,5],nectar:0}]};
const result=ctx.meshPropRecords(snapshot);
assert.deepStrictEqual(Array.from(result[0].positionYup),[11,23,5]);assert.strictEqual(result[0].scaleFactor,2.5);
assert.strictEqual(result[0].assetId,'flower_a');assert.strictEqual(result[0].id,'flower:Flower');
result[0].ownerMatrix[0]=99;assert.strictEqual(instance.ownerMatrix[0],1);
assert.throws(()=>ctx.meshPropRecords({flowers:[{...snapshot.flowers[0],type:2}]}));
assert.throws(()=>ctx.meshPropRecords({flowers:[{...snapshot.flowers[0],name:'missing'}]}));
assert.throws(()=>ctx.meshPropRecords({flowers:[snapshot.flowers[0],snapshot.flowers[0]]}));
render.meshAssets={worlds:{w:{}}};assert.strictEqual(ctx.meshPropRecords(snapshot).length,0);
""")

    def test_first_level_defaults_to_mesh_and_unsupported_world_keeps_overview(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const ctx=vm.createContext({});const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('const NEAR_CAMERA_PRESET'),host.indexOf('// A16')),ctx);
vm.runInContext(host.slice(host.indexOf('function defaultCameraPresetFor('),host.indexOf('// Default camera selection end')),ctx);
for(const world of ['world_01','world_02','world_03']) {
  assert.strictEqual(ctx.defaultCameraPresetFor(world,{mesh_cam:{},wide_cam:{}}),'mesh_cam');
  assert.strictEqual(ctx.defaultCameraPresetFor(world,{wide_cam:{}}),'wide_cam');
  assert.strictEqual(ctx.defaultCameraPresetFor(world,{}),null);
  assert.strictEqual(ctx.defaultCameraPresetFor(world,null),null);
}
assert.strictEqual(ctx.defaultCameraPresetFor('world_04',{mesh_cam:{},wide_cam:{}}),null);
""")

    def test_legacy_mesh_without_view_metadata_keeps_controls_hidden(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const controls={hidden:false};const render={meshScene:{},activePreset:{projection:{}}};
const ctx=vm.createContext({render,$:id=>id==='mesh-controls'?controls:null});
const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function updateMeshControls('),host.indexOf('// Mesh view controls end')),ctx);
ctx.updateMeshControls(null);assert.strictEqual(controls.hidden,true);
""")

    def test_mesh_projection_commit_keeps_overlay_input_and_gpu_in_one_view(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs'),camera=require('./web/camera_projection.js');
const old={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,10,0],size:400,cot:1,aspect:1.6,near:1,far:100};
let submitted=null;const scene={setProjection(p){assert.strictEqual(render.meshProjection,null);submitted=JSON.parse(JSON.stringify(p));}};
const render={activePreset:{projection:old},meshScene:scene,meshProjection:null,meshFollowId:null};
const ctx=vm.createContext({render,BugBitsCameraProjection:camera});const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function activeProjection('),host.indexOf('// One 3D/depth')),ctx);
vm.runInContext(host.slice(host.indexOf('function setMeshProjection('),host.indexOf('// Mesh view controls end')),ctx);
const next={...old,cameraPosition:[2,10,3]};ctx.setMeshProjection(next);next.cameraPosition[0]=999;
assert.deepStrictEqual(Array.from(ctx.activeProjection().cameraPosition),[2,10,3]);
assert.deepStrictEqual(submitted.cameraPosition,[2,10,3]);assert.strictEqual(render.activePreset.projection,old);
const before=JSON.stringify(ctx.activeProjection());render.meshScene.setProjection=()=>{throw Error('context lost');};
assert.throws(()=>ctx.setMeshProjection({...old,cameraPosition:[5,10,6]}));assert.strictEqual(JSON.stringify(ctx.activeProjection()),before);
assert.throws(()=>ctx.setMeshProjection({...old,aspect:2}));assert.strictEqual(JSON.stringify(ctx.activeProjection()),before);
""")

    def test_camera_abort_settles_and_late_scene_is_disposed_once(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const camera=require('./web/camera_projection.js'),crypto=require('crypto').webcrypto;
const raw=new TextEncoder().encode('{}'),sha=require('crypto').createHash('sha256').update(raw).digest('hex');
let finish,started,deadline,disposed=0;
const began=new Promise(r=>started=r),held=new Promise(r=>finish=r);
const previous={projection:{aspect:1.6}};
const render={worldPresets:{mesh_cam:{projection:{kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,2,0],size:400,cot:1,aspect:1.6,near:1,far:100},presentationScope:'engine-mesh-v1',meshContractVersion:'engine-mesh-v1',geometryFile:'scene.json',geometrySHA256:sha}},activePreset:previous,activePresetKey:'wide_cam',presetReqSeq:0,presetController:null};
const ctx=vm.createContext({render,state:{generation:1,world:'w'},BugBitsCameraProjection:camera,
 BugBitsMeshScene:{prepareMeshScene:()=>{started();return held;}},CANVAS_SIZE:640,
 CAMERA_LOAD_TIMEOUT_MS:8000,$:()=>null,AbortController,DOMException,TextDecoder,crypto,
 fetch:async()=>({ok:true,arrayBuffer:async()=>raw.buffer}),setTimeout:f=>{deadline=f;return 1;},clearTimeout:()=>{}});
const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function closePresetBitmap('),host.indexOf('// ── 音频')),ctx);
(async()=>{const request=ctx.setCameraPreset('mesh_cam');await began;deadline();
 const result=await Promise.race([request,new Promise(r=>setTimeout(()=>r('hung'),100))]);
 assert.strictEqual(result,false,'cancel must settle even when dependency ignores signal');
 assert.strictEqual(render.presetPending,null);assert.strictEqual(render.activePreset,previous);
 finish({dispose:()=>disposed++});await new Promise(setImmediate);assert.strictEqual(disposed,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_context_loss_restores_canvas_clip_before_overview_fallback(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
let saved=0,terrainDrawClip=null;
const context={setTransform(){},clearRect(){},save(){saved++;},beginPath(){},rect(){},clip(){},restore(){saved--;},drawImage(){terrainDrawClip=saved;}};
const canvas={width:640,height:640,getContext:()=>context};
const render={meshScene:{renderFrame(){throw Error('context lost');}},activePreset:{projection:{aspect:1.6}},presetTerrain:null,terrain:{width:640},projection:{aspect:1},fallbackHits:{},presetReqSeq:1};
const ctx=vm.createContext({render,state:{lastSnapshot:null,tick:0,generation:1},CANVAS_SIZE:640,
 window:{devicePixelRatio:1},$:(id)=>id==='scene'?canvas:null,perf:{_lastFrame:0,frameTimes:[],push(){}},
 activeProjection:()=>render.activePreset.projection,frameMark:{seq:0},updateCameraControl(){},requestAnimationFrame(){},
 commitCameraView(){render.meshScene=null;render.activePreset=null;}});
const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function updateNativeCamera('),host.indexOf('function updateMeshFollow(')),ctx);
vm.runInContext(host.slice(host.indexOf('function renderFrame('),host.indexOf('async function init(')),ctx);
ctx.renderFrame(50);assert.strictEqual(saved,0,'Canvas save stack must balance');
assert.strictEqual(terrainDrawClip,0,'overview fallback must use whole canvas');
// A legal scene can render terrain while the first worker snapshot is pending.
render.activePreset={projection:{aspect:1.6}};
render.meshScene={renderFrame({snapshot,drawRecords}){
 assert.strictEqual(snapshot.tick,0);assert.strictEqual(drawRecords.length,0);
 return {canvas:{},draws:[]};
}};
ctx.renderFrame(60);assert(render.meshScene,'empty first snapshot must retain mesh');
assert.strictEqual(saved,0);
""")

    def test_world_heading_height_pause_and_scale_once(self):
        js = """
const assert = require('assert'), fs = require('fs'), vm = require('vm');
const host = fs.readFileSync('web/host.js', 'utf8');
const start = host.indexOf('function attackElapsedSeconds(');
assert(start >= 0, 'mesh snapshot adapter missing');
const stop = host.indexOf('// Mesh snapshot adapter end', start);
const scene = {units:{ant:{clips:{walk:{kind:'animated',frames:[{},{}],duration:1}}}}};
const render={meshAssets:scene,meshHeading:{},meshLastPos:{}};
const ctx=vm.createContext({render,TICK_HZ:20,unitScale:()=>1.5,clipFor:()=> 'walk'});
vm.runInContext(host.slice(start, stop),ctx);
const snap=(tick,pos)=>({tick,bugs:[{id:7,unit:'ant',pos,dead:false}]});
let records=ctx.meshDrawRecords(snap(0,[2,3,4]));
assert.deepStrictEqual(Array.from(records[0].positionYup),[2,3,4]);
assert.strictEqual(records[0].scaleFactor,1.5);
records=ctx.meshDrawRecords(snap(10,[4,3,4]));
assert(Math.abs(records[0].headingRadians-Math.PI/2)<1e-12);
assert.strictEqual(records[0].frame,1);
const frozen=JSON.stringify(records);
render.activePreset={camera:{yawDeg:90}};
assert.strictEqual(JSON.stringify(ctx.meshDrawRecords(snap(10,[4,3,4]))),frozen);
records=ctx.meshDrawRecords(snap(20,[4,3,6]));
assert.strictEqual(records[0].headingRadians,0);
assert.strictEqual(records[0].frame,0);
assert.strictEqual(ctx.meshDrawRecords({tick:20,bugs:[{id:8,unit:'ant',pos:[0,0,0],dead:true}]}).length,0);
"""
        result = subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
