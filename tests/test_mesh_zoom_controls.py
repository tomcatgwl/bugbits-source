"""User DOM controls reach the complete host frame and scene projection seam."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

SETUP = r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const camera=require('./web/camera_projection.js'),host=fs.readFileSync('web/host.js','utf8');
const elements={};
function element(){return {dataset:{},appendChild(){},append(){},setAttribute(){},
 set id(value){this._id=value;elements[value]=this;},get id(){return this._id;}};}
const document={createElement:element},controls=element();
const context={setTransform(){},clearRect(){},save(){},beginPath(){},rect(){},clip(){},restore(){},drawImage(){}};
const canvas={width:640,height:640,getContext:()=>context};elements.scene=canvas;
const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],
 cameraPosition:[11,23,-175],near:1,far:1000,size:640,aspect:1.6,cot:Math.sqrt(3)};
const submissions=[],frames=[];
const scene={setProjection(p){camera.validateProjection(p);submissions.push(JSON.parse(JSON.stringify(p)));},
 renderFrame(){frames.push(render.meshProjection||projection);return {canvas:{},draws:[]};},dispose(){}};
const render={meshScene:scene,activePreset:{projection,meshView:{targetYup:[11,23,5],distance:180}},
 meshFollowId:null,meshZoomFactor:1,meshTargetYup:null,meshProjection:null,
 meshHeading:{},meshLastPos:{},meshAssets:{units:{},worlds:{world_01:{propInstances:[]}}},
 projection:{aspect:1},atlas:null,presetReqSeq:0,presetTerrain:null,terrain:null,draws:[],fallbackHits:{}};
const state={phase:'running',lastSnapshot:{tick:10,bugs:[],flowers:[]},tick:10,generation:1,world:'world_01',starts0:null};
const scope=vm.createContext({render,state,document,controls,BugBitsCameraProjection:camera,CANVAS_SIZE:640,TICK_HZ:20,
 window:{devicePixelRatio:1},$:id=>elements[id]||null,
 perf:{_lastFrame:0,frameTimes:[],push(){}},frameMark:{seq:0},requestAnimationFrame(){},
 drawTargetIndicators(){},unitInfo:unit=>({name:unit}),unitScale:()=>1,
 syncStageGeometry(){},updateCameraControl(){}});
function section(first,last){const a=host.indexOf(first),b=host.indexOf(last,a);assert(a>=0&&b>a);return host.slice(a,b);}
vm.runInContext(section('function activeProjection(', '// One 3D/depth'),scope);
vm.runInContext(section('function commitCameraView(', '// Mesh view controls end'),scope);
vm.runInContext(section("  const meshControls = document.createElement('span');", '  const pause = document.createElement('),scope);
vm.runInContext(section('function attackElapsedSeconds(', '// Mesh snapshot adapter end'),scope);
vm.runInContext(section('function clipFor(', '// ── CAM-03'),scope);
vm.runInContext(section('function meshPropRecords(', '// Mesh prop adapter end'),scope);
vm.runInContext(section('function meshNectarRecords(', '// Mesh nectar adapter end'),scope);
vm.runInContext(section('function renderFrame(', 'async function init('),scope);
function zoom(value){elements['mesh-zoom'].value=String(value);elements['mesh-zoom'].oninput();scope.renderFrame(50);}
"""


class MeshZoomControls(unittest.TestCase):
    def node(self, behavior):
        result = subprocess.run(['node', '-e', SETUP + behavior], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_slider_return_to_one_updates_the_actual_rendered_projection(self):
        self.node(r"""
zoom(.5);assert.deepEqual(submissions.at(-1).cameraPosition,[11,23,-85]);
zoom(1);assert.deepEqual(submissions.at(-1).cameraPosition,[11,23,-175]);
assert.deepEqual(Array.from(frames.at(-1).cameraPosition),[11,23,-175]);
assert.equal(elements['mesh-zoom'].value,'1');
const count=submissions.length;scope.renderFrame(60);
assert.equal(submissions.length,count,'settled non-follow camera is not reset each frame');
""")

    def test_stop_follow_then_zoom_retains_target_and_home_restores_preset(self):
        self.node(r"""
render.meshAssets.units.ant={clips:{walk:{kind:'sampled',frames:[{}],duration:1}}};
state.lastSnapshot.bugs=[{id:7,side:0,unit:'ant',dead:false,pos:[20,30,40],attackTick:-1}];
elements['mesh-target'].value='auto';elements['mesh-follow'].onclick();scope.renderFrame(50);
assert.deepEqual(submissions.at(-1).cameraPosition,[20,30,-140]);
elements['mesh-follow'].onclick();state.lastSnapshot.bugs[0].pos=[100,200,300];
scope.renderFrame(60);assert.deepEqual(submissions.at(-1).cameraPosition,[20,30,-140]);
zoom(.5);assert.deepEqual(submissions.at(-1).cameraPosition,[20,30,-50]);
zoom(1);assert.deepEqual(submissions.at(-1).cameraPosition,[20,30,-140]);
elements['mesh-home'].onclick();scope.renderFrame(70);
assert.deepEqual(submissions.at(-1).cameraPosition,[11,23,-175]);
assert.equal(elements['mesh-zoom'].value,'1');
const count=submissions.length;scope.renderFrame(80);assert.equal(submissions.length,count);
""")

    def test_first_snapshot_defers_zoom_and_captured_view_has_no_zoom_entry(self):
        self.node(r"""
const snapshot=state.lastSnapshot;state.lastSnapshot=null;zoom(1);
assert.equal(submissions.length,0,'first worker snapshot has not arrived');
state.lastSnapshot=snapshot;scope.renderFrame(60);
assert.deepEqual(submissions.at(-1).cameraPosition,[11,23,-175]);
// The real camera publication resets pending input when leaving an operable view.
elements['mesh-zoom'].value='.5';elements['mesh-zoom'].oninput();
scope.commitCameraView('original_static_01',{projection},null,scene,render.meshAssets);
scope.renderFrame(70);assert.equal(elements['mesh-controls'].hidden,true);
const count=submissions.length;elements['mesh-zoom'].oninput();scope.renderFrame(80);
assert.equal(submissions.length,count,'captured view keeps its fixed projection');
""")
