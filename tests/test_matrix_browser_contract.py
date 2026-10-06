"""Same production JS API in Node; expectations are independent hand literals."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'web/camera_projection.js'


class MatrixBrowserContract(unittest.TestCase):
    def js(self, body):
        source = "const assert=require('assert'); const api=require(process.argv[1]);" + body
        result = subprocess.run(['node','-e',source,str(MODULE)], cwd=ROOT,
                                capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_height_translation_and_projection_match_independent_literals(self):
        self.js("""
const p={kind:'matrix-yup-v1',basis9:[-1,0,0,0,1,0,0,0,-1],cameraPosition:[-23,5,11],size:100,cot:1,aspect:2,near:1,far:100};
assert.deepStrictEqual(api.cameraSpace(p,[-19,0,-9]),[-4,-5,20]);
assert.deepStrictEqual(api.projectWorldPoint(p,[-19,0,-9]),{px:90,py:62.5,camZ:20});
const elevated=api.projectWorldPoint(p,[-19,3,-9]);
assert(Math.abs(elevated.px-90)<1e-12 && Math.abs(elevated.py-55)<1e-12 && elevated.camZ===20);
""")

    def test_inverse_planes_and_strict_public_input_domain(self):
        self.js("""
const p={kind:'matrix-yup-v1',basis9:[-1,0,0,0,1,0,0,0,-1],cameraPosition:[-23,5,11],size:100,cot:1,aspect:2,near:1,far:100};
const hit=api.pixelToGround(p,90,62.5); assert(Math.abs(hit[0]+19)<1e-12 && Math.abs(hit[1]+9)<1e-12);
assert.strictEqual(api.pixelToGround(p,100,50),null);
assert.strictEqual(api.pixelToGround(p,100,0),null);
assert.strictEqual(api.pixelToGround(p,100,50.01),null);
for (const z of [11,12,-90]) assert.strictEqual(api.projectWorldPoint(p,[-23,5,z]),null);
assert.strictEqual(api.projectWorldPoint(p,[-23,5,10]).camZ,1);
assert.strictEqual(api.projectWorldPoint(p,[-23,5,-89]).camZ,100);
for(const q of [{...p,kind:'unknown'},{...p,basis9:[2,0,0,0,1,0,0,0,-1]},
 {...p,basis9:[1,0,0,0,1,0,0,0,-1]},{...p,basis9:[-1,.1,0,0,1,0,0,0,-1]},
 {...p,cameraPosition:[true,5,11]},{...p,cameraPosition:[0,0,NaN]},
 {...p,cot:0},{...p,near:0},{...p,far:1},{...p,basis9:[1]},
 {...p,size:'100'},{...p,size:Infinity},{...p,aspect:0}]) assert.throws(()=>api.validateProjection(q));
for(const point of [[true,0,0],[0,0],[0,Infinity,0]]) assert.throws(()=>api.cameraSpace(p,point));
assert.throws(()=>api.pixelToGround(p,NaN,50));
""")

    def test_real_host_logical_coordinates_and_matrix_ground_input(self):
        self.js("""
const fs=require('fs'),vm=require('vm'),path=require('path');
const host=fs.readFileSync(path.join(path.dirname(process.argv[1]),'host.js'),'utf8');
const p={kind:'matrix-yup-v1',basis9:[-1,0,0,0,1,0,0,0,-1],cameraPosition:[-23,5,11],size:100,cot:1,aspect:2,near:1,far:100};
const rect={left:0,top:0,right:640,bottom:640,width:640,height:640};
const cvs={getBoundingClientRect:()=>rect,clientLeft:0,clientTop:0};
const stage={getBoundingClientRect:()=>({...rect,top:160,bottom:480,height:320})};
const ctx=vm.createContext({BugBitsCameraProjection:api,CANVAS_SIZE:640,
 render:{activePreset:{projection:p},projection:p},$:(id)=>id==='scene'?cvs:stage});
vm.runInContext(host.slice(host.indexOf('function activeProjection('),host.indexOf('// NC 相机交付：预设精灵键前缀')),ctx);
vm.runInContext(host.slice(host.indexOf('function canvasToWorld('),host.indexOf('let loopRaf')),ctx);
let q=ctx.projectCanvasPoint([-19,0,-9]);assert(Math.abs(q.px-288)<1e-12&&Math.abs(q.py-360)<1e-12);
q=ctx.projectCanvasPoint([-19,3,-9]);assert(Math.abs(q.py-336)<1e-12);
let hit=ctx.canvasToWorld({clientX:288,clientY:360});assert(hit && Math.abs(hit[0]+19)<1e-12&&Math.abs(hit[1]+9)<1e-12);
assert.strictEqual(ctx.canvasToWorld({clientX:288,clientY:100}),null);
""")

    def test_noncommuting_rotation_uses_actual_three_rows_and_height(self):
        self.js("""
