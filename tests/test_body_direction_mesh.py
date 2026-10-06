"""Public body direction reaches actual host and mesh instance consumers."""
import json
from pathlib import Path
import subprocess
import unittest

from bugbits import web_data
from bugbits.web_bridge import WebBridge
from test_nongather_motion import ordinary_game

ROOT=Path(__file__).resolve().parents[1]


class BodyDirectionMesh(unittest.TestCase):
    def node(self,body,payload=None):
        result=subprocess.run(['node','-e',body],cwd=ROOT,input=json.dumps(payload),
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_public_slope_body_forward_reaches_host_and_mesh(self):
        snapshots=[]
        for height in (500.,-500.):
            base=ordinary_game(direction_factor=20,target=(1000.,height,0.))
            bridge=WebBridge()
            opened=bridge.init('pitch-public',2026,web_data.level_to_dict(base.level),
                web_data.world_to_dict(base.world),
                {'littlebeetle':web_data.unit_to_dict(base.units['littlebeetle'])},
                {'buyable':['littlebeetle']})
            self.assertTrue(bridge.submit(dict(type='buy',commandId='pitch-buy',
                sessionId=opened['sessionId'],unit='littlebeetle',lane=0))['queued'])
            self.assertEqual(bridge.advance(4)['advanced'],4)
            snapshots.append(bridge.snapshot())
        self.assertEqual(snapshots[0]['bugs'][0]['pos'],snapshots[1]['bugs'][0]['pos'])
        self.assertGreater(snapshots[0]['bugs'][0]['direction'][1],0)
        self.assertLess(snapshots[1]['bugs'][0]['direction'][1],0)
        self.node(r'''
const fs=require('fs'),assert=require('assert'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),api=require('./web/mesh_scene.js');
const source=fs.readFileSync('web/host.js','utf8'),start=source.indexOf('function attackElapsedSeconds('),stop=source.indexOf('// Mesh snapshot adapter end',start);
const phi=Math.fround(-Math.PI/2),c=Math.cos(phi),s=Math.sin(phi);
const unit={anchor:[3,7,2],scaleFactor:1.2,rootMatrix:[1,0,0,0,0,c,s,0,0,-s,c,0,0,0,0,1],
 clips:{walk:{kind:'animated',frames:[{},{}],duration:input[0].bugs[0].walkAnimation.duration}}};
const render={meshAssets:{units:{littlebeetle:unit}},meshHeading:{},meshLastPos:{}};
const ctx=vm.createContext({render,TICK_HZ:20,unitScale:()=>unit.scaleFactor,clipFor:()=>'walk'});
vm.runInContext(source.slice(start,stop),ctx);
for(const snapshot of input){
 const record=ctx.meshDrawRecords(snapshot)[0];
 const origin=api.transformVertex(unit.anchor,unit,record);
 const tip=api.transformVertex(unit.anchor.map((v,i)=>v+(i===2?1:0)),unit,record);
 const forward=tip.map((v,i)=>(v-origin[i])/unit.scaleFactor),wanted=snapshot.bugs[0].direction;
 // Original S maps raw Z to raw Y; body matrix row Y is its forward.
 // 3e-7 covers the original f32 root angle and f32 Bridge direction stores.
 forward.forEach((v,i)=>assert(Math.abs(v-wanted[i])<3e-7,JSON.stringify({forward,wanted})));
 assert.equal(record.orientationPolicy,'normal-body-direction-roll0-v1');
 assert.deepEqual(Array.from(record.directionYup),wanted);
 assert.notStrictEqual(record.directionYup,snapshot.bugs[0].direction);
 assert(!Object.hasOwn(record,'headingRadians'),'full body must not also consume yaw');
}
''',snapshots)

    def test_native_matrix_literals_transform_vertices_and_normals_once(self):
        self.node(r'''
const assert=require('assert'),api=require('./web/mesh_scene.js');
const S=[1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1],I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const unit={anchor:[0,0,0],scaleFactor:1,rootMatrix:S};
const draw=directionYup=>({positionYup:[0,0,0],directionYup,orientationPolicy:'normal-body-direction-roll0-v1',sourceScope:'engineering',posePolicy:'engine-pose-v1'});
const near=(actual,wanted)=>actual.forEach((v,i)=>assert(Math.abs(v-wanted[i])<1e-12,JSON.stringify({actual,wanted})));
for(const [direction,point,up] of [[[0,.6,.8],[11,21.4,-9.8],[0,.8,-.6]],[[0,-.6,.8],[11,15.4,17.8],[0,.8,.6]]]){
 const d=draw(direction);
 near(api.transformVertex([11,23,5],unit,d),point);
 near(api.transformNormal([0,0,1],unit,d),direction);
 near(api.transformNormal([0,1,0],unit,d),up);
 near(api.transformNormal([0,1,0],unit,{...d,positionYup:[100,-200,300],scaleFactor:2}),up);
 assert(Math.abs(up.reduce((sum,v,i)=>sum+v*direction[i],0))<1e-12);
}
const scaled={...unit,anchor:[3,7,2],scaleFactor:2},d={...draw([0,.6,.8]),positionYup:[10,3,-4]};
near(api.transformVertex([11,23,5],scaled,d),[26,32.2,-18.4]);
const parent=[...I];parent[12]=5;parent[13]=-7;parent[14]=9;
near(api.transformVertex([11,23,5],scaled,{...d,parentMatrix:parent}),[31,25.2,-9.4]);
near(api.transformNormal([0,1,0],scaled,{...d,parentMatrix:parent}),[0,.8,-.6]);
''')

    def test_horizontal_zero_parallel_and_legacy_orientation_are_distinct(self):
        self.node(r'''
const assert=require('assert'),api=require('./web/mesh_scene.js');
const unit={anchor:[0,0,0],scaleFactor:1,rootMatrix:[1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1]};
const draw={positionYup:[0,0,0],orientationPolicy:'normal-body-direction-roll0-v1',sourceScope:'engineering',posePolicy:'engine-pose-v1'};
const near=(a,b)=>a.forEach((v,i)=>assert(Math.abs(v-b[i])<1e-12));
for(const direction of [[1,0,0],[-1,0,0],[0,0,1],[0,0,-1],[0,1,0],[0,-1,0]]){
 near(api.transformVertex([0,0,1],unit,{...draw,directionYup:direction}),direction);
}
near(api.transformVertex([0,0,1],unit,{...draw,directionYup:[0,0,0]}),[-1,0,0]);
near(api.transformNormal([1,0,0],unit,{...draw,directionYup:[0,1,0]}),[0,0,0]);
const legacy={positionYup:[0,0,0],headingRadians:Math.PI/2,sourceScope:'engineering',posePolicy:'engine-pose-v1'};
near(api.transformVertex([0,0,1],unit,legacy),[0,0,1]);
for(const directionYup of [null,[1,0],[1,0,NaN],['1',0,0]])assert.throws(()=>api.transformVertex([0,0,1],unit,{...draw,directionYup}));
assert.throws(()=>api.transformVertex([0,0,1],unit,{...draw,directionYup:[1,0,0],headingRadians:0}),/also consume/);
assert.throws(()=>api.transformVertex([0,0,1],unit,{...draw,directionYup:[1,0,0],ownerMatrix:unit.rootMatrix}),/also consume/);
assert.throws(()=>api.transformVertex([0,0,1],unit,{...legacy,directionYup:[1,0,0]}),/orientation policy/);
''')

    def test_render_submission_uploads_each_owner_and_shares_pose_geometry(self):
        # Instrument the GL system boundary; this does not execute GPU pixels.
        self.node(r'''
const assert=require('assert'),api=require('./web/mesh_scene.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],S=[1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1];
const mesh={positions:[1,0,0,0,1,0,0,0,1],normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture:null}]};
const clips={walk:{kind:'static',duration:1,loop:true,sampleTimes:[0],frames:[{positions:mesh.positions,normals:mesh.normals}]}};
for(const name of ['idle','normal_attack','hurt','special_attack','special_move'])clips[name]={kind:'missing',fallbackClip:'walk'};
const unit={...mesh,anchor:[0,0,0],rootMatrix:S,scaleFactor:1,clips,rootPolicy:'engineering-fixed-S-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-bind-ground-pivot-v1',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false};
const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{ant:unit},textures:{},worlds:{w:{basisVersion:'loaded-yup-v1',meshes:[mesh]}}};
let vaos=0,clears=0;const noop=()=>{},uniforms={},submitted=[];
const gl=new Proxy({NO_ERROR:0,isContextLost:()=>false,getError:()=>0,getShaderParameter:()=>true,getProgramParameter:()=>true,createShader:()=>({}),createProgram:()=>({}),createTexture:()=>({}),createBuffer:()=>({}),createVertexArray:()=>{vaos++;return {};},getUniformLocation:(program,name)=>name,
 uniform1i:(name,value)=>{uniforms[name]=value;},uniform1f:(name,value)=>{uniforms[name]=value;},uniformMatrix4fv:(name,transpose,value)=>{assert.equal(transpose,false);uniforms[name]=Array.from(value);},clear:()=>{clears++;},drawElements:()=>{if(uniforms.uUnit===1)submitted.push({owner:[...uniforms.uOwner],heading:uniforms.uHeading});}},
 {get:(o,k)=>k in o?o[k]:/^[A-Z_]+$/.test(k)?1:noop});
const canvas={width:640,height:640,getContext:()=>gl,addEventListener:noop,removeEventListener:noop};
const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:1,far:100};
const base={unitId:'ant',clip:'walk',frame:0,positionYup:[0,0,20],posePolicy:'engine-pose-v1',sourceScope:'engineering'};
const records=[{...base,id:1,directionYup:[0,.6,.8],orientationPolicy:'normal-body-direction-roll0-v1'},
 {...base,id:2,directionYup:[0,-.6,.8],orientationPolicy:'normal-body-direction-roll0-v1'},
 {...base,id:3,headingRadians:Math.PI/2}];
(async()=>{
 const scene=await api.prepareMeshScene({assets,projection,worldId:'w',canvas});
 const before=vaos,result=scene.renderFrame({snapshot:{tick:4},drawRecords:records});
 assert.equal(submitted.length,3);assert.equal(vaos,before+1,'one shared unit/clip/frame VAO');
 for(let i=0;i<3;i++){
   assert.deepEqual(submitted[i].owner,result.draws[i].ownerMatrix.map(Math.fround));
   assert.equal(submitted[i].heading,i<2?0:Math.PI/2);
 }
 const forward=m=>[-m[0],-m[1],-m[2]]; // native model raw Z -> S -> canonical -X
 for(let i=0;i<2;i++)forward(submitted[i].owner).forEach((v,j)=>assert(Math.abs(v-records[i].directionYup[j])<1e-7));
 assert.deepEqual(submitted[2].owner,I,'legacy resets owner, does not retain prior body matrix');
 assert.equal(result.draws[0].orientationPolicy,'normal-body-direction-roll0-v1');
 assert.equal(result.draws[2].orientationPolicy,'legacy-yaw-v1');
 const cached=vaos;scene.renderFrame({snapshot:{tick:4},drawRecords:records,dpr:2});assert.equal(vaos,cached);
 const clearCount=clears;assert.throws(()=>scene.renderFrame({snapshot:{tick:4},drawRecords:[{...records[0],headingRadians:0}]}));assert.equal(clears,clearCount);
 scene.dispose();
})().catch(error=>{console.error(error);process.exitCode=1;});
''')


if __name__=='__main__':unittest.main()
