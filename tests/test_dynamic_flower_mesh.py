"""Public scene submission contract (instrumented GL, not actual GPU pixels)."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class DynamicFlowerMeshTests(unittest.TestCase):
    def test_same_phase_position_normal_reuse_and_preclear_validation(self):
        body=r'''
const assert=require('assert'),api=require('./web/mesh_scene.js'),crypto=require('crypto');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const mesh={positions:[1,0,0,0,1,0,0,0,1],normals:[1,0,0,1,0,0,1,0,0],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null}]};
const rig={contract:'flower-node-keys-v1',assetId:'flower_a',modelSource:'models/props/flower_a.v3d',modelSHA:'a'.repeat(64),animationSource:'models/props/flower_a.van',animationSHA:'b'.repeat(64),duration:1,nektarNode:0,nodes:[{name:'nektar',parent:-1,bind:I,keys:[[0,0,0,0,0,0,0],[1,0,0,Math.PI/2,0,0,0]]}]};
const text=JSON.stringify(rig);rig.rigSHA256=crypto.createHash('sha256').update(text).digest('hex');
const prop={...mesh,assetId:'flower_a',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1',nodeCount:1,skinVertices:3,animationScope:'normal-flower-node-keys-v1',animationRig:rig,animationRigJson:text,animationSkin:mesh.positions.reduce((a,v,i)=>{if(i%3===0)a.push([mesh.positions.slice(i,i+3),mesh.normals.slice(i,i+3),[[0,1]]]);return a;},[]),attachments:{nektar:{name:'nektar',node:0,parentChain:[0],positionRaw:[0,0,0],poseScope:'bind-model-attachment-v1'}}};
const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{},textures:{},props:{flower_a:prop},worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh]}}};
let clears=0,vaos=0;const buffers=new Map(),bound={},attributes=new Map();const noop=()=>{};
const gl=new Proxy({NO_ERROR:0,ARRAY_BUFFER:11,ELEMENT_ARRAY_BUFFER:12,isContextLost:()=>false,getError:()=>0,getShaderParameter:()=>true,getProgramParameter:()=>true,createShader:()=>({}),createProgram:()=>({}),createTexture:()=>({}),createBuffer:()=>({}),createVertexArray:()=>{vaos++;return {};},getUniformLocation:()=>({}),bindBuffer:(target,b)=>{bound[target]=b;},bufferData:(target,data)=>{buffers.set(bound[target],Array.from(data));},vertexAttribPointer:(i)=>attributes.set(i,bound[11]),clear:()=>{clears++;}}, {get:(o,k)=>k in o?o[k]:/^[A-Z_]+$/.test(k)?1:noop});
const canvas={width:640,height:640,getContext:()=>gl,addEventListener:noop,removeEventListener:noop};
const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:1,far:100};
const record={id:'flower:f',assetId:'flower_a',positionYup:[0,0,20],scaleFactor:1,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1',animationPhase:0};
(async()=>{
 const scene=await api.prepareMeshScene({assets,projection,worldId:'w',canvas});
 const a=scene.renderFrame({snapshot:{tick:4},propRecords:[record]});
 assert.strictEqual(a.propDraws[0].animationPhase,0);
 const count=vaos;
 const b=scene.renderFrame({snapshot:{tick:4},propRecords:[{...record,animationPhase:1}]});
 assert.strictEqual(b.propDraws[0].animationPhase,1);assert.strictEqual(vaos,count);
 const pos=buffers.get(attributes.get(0)),normal=buffers.get(attributes.get(2));
 assert(Math.abs(pos[0])<1e-6&&Math.abs(pos[1]-1)<1e-6);assert(Math.abs(normal[0])<1e-6&&Math.abs(normal[1]-1)<1e-6);
 for(let i=0;i<30;i++)scene.renderFrame({snapshot:{tick:4},propRecords:[{...record,animationPhase:i/30}]});
 assert.strictEqual(vaos,count);
 const before=clears;for(const phase of [undefined,-1,NaN,'1'])assert.throws(()=>scene.renderFrame({snapshot:{tick:4},propRecords:[{...record,animationPhase:phase}]}));assert.strictEqual(clears,before);
 assert.throws(()=>scene.renderFrame({snapshot:{tick:4},propRecords:[record,record]}));assert.strictEqual(clears,before);
 scene.dispose();
 const bad=structuredClone(assets);bad.props.flower_a.animationRig.rigSHA256='c'.repeat(64);
 await assert.rejects(()=>api.prepareMeshScene({assets:bad,projection,worldId:'w',canvas}),/SHA/);
 // Hold digest resolution while an external owner changes both signed values.
 const mutable=structuredClone(assets),originalSHA=mutable.props.flower_a.animationRig.rigSHA256;
 const nativeCrypto=globalThis.crypto;let release,entered=false;
 Object.defineProperty(globalThis,'crypto',{configurable:true,value:{subtle:{digest(algorithm,bytes){
   entered=true;const frozenBytes=new Uint8Array(bytes);
   return new Promise(resolve=>{release=()=>resolve(crypto.webcrypto.subtle.digest(algorithm,frozenBytes));});
 }}}});
 let isolated;
 try{
   const preparing=api.prepareMeshScene({assets:mutable,projection,worldId:'w',canvas});
   assert(entered,'digest must be pending');
   mutable.props.flower_a.animationRig.nodes[0].keys[1][3]=0;
   const unsigned={...mutable.props.flower_a.animationRig};delete unsigned.rigSHA256;
   mutable.props.flower_a.animationRigJson=JSON.stringify(unsigned);
   assert.strictEqual(mutable.props.flower_a.animationRig.rigSHA256,originalSHA);
   release();isolated=await preparing;
   isolated.renderFrame({snapshot:{tick:5},propRecords:[{...record,animationPhase:1}]});
   const signedPosition=buffers.get(attributes.get(0));
   assert(Math.abs(signedPosition[0])<1e-6&&Math.abs(signedPosition[1]-1)<1e-6,
          'prepared pose must match the pre-await signed configuration');
 }finally{isolated?.dispose();Object.defineProperty(globalThis,'crypto',{configurable:true,value:nativeCrypto});}

})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run(['node','-e',body],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
