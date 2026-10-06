"""Same-world level selectors reach the actual host adapter and mesh validator."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LevelFlowerVariantHostTests(unittest.TestCase):
    def node(self, body):
        result = subprocess.run(['node', '-e', body], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bad_level_selector_fails_before_mesh_preparation(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const contract='level-flower-variants-v1';let prepared=0;
const state={world:'w',levelId:'normal',manifest:{levels:[{id:'normal',world:'w',type:'gather',deps:{}}]}};
const assets={propVariantContract:contract,worlds:{w:{propVariants:{normal:[],rescue:[]}}}};
const ctx=vm.createContext({state,DOMException,BugBitsMeshScene:{prepareMeshScene:async()=>{prepared++;return {dispose(){}};}}});
const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function meshPropRecords('),host.indexOf('// Mesh prop adapter end')),ctx);
vm.runInContext(host.slice(host.indexOf('function loadMeshScene('),host.indexOf('async function setCameraPreset(')),ctx);
(async()=>{
 await assert.rejects(async()=>ctx.loadMeshScene(assets,{projection:{}},new AbortController().signal));
 assert.strictEqual(prepared,0,'bad level selector must not prepare or publish any GL scene');
 state.manifest.levels[0].deps.meshProps={contract,world:'w',variant:'normal'};
 await ctx.loadMeshScene(assets,{projection:{}},new AbortController().signal);assert.strictEqual(prepared,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_same_world_level_roundtrip_and_no_new_contract_fallback(self):
        self.node("""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const contract='level-flower-variants-v1';
const instance=(rescue)=>({name:'Flower2',assetId:rescue?'flower_a_swap':'flower_a',
 flowerType:1,rescue,scaleFactor:rescue?4:2.5,positionYup:[-83.6097259521,2.3150925636,-50.7187004089],
 ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'});
const level=(id,type,variant)=>({id,type,world:'world_01',deps:{meshProps:{contract,world:'world_01',variant}}});
const state={world:'world_01',levelId:'level_01',manifest:{levels:[level('level_01','gather','normal'),level('rescue_01','rescue','rescue')]}};
const render={meshAssets:{propVariantContract:contract,props:{flower_a:{},flower_a_swap:{}},
 worlds:{world_01:{propVariants:{normal:[instance(false)],rescue:[instance(true)]}}}}};
const ctx=vm.createContext({render,state});const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function meshPropRecords('),host.indexOf('// Mesh prop adapter end')),ctx);
const snapshot={flowers:[{name:'Flower2',type:1,pos:[-83.6097259521,2.3150925636,-50.7187004089],nectar:0}]};
const identity=JSON.stringify(snapshot);
for(const [id,asset] of [['level_01','flower_a'],['rescue_01','flower_a_swap'],['level_01','flower_a']]){
 state.levelId=id;const records=ctx.meshPropRecords(snapshot);
 assert.strictEqual(records.length,1);assert.strictEqual(records[0].assetId,asset);
 assert.strictEqual(records[0].scaleFactor,id==='rescue_01'?4:2.5);
 assert.deepStrictEqual(Array.from(records[0].positionYup),snapshot.flowers[0].pos);
 records[0].ownerMatrix[0]=99;
 assert.strictEqual(render.meshAssets.worlds.world_01.propVariants.normal[0].ownerMatrix[0],1);
 assert.strictEqual(JSON.stringify(snapshot),identity);
}
const selector=state.manifest.levels[0].deps.meshProps;
for(const bad of [undefined,{...selector,world:'other'},{...selector,variant:'rescue'},
 {...selector,variant:'absent'},{...selector,contract:'wrong'}]){
 state.manifest.levels[0].deps.meshProps=bad;assert.throws(()=>ctx.meshPropRecords(snapshot));
}
state.manifest.levels[0].deps.meshProps=selector;
const variants=render.meshAssets.worlds.world_01.propVariants;
render.meshAssets.worlds.world_01.propInstances=[instance(false)];
delete variants.normal;assert.throws(()=>ctx.meshPropRecords(snapshot));
variants.normal=[instance(false)];assert.throws(()=>ctx.meshPropRecords(snapshot),'new packet must not hide a legacy default');
delete render.meshAssets.worlds.world_01.propInstances;
delete render.meshAssets.propVariantContract;assert.throws(()=>ctx.meshPropRecords(snapshot),'variants must not downgrade to legacy');
""")

    def test_mesh_validator_rejects_cross_variant_assets_and_duplicate_instances(self):
        self.node("""
const assert=require('assert'),api=require('./web/mesh_scene.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const mesh={positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null}]};
const prop={...mesh,frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,
 rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
const instance=rescue=>({name:'Flower',flowerType:1,rescue,assetId:rescue?'flower_a_swap':'flower_a',
 scaleFactor:rescue?4:2.5,positionYup:[0,0,0],ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'});
const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',propVariantContract:'level-flower-variants-v1',
 units:{},textures:{},props:{flower_a:prop,flower_a_swap:prop},
 worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh],propVariants:{normal:[instance(false)],rescue:[instance(true)]}}}};
api.validateAssets(assets);
for(const mutate of [a=>a.propVariantContract='wrong',a=>delete a.propVariantContract,
 a=>a.worlds.w.propInstances=[],a=>a.worlds.w.propVariants={},
 a=>a.worlds.w.propVariants.other=[],a=>a.worlds.w.propVariants.normal[0].assetId='flower_a_swap',
 a=>a.worlds.w.propVariants.rescue[0].rescue=false,a=>a.worlds.w.propVariants.normal[0].scaleFactor=1,
 a=>a.worlds.w.propVariants.rescue[0].scaleFactor=2.5,
 a=>{a.props.flower_b_swap=a.props.flower_a_swap;
   Object.assign(a.worlds.w.propVariants.rescue[0],{flowerType:2,assetId:'flower_b_swap',scaleFactor:2.5});},
 a=>a.worlds.w.propVariants.rescue.push({...a.worlds.w.propVariants.rescue[0]}),
 a=>delete a.props.flower_a_swap,a=>a.worlds.w.propVariants.normal[0].positionYup[0]=NaN]){
 const bad=structuredClone(assets);mutate(bad);assert.throws(()=>api.validateAssets(bad));
}
""")