// Proper rational noncommuting rotation, hand view of (4,-5,-20).
const p={kind:'matrix-yup-v1',basis9:[.8,.36,.48,0,.8,-.6,-.6,.48,.64],cameraPosition:[-23,5,11],size:100,cot:1,aspect:2,near:1,far:100};
// Rows applied to (4,-5,-20) => (-8.2,8,-17.6), not its transpose.
let v=api.cameraSpace(p,[-19,0,-9]);
assert(v.every((a,i)=>Math.abs(a-[-8.2,8,-17.6][i])<1e-12));
assert.strictEqual(api.projectWorldPoint(p,[-19,0,-9]),null);
// Reversing the displacement gives positive depth and a noncentral pixel.
v=api.cameraSpace(p,[-27,10,31]);
assert(v.every((a,i)=>Math.abs(a-[8.2,-8,17.6][i])<1e-12));
let q=api.projectWorldPoint(p,[-27,10,31]);
assert(Math.abs(q.px-123.29545454545455)<1e-12 && Math.abs(q.py-72.72727272727272)<1e-12);
""")

    def test_real_host_legacy_height_and_shared_billboard_centers(self):
        self.js("""
const fs=require('fs'),vm=require('vm'),path=require('path');
const host=fs.readFileSync(path.join(path.dirname(process.argv[1]),'host.js'),'utf8');
const p={size:100,cot:1,aspect:2,near:1,far:100,tx:-23,tz:11,sinY:0,cosY:1,sinP:0,cosP:1,distance:20};
const ctx=vm.createContext({BugBitsCameraProjection:api,CANVAS_SIZE:640,
 render:{activePreset:null,projection:p},state:{units:{ant:{worldSize:{w:4,h:6,d:4},atlasScale:1}},manifest:{props:{flower:{worldSize:{w:4,h:6,d:4},atlasScale:1}}}}});
vm.runInContext(host.slice(host.indexOf('function activeProjection('),host.indexOf('// NC 相机交付：预设精灵键前缀')),ctx);
vm.runInContext(host.slice(host.indexOf('function unitScale('),host.indexOf('// NC-03：按稳定瓦片')),ctx);
let q=ctx.projectCanvasPoint([-19,3,11]);assert(Math.abs(q.py-296)<1e-12); // y=0 would be320.
const u=ctx.unitBillboard({pos:[-19,0,11]},'ant'),f=ctx.flowerBillboard([-19,0,11]);
assert(Math.abs(u.py-296)<1e-12 && Math.abs(f.py-296)<1e-12 && u.camZ===20 && f.camZ===20);
assert.strictEqual(ctx.unitBillboard({pos:[-19,0,-10]},'ant'),null);
assert.strictEqual(ctx.flowerBillboard([-19,0,-10]),null);
""")

    def test_native_matrix_preset_cannot_be_enabled_by_metadata_labels(self):
        self.js("""
const fs=require('fs'),vm=require('vm'),path=require('path');
const host=fs.readFileSync(path.join(path.dirname(process.argv[1]),'host.js'),'utf8');
const p={kind:'matrix-yup-v1',basis9:[-1,0,0,0,1,0,0,0,-1],cameraPosition:[-23,5,11],size:100,cot:1,aspect:2,near:1,far:100};
const previous={projection:{aspect:1.6}};
const render={worldPresets:{native:{projection:p,presentationScope:'native-sprites-verified',worldBasisVersion:'loaded-yup-v1'}},activePreset:previous,activePresetKey:'wide_cam',presetReqSeq:0,presetController:null};
const ctx=vm.createContext({render,state:{generation:1},BugBitsCameraProjection:api,
 CANVAS_SIZE:640,$:()=>null,loadBitmap:()=>{throw Error('native atlas must not load');}});
vm.runInContext(host.slice(host.indexOf('function closePresetBitmap('),host.indexOf('// ── 音频')),ctx);
(async()=>{assert.strictEqual(await ctx.setCameraPreset('native'),false);
assert.strictEqual(render.activePreset,previous);assert.strictEqual(render.activePresetKey,'wide_cam');
assert.match(render.presetError,/research-only/);})().catch(e=>{console.error(e);process.exitCode=1;});
""")


if __name__ == '__main__': unittest.main()
