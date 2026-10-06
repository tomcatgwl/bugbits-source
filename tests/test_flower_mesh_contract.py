"""Public props coordinate and packet contracts; real GPU pixels are root's queue."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FlowerMeshContractTests(unittest.TestCase):
    def node(self, body):
        result = subprocess.run(['node', '-e', "const assert=require('assert');const api=require(process.argv[1]);" + body,
                                 str(ROOT / 'web/mesh_scene.js')], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_texture_flip_rejects_partial_and_false_reference_scope(self):
        self.node("""
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const mesh={positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null}]};
const prop={...mesh,assetId:'flower_a',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
const packet=p=>({schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{},worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh]}},textures:{},props:{flower_a:p}});
api.validateAssets(packet(prop));
api.validateAssets(packet({...prop,textureVFlip:false,textureUvScope:'observed-normal-flower-a-v1'}));
for(const change of [{textureVFlip:false},{textureUvScope:'engineering-explicit-v1'},
 {textureVFlip:0,textureUvScope:'engineering-explicit-v1'},
 {textureVFlip:'false',textureUvScope:'engineering-explicit-v1'},
 {textureVFlip:null,textureUvScope:'engineering-explicit-v1'},
 {textureVFlip:true,textureUvScope:'observed-normal-flower-a-v1'},
 {assetId:'flower_a_swap',textureVFlip:false,textureUvScope:'observed-normal-flower-a-v1'},
 {textureVFlip:false,textureUvScope:'unverified-original'}]){
 assert.throws(()=>api.validateAssets(packet({...prop,...change})),/texture UV/);
}
const bad=packet(prop);bad.worlds.w.meshes=[{...mesh,assetId:'flower_a',textureVFlip:false,textureUvScope:'observed-normal-flower-a-v1'}];
assert.throws(()=>api.validateAssets(bad),/texture UV/);
for(const value of [false,true])api.validateAssets(packet({...prop,textureVFlip:value,textureUvScope:'engineering-explicit-v1'}));
""")

    def test_prop_normals_reject_nonuniform_and_shear_matrices(self):
        self.node("""
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const prop={frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,
rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
const draw={positionYup:[10,3,-4],scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
// For owner diag(2,1,1), tangent (1,1,0) and normal (1,-1,0)
// cease orthogonality under ordinary vector multiplication: dot=3.
const scale=[2,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const shear=[1,1,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
for(const field of ['rootMatrix','ownerMatrix','parentMatrix'])for(const m of [scale,shear]){
const p=field==='rootMatrix'?{...prop,rootMatrix:m}:prop;
const d=field==='rootMatrix'?draw:{...draw,[field]:m};
assert.throws(()=>api.transformPropNormal([1,-1,0],p,d),/rigid/);
assert.throws(()=>api.transformPropVertex([1,1,0],p,d),/rigid/);
}
""")

    def test_original_loaded_bind_root_policy_and_independent_vertex_normal(self):
        self.node("""
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const phi=Math.fround(-Math.PI/2),c=Math.cos(phi),s=Math.sin(phi);
const S=[1,0,0,0,0,c,s,0,0,-s,c,0,0,0,0,1];
const prop={frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:S,
rootPolicy:'original-load-bind-S-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
const draw={positionYup:[10,3,-4],scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
const p=api.transformPropVertex([11,23,5],prop,draw);
assert(p.every((v,i)=>Math.abs(v-[-2.5,60.5,23.5][i])<3e-6));
const n=api.transformPropNormal([0,1,0],prop,draw);
assert(n.every((v,i)=>Math.abs(v-[0,1,0][i])<1e-7));
for(const root of [I,[1,0,0,0,0,c,-s,0,0,s,c,0,0,0,0,1]])
assert.throws(()=>api.transformPropVertex([11,23,5],{...prop,rootMatrix:root},draw),/loaded root/);
""")

    def test_prop_keeps_raw_origin_and_applies_scale_basis_translation_once(self):
        self.node("""
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const prop={frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,
 rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
const draw={assetId:'flower_a',positionYup:[10,3,-4],scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,
 transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
assert.deepStrictEqual(api.transformPropVertex([11,23,5],prop,draw),[-47.5,-9.5,23.5]);
assert.deepStrictEqual(api.transformPropVertex([0,0,0],prop,draw),[10,3,-4]);
assert.deepStrictEqual(api.transformPropNormal([0,1,0],prop,draw),[-1,0,0]);
const rootZ=[0,1,0,0,-1,0,0,0,0,0,1,0,0,0,0,1];
const ownerX=[1,0,0,0,0,0,1,0,0,-1,0,0,0,0,0,1];
const parent=[...I];parent[12]=5;parent[13]=7;parent[14]=9;
const rotated={...draw,ownerMatrix:ownerX,parentMatrix:parent};
assert.deepStrictEqual(api.transformPropVertex([11,23,5],{...prop,rootMatrix:rootZ},rotated),[-12.5,67.5,-7.5]);
assert.deepStrictEqual(api.transformPropNormal([0,1,0],{...prop,rootMatrix:rootZ},rotated),[0,1,0]);
for(const bad of [{...draw,scaleFactor:NaN},{...draw,scaleApplied:true},{...draw,transformScope:'original'}])
 assert.throws(()=>api.transformPropVertex([11,23,5],prop,bad));
assert.throws(()=>api.transformPropVertex([11,23,5],{...prop,frameBasis:'loaded-yup-v1'},draw));
""")

    def test_props_validate_and_invalid_records_do_not_clear_published_frame(self):
        self.node("""
(async()=>{
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const mesh={positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null}]};
const prop={...mesh,frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,
rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{},worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh]}},textures:{},props:{flower_a:prop}};
api.validateAssets(assets);
for(const key of ['frameBasis','rootApplied','scaleApplied','rootPolicy','coordinatePolicy','anchorPolicy']){
const bad=structuredClone(assets);bad.props.flower_a[key]='wrong';assert.throws(()=>api.validateAssets(bad));}
const bad=structuredClone(assets);bad.props.flower_a.groups[0].texture='absent';assert.throws(()=>api.validateAssets(bad),/texture/);
let clears=0,submissions=0;const noop=()=>{};
const gl=new Proxy({NO_ERROR:0,isContextLost:()=>false,getError:()=>0,getShaderParameter:()=>true,getProgramParameter:()=>true,
 createShader:()=>({}),createProgram:()=>({}),createTexture:()=>({}),createBuffer:()=>({}),createVertexArray:()=>({}),getUniformLocation:()=>({}),
 clear:()=>{clears++;},drawElements:()=>{submissions++;}}, {get:(o,k)=>k in o?o[k]:(/^[A-Z_]+$/.test(k)?1:noop)});
const canvas={width:640,height:640,getContext:()=>gl,addEventListener:noop,removeEventListener:noop};
const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:1,far:100};
const scene=await api.prepareMeshScene({assets,projection,worldId:'w',canvas});
const record={id:7,assetId:'flower_a',positionYup:[10,3,-4],scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'};
const frame=scene.renderFrame({snapshot:{tick:1},propRecords:[record]});assert.strictEqual(frame.propDraws.length,1);assert.strictEqual(submissions,2);
const prior=clears;
for(const invalid of [{...record,assetId:'missing'},{...record,scaleApplied:true},{...record,scaleFactor:'2.5'},{...record,positionYup:[0,NaN,0]},{...record,transformPolicy:'unit'}]){
assert.throws(()=>scene.renderFrame({snapshot:{tick:2},propRecords:[invalid]}));assert.strictEqual(clears,prior);}
scene.dispose();
})().catch(e=>{console.error(e);process.exitCode=1});
""")
