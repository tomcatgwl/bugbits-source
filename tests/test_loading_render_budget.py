"""Real complete host renderFrame: loading work, publication and resume boundaries."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SETUP = r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const counts={clear:0,terrain:0,mesh:0,sprite:0,meshRecords:0,propRecords:0,nectarRecords:0};
const queued=[];
const context={setTransform(){},clearRect(){counts.clear++;},save(){},beginPath(){},rect(){},clip(){},restore(){},
 drawImage(){counts.terrain++;},fillRect(){},strokeRect(){},fillText(){},arc(){},fill(){},stroke(){}};
const canvas={width:640,height:640,getContext:()=>context};
const snapshot={tick:10,pathNectar:[],flowers:[{name:'Flower',pos:[1,2,3],nectar:1}],hives:[],
 bugs:[{id:7,unit:'ant',pos:[2,3,4],dead:false,trapped:false}]};
const state={phase:'loading',lastSnapshot:snapshot,tick:10,generation:3,world:'world_01',starts0:null};
const render={draws:[{id:'stale'}],terrain:{width:1024},projection:{aspect:1},atlas:{flower:'flower'},
 fallbackHits:{},presetReqSeq:10,cameraReady:true,activePresetKey:null,activePreset:null,presetTerrain:null,meshScene:null};
const frameMark={seq:7,tick:22,stateTick:22,generation:2,presetKey:'old',cameraReady:true};
const scope=vm.createContext({render,state,frameMark,CANVAS_SIZE:640,window:{devicePixelRatio:2},
 $:id=>id==='scene'?canvas:null,perf:{_lastFrame:0,frameTimes:[],push(){}},
 requestAnimationFrame:fn=>{queued.push(fn);return queued.length;},
 activeProjection:()=>render.activePreset.projection,activeSpritePrefix:()=>'',
 flowerBillboard:()=>({px:10,py:20,lam:1}),unitBillboard:()=>({px:50,py:60,lam:1,camZ:100}),
 drawUnitSprite:()=>{counts.sprite++;return true;},clipFor:()=> 'walk',
 resolveClip:()=>({clip:'walk',def:{frames:2,duration:1,kind:'animated',prefix:'ant'}}),
 frameIndex:()=>0,yawIndex:()=>0,drawTargetIndicators(){},
 meshDrawRecords:()=>{counts.meshRecords++;return [{id:7}];},
 meshPropRecords:()=>{counts.propRecords++;return [{id:'flower:Flower'}];}});
const host=fs.readFileSync('web/host.js','utf8');
vm.runInContext(host.slice(host.indexOf('function updateNativeCamera('),
 host.indexOf('function updateMeshFollow(')),scope);
const first=host.indexOf('function renderFrame('),last=host.indexOf('async function init(',first);
assert(first>=0&&last>first,'actual full presentation function must exist');
vm.runInContext(host.slice(first,last),scope);
vm.runInContext(host.slice(host.indexOf('function meshNectarRecords('),host.indexOf('// Mesh nectar adapter end')),scope);
const nectarAdapter=scope.meshNectarRecords;
scope.meshNectarRecords=(snapshot,props)=>{counts.nectarRecords++;return nectarAdapter(snapshot,props);};
function mesh(){render.activePreset={projection:{aspect:1.6}};render.activePresetKey='mesh_cam';
 render.meshAssets={worlds:{world_01:{propInstances:[]}}};
 render.meshScene={renderFrame({snapshot,drawRecords,propRecords,spriteRecords,dpr}){
  counts.mesh++;assert.equal(snapshot.tick,10);assert.equal(drawRecords.length,1);
  assert.equal(propRecords.length,1);assert.equal(dpr,2);
  assert.equal(spriteRecords.length,0,'legacy packet has no named nectar contract');
  return {canvas:{},draws:[{id:7}],propDraws:[{id:'flower:Flower'}]};}};}
function scheduledOnce(){assert.equal(queued.length,1);assert.equal(queued[0],scope.renderFrame);}
"""


class LoadingRenderBudget(unittest.TestCase):
    def node(self, behavior):
        result = subprocess.run(['node', '-e', SETUP + behavior], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_loading_clears_terrain_and_sprite_work_without_completed_publication(self):
        self.node(r"""
const before=JSON.stringify(frameMark);scope.renderFrame(50);
assert.equal(counts.clear,1,'loading canvas must clear');
assert.equal(canvas.width,1280);assert.equal(canvas.height,1280);
assert.equal(counts.terrain,0,'loading must not draw old terrain');
assert.equal(counts.sprite,0,'loading must not render flower or unit atlas');
assert.equal(JSON.stringify(render.draws),'[]','loading must discard stale draws');
assert.equal(JSON.stringify(frameMark),before,'loading must not publish completed frame');
scheduledOnce();
""")

    def test_loading_skips_mesh_and_props_then_running_resumes_full_actual_function(self):
        self.node(r"""
mesh();const before=JSON.stringify(frameMark);scope.renderFrame(50);
assert.equal(counts.clear,1);assert.equal(counts.mesh,0,'loading must not submit GPU scene');
assert.equal(counts.meshRecords,0);assert.equal(counts.propRecords,0);
assert.equal(counts.nectarRecords,0,'loading must skip nectar adapter work');
assert.equal(JSON.stringify(frameMark),before);assert.equal(JSON.stringify(render.draws),'[]');
scheduledOnce();const next=queued.shift();state.phase='running';next(70);
assert.equal(counts.mesh,1);assert.equal(counts.meshRecords,1);assert.equal(counts.propRecords,1);
assert.equal(counts.nectarRecords,1);
assert.equal(frameMark.seq,8);assert.equal(frameMark.tick,10);assert.equal(frameMark.stateTick,10);
assert.equal(frameMark.generation,3);assert.equal(frameMark.stageAspect,1.6);
assert.equal(frameMark.presetKey,'mesh_cam');assert.equal(frameMark.cameraReady,true);
assert.equal(render.draws.length,2);assert.equal(render.draws[0].id,7);
assert.equal(render.draws[1].id,'flower:Flower');scheduledOnce();
""")

    def test_selecting_and_error_keep_presenting_and_scheduling(self):
        for phase in ('selecting', 'error'):
            with self.subTest(phase=phase):
                self.node("state.phase=" + repr(phase) + r""";scope.renderFrame(50);
assert.equal(counts.clear,1);assert.equal(counts.terrain,1);
assert.equal(counts.sprite,2);assert.equal(frameMark.seq,8);
assert.equal(frameMark.generation,3);assert.equal(frameMark.tick,10);scheduledOnce();
""")
