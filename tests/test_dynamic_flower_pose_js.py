import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class DynamicFlowerPoseJsTests(unittest.TestCase):
    def test_independent_axes_graph_skin_and_rejection(self):
        subprocess.run(['node','-e',r'''
const assert=require('assert'),api=require('./web/flower_pose.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const rig={contract:'flower-node-keys-v1',assetId:'fixture',modelSource:'m',modelSHA:'a'.repeat(64),animationSource:'a',animationSHA:'b'.repeat(64),duration:1,nektarNode:0,nodes:[
{name:'nektar',parent:2,bind:I,keys:[[0,0,0,0,0,0,0],[1,0,0,Math.PI/2,0,0,0]]},
{name:'other',parent:-1,bind:I,keys:[[0,0,0,0,99,0,0],[1,0,0,0,99,0,0]]},
{name:'parent',parent:-1,bind:I,keys:[[0,0,0,0,0,2,0],[1,0,0,0,0,2,0]]}]};
const json=JSON.stringify(rig);rig.rigSHA256='c'.repeat(64);
const p={animationScope:'normal-flower-node-keys-v1',animationRig:rig,animationRigJson:json,positions:[1,0,0],normals:[1,0,0],animationSkin:[[[1,0,0],[1,0,0],[[0,1]]]]};
p.animationRigJson=JSON.stringify(Object.fromEntries(Object.entries(JSON.parse(json)).reverse()));
api.validateProp(p);const sampler=api.createSampler(p),pose=sampler.sample(1);
assert(Math.abs(pose.positions[0])<1e-10);assert(Math.abs(pose.positions[1]-3)<1e-10);
assert(Math.abs(pose.normals[0])<1e-10);assert(Math.abs(pose.normals[1]-1)<1e-10);
assert.deepStrictEqual(pose.attachmentPointRaw,[0,2,0]);
assert.deepStrictEqual(sampler.sample(10),pose);p.animationRig.nodes[0].keys[1][3]=0;
assert.deepStrictEqual(sampler.sample(1),pose);
for(const t of [-1,NaN,Infinity,'1'])assert.throws(()=>sampler.sample(t));
assert.throws(()=>api.validateProp(p));
p.animationRig.nodes[0].keys[1][3]=Math.PI/2;
function malformed(edit){const q=JSON.parse(JSON.stringify(p));edit(q);const r={...q.animationRig};delete r.rigSHA256;q.animationRigJson=JSON.stringify(r);assert.throws(()=>api.validateProp(q));}
malformed(q=>q.animationRig.nodes[2].parent=0);
malformed(q=>q.animationRig.nodes[1].name='nektar');
malformed(q=>q.animationRig.nodes[0].keys[1][0]=0);
malformed(q=>q.animationRig.nodes[0].bind[3]=1);
malformed(q=>q.animationSkin[0][0][0]=2);
malformed(q=>q.animationSkin[0][2][0][0]=3);
malformed(q=>q.animationSkin[0][2][0][1]=-1);
malformed(q=>q.animationRig.nektarNode=1);
malformed(q=>q.animationRig.duration=2);
malformed(q=>q.animationSkin[0][1][0]=0);
malformed(q=>q.animationSkin[0][2][0][1]=.5);
const sing=JSON.parse(JSON.stringify(p));sing.animationRig.nodes[2].bind[0]=0;const unsigned={...sing.animationRig};delete unsigned.rigSHA256;sing.animationRigJson=JSON.stringify(unsigned);assert.throws(()=>api.createSampler(sing));
console.log('independent pose tests PASS');
'''],cwd=ROOT,check=True,capture_output=True,text=True)

    def test_real_three_flower_cross_kernel(self):
        from bugbits.assets import data_dir, v3d, pose
        from bugbits.assets.flower_pose import load_normal_rig, worlds_at, attachment_at
        cases=[]
        for asset in ('flower_a','flower_b','cactus_a'):
            rig=load_normal_rig(asset)
            geometry,skin,recs,_=v3d.parse_v3d(data_dir('models','props',asset+'.v3d'))
            prop=dict(animationScope='normal-flower-node-keys-v1',animationRig=rig,
                animationRigJson=json.dumps({k:v for k,v in rig.items() if k!='rigSHA256'},sort_keys=True,separators=(',',':')),
                positions=[x for v in geometry[0] for x in v[0]],normals=[x for v in geometry[0] for x in v[1]],animationSkin=skin)
            bind=pose.worlds_from_records(recs)
            for phase in (0,.37,rig['duration']/2,rig['duration']+1):
                vertices=pose.skin_at(skin,bind,worlds_at(rig,phase))
                cases.append(dict(prop=prop,phase=phase,positions=[x for v in vertices for x in v[0]],
                                  normals=[x for v in vertices for x in v[1]],attachment=list(attachment_at(rig,phase))))
        result=subprocess.run(['node','-e',r'''
const fs=require('fs'),assert=require('assert'),vm=require('vm'),api=require('./web/flower_pose.js');
const context=vm.createContext({});vm.runInContext(fs.readFileSync('web/flower_pose.js','utf8'),context);
assert.strictEqual(typeof context.BugBitsFlowerPose.createSampler,'function');
const close=(a,b)=>{assert.strictEqual(a.length,b.length);a.forEach((v,i)=>assert(Math.abs(v-b[i])<1e-8,`${i}: ${v} != ${b[i]}`));};
for(const item of JSON.parse(fs.readFileSync(0,'utf8'))){const p=api.samplePropPose(item.prop,item.phase);close(p.positions,item.positions);close(p.normals,item.normals);close(p.attachmentPointRaw,item.attachment);}
'''],input=json.dumps(cases),cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
