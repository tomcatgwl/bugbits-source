"""Actual mesh preparation: level closure, bounded downloads and failure cleanup."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SETUP = r"""
const assert=require('assert'),api=require('./web/mesh_scene.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const mesh={positions:[0,0,2,1,0,2,0,1,2],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:'terrain'}]};
const clips={idle:{kind:'static',duration:1,loop:true,sampleTimes:[0],frames:[{positions:mesh.positions,normals:mesh.normals}]}};
for(const name of ['walk','normal_attack','hurt','special_attack','special_move'])clips[name]={kind:'missing',fallbackClip:'idle'};
const unit={...mesh,anchor:[0,0,0],rootMatrix:I,scaleFactor:1,clips,rootPolicy:'engineering-fixed-S-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-bind-ground-pivot-v1',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false};
const bytes=new Uint8Array([1,2,3]);
const hash=require('crypto').createHash('sha256').update(bytes).digest('hex');
const texture=id=>({width:1,height:1,file:'assets/'+id+'.png',sha256:hash,size:3});
const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{ant:{...unit,groups:[{indices:[0,1,2],texture:'ant'}]},unused:{...unit,groups:[{indices:[0,1,2],texture:'unused'}]}},textures:{terrain:texture('terrain'),ant:texture('ant'),unused:texture('unused')},worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh]},other:{basisVersion:'loaded-yup-v1',meshes:[{...mesh,groups:[{indices:[0,1,2],texture:'unused'}]}]}}};
let allocations=0,deletions=0,closed=0;
const allocate=()=>{allocations++;return {};},noop=()=>{};
const gl=new Proxy({getShaderParameter:()=>true,getProgramParameter:()=>true,createShader:allocate,createProgram:allocate,createTexture:allocate,createBuffer:allocate,createVertexArray:allocate,deleteShader:()=>deletions++,deleteProgram:()=>deletions++,deleteTexture:()=>deletions++,deleteBuffer:()=>deletions++,deleteVertexArray:()=>deletions++},{get:(o,k)=>k in o?o[k]:/^[A-Z_]+$/.test(k)?1:noop});
const canvas={width:640,height:640,getContext:()=>gl,addEventListener:noop,removeEventListener:noop};
const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:1,far:100};
globalThis.createImageBitmap=async()=>({width:1,height:1,close(){closed++;}});
const options={assets,projection,worldId:'w',canvas,baseURL:'http://fixture/',unitIds:['ant'],requiredUnitIds:['ant']};
"""

class MeshResourceLoading(unittest.TestCase):
    def node(self, body):
        result = subprocess.run(['node', '-e', SETUP + body], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_host_uses_future_level_dependencies_and_legacy_full_fallback(self):
        js = r"""
const assert=require('assert'),vm=require('vm'),fs=require('fs');
const host=fs.readFileSync('web/host.js','utf8');let captured;
const state={world:'w',levelId:'first',units:{ant:{},future:{},unrelated:{}},manifest:{levels:[{id:'first',deps:{units:['ant','future']}}]}};
const ctx=vm.createContext({state,DOMException,BugBitsMeshScene:{prepareMeshScene:async(options)=>{captured=options;return {dispose(){}};}}});
vm.runInContext(host.slice(host.indexOf('function loadMeshScene('),host.indexOf('async function setCameraPreset(')),ctx);
(async()=>{
 await ctx.loadMeshScene({}, {projection:{}},new AbortController().signal);
 assert.deepEqual(Array.from(captured.unitIds),['ant','future']);assert.deepEqual(Array.from(captured.requiredUnitIds),['ant','future']);
 delete state.manifest.levels[0].deps;
 await ctx.loadMeshScene({}, {projection:{}},new AbortController().signal);
 assert.equal(captured.unitIds,null);assert.deepEqual(Array.from(captured.requiredUnitIds),['ant','future','unrelated']);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_closure_concurrency_and_legacy_fallback(self):
        self.node(r"""
(async()=>{
 let active=0,max=0,paths=[];
 globalThis.fetch=async(url)=>{paths.push(new URL(url).pathname);active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,20));active--;return {ok:true,arrayBuffer:async()=>bytes.buffer};};
 const scene=await api.prepareMeshScene(options);scene.dispose();
 assert.deepEqual(paths.sort(),['/assets/ant.png','/assets/terrain.png']);assert.equal(max,2,'independent needed resources overlap');assert.equal(allocations,deletions);assert.equal(closed,2);
 assert.equal(Object.keys(assets.units).length,2,'caller metadata is unchanged');
 paths=[];const legacy=await api.prepareMeshScene({...options,unitIds:null});legacy.dispose();assert(paths.includes('/assets/unused.png'));
 assert.equal(allocations,deletions);
 for(let i=0;i<8;i++){assets.textures['extra'+i]=texture('extra'+i);mesh.groups.push({indices:[0,1,2],texture:'extra'+i});}
 active=0;max=0;const bounded=await api.prepareMeshScene(options);bounded.dispose();assert.equal(max,4,'network pool capped at four');
 await assert.rejects(api.prepareMeshScene({...options,unitIds:['absent']}),/unit/);
 await assert.rejects(api.prepareMeshScene({...options,unitIds:[]}),/unit/);
 await assert.rejects(api.prepareMeshScene({...options,requiredUnitIds:['unused']}),/unit/);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_abort_and_failed_download_drain_without_leaking_gpu(self):
        self.node(r"""
(async()=>{
 const controller=new AbortController();let active=0,started;
 const began=new Promise(r=>started=r);
 globalThis.fetch=(url,{signal})=>new Promise((resolve,reject)=>{active++;started();signal.addEventListener('abort',()=>{active--;reject(new DOMException('aborted','AbortError'));},{once:true});});
 const pending=api.prepareMeshScene({...options,signal:controller.signal});await began;controller.abort();await assert.rejects(pending,/aborted/i);assert.equal(active,0);assert.equal(allocations,deletions);
 globalThis.fetch=(url,{signal})=>new Promise((resolve,reject)=>{active++;const abort=()=>{clearTimeout(timer);active--;reject(new DOMException('aborted','AbortError'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);active--;resolve({ok:false,status:503});},5);signal.addEventListener('abort',abort,{once:true});});
 await assert.rejects(api.prepareMeshScene(options),/503/);assert.equal(active,0);assert.equal(allocations,deletions);
 globalThis.fetch=async()=>({ok:true,arrayBuffer:async()=>new Uint8Array([3,2,1]).buffer});
 await assert.rejects(api.prepareMeshScene(options),/SHA/);assert.equal(allocations,deletions);assert.equal(closed,0);
 let n=0;
 globalThis.fetch=()=>++n===1?Promise.resolve({ok:false,status:502}):new Promise(()=>{});
 await assert.rejects(api.prepareMeshScene(options),/502/);assert.equal(allocations,deletions);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
