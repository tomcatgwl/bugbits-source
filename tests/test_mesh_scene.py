"""Production mesh Interface literals; GPU pixels are checked by the browser fixture."""
from pathlib import Path
import subprocess
import unittest
ROOT = Path(__file__).resolve().parents[1]
class MeshSceneTests(unittest.TestCase):
    def node(self, body):
        result = subprocess.run(['node', '-e', "const assert=require('assert');const api=require(process.argv[1]);"+body, str(ROOT/'web/mesh_scene.js')], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
    def test_root_anchor_scale_heading_and_height_have_independent_literals(self):
        self.node("""
const unit={anchor:[3,7,2],scaleFactor:1.5,rootMatrix:[1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1]};
const draw={positionYup:[10,3,-4],headingRadians:Math.PI/2,sourceScope:'engineering',posePolicy:'engine-pose-v1'};
const p=api.transformVertex([11,23,5],unit,draw);
for(let i=0;i<3;i++)assert(Math.abs(p[i]-[22,27,.5][i])<1e-10);
const override=api.transformVertex([11,23,5],unit,{...draw,scaleFactor:1});
for(let i=0;i<3;i++)assert(Math.abs(override[i]-[18,19,-1][i])<1e-10);
assert.throws(()=>api.transformVertex([11,23,5],unit,{...draw,sourceScope:'original'}));
assert.throws(()=>api.transformVertex([NaN,23,5],unit,draw));
""")
    def test_mesh_domain_rejects_missing_texture_and_out_of_range_geometry(self):
        self.node("""
const mesh={positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:'named'}]};
const scene={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{},worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh]}},textures:{}};
assert.throws(()=>api.validateAssets(scene),/texture/);
scene.textures.named={width:1,height:1,pixels:[255,0,0,255]};
api.validateAssets(scene);
mesh.groups[0].indices[2]=3;assert.throws(()=>api.validateAssets(scene),/index/);
mesh.groups[0].indices[2]=2;mesh.uvs[0]=NaN;assert.throws(()=>api.validateAssets(scene),/UV/);
""")
    def test_mixed_world_packet_selects_only_loaded_world_and_rejects_bad_basis(self):
        self.node("""
const mesh={positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null}]};
const scene={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{},worlds:{loaded:{basisVersion:'loaded-yup-v1',meshes:[mesh]},historical:{basisVersion:'legacy-grid-v1',meshes:[mesh]}},textures:{}};
api.validateAssets(scene);
(async()=>{await assert.rejects(api.prepareMeshScene({assets:scene,projection:{kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:1,far:100},worldId:'historical'}),/loaded/);scene.worlds.historical.basisVersion='bad';assert.throws(()=>api.validateAssets(scene),/world/);})().catch(e=>{console.error(e);process.exitCode=1});
""")
    def test_binary_frame_decode_preserves_float_values_and_rejects_invalid_sources(self):
        self.node("""
(async()=>{
const bytes=new ArrayBuffer(72),v=new DataView(bytes);for(let i=0;i<18;i++)v.setFloat32(i*4,[1.25,-2.5,3.75][i%3],true);
const hash=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
const frames=[{positions:{offset:0,count:9},normals:{offset:36,count:9}}];
const unit={positions:Array(9).fill(0),frameBuffer:{format:'f32le-pose-v1',file:'assets/geometry/ant-frames.bin',sha256:hash,byteLength:72},clips:{idle:{kind:'static',duration:1,loop:true,sampleTimes:[0],frames}}};
const decoded=await api.decodeUnitFrameBuffer(unit,bytes);
assert(decoded.clips.idle.frames[0].positions instanceof Float32Array);
assert.deepStrictEqual(Array.from(decoded.clips.idle.frames[0].positions.slice(0,3)),[1.25,-2.5,3.75]);
assert.strictEqual(unit.clips.idle.frames[0].positions.offset,0);
await assert.rejects(api.decodeUnitFrameBuffer({...unit,frameBuffer:{...unit.frameBuffer,sha256:'0'.repeat(64)}},bytes),/SHA/);
await assert.rejects(api.decodeUnitFrameBuffer(unit,bytes.slice(0,68)),/length/);
for(const positions of [{offset:1,count:9},{offset:64,count:9},{offset:0,count:8},{offset:NaN,count:9},Array(9).fill(0)]){
 const bad={...unit,clips:{idle:{...unit.clips.idle,frames:[{positions,normals:{offset:36,count:9}}]}}};await assert.rejects(api.decodeUnitFrameBuffer(bad,bytes),/frame/);
}
await assert.rejects(api.decodeUnitFrameBuffer({...unit,clips:{idle:{...unit.clips.idle,frames:[{positions:{offset:36,count:9},normals:{offset:0,count:9}}]}}},bytes),/frame/);
v.setFloat32(0,NaN,true);unit.frameBuffer.sha256=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');await assert.rejects(api.decodeUnitFrameBuffer(unit,bytes),/finite/);
})().catch(e=>{console.error(e);process.exitCode=1});
""")
