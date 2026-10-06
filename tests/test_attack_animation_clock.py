"""Public Bridge attack playback reaches both host animation consumers."""
import json
from pathlib import Path
import subprocess
import unittest

from bugbits import unitdb, web_data
from bugbits.level import LevelData
from bugbits.web_bridge import WebBridge
from bugbits.worlddb import Start, Waypoint, WorldData

ROOT = Path(__file__).resolve().parents[1]

NODE_SETUP = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const host=fs.readFileSync('web/host.js','utf8');
const attack={kind:'sampled',frames:Array.from({length:16},()=>({})),duration:2.933333396911621};
const render={meshAssets:{units:{ant:{clips:{normal_attack:attack}}}},meshHeading:{},meshLastPos:{}};
const state={tick:0,units:input.units,testMode:false};
const scope=vm.createContext({state,render,TICK_HZ:20,unitScale:()=>1});
vm.runInContext(host.slice(host.indexOf('function clipFor('),host.indexOf('// ── CAM-03')),scope);
let start=host.indexOf('function attackElapsedSeconds(');
if(start<0)start=host.indexOf('function frameIndex(');
vm.runInContext(host.slice(start,host.indexOf('// Mesh snapshot adapter end')),scope);
function frames(snapshot){state.tick=snapshot.tick;const bug=snapshot.bugs.find(b=>b.side===0);
 const mesh=scope.meshDrawRecords(snapshot).find(r=>r.id===bug.id);
 return [mesh.frame,scope.frameIndex({frames:16,duration:attack.duration,def_kind:'attack'},bug,900000)];}
"""


class AttackAnimationClock(unittest.TestCase):
    def node(self, js, payload):
        result = subprocess.run(['node', '-e', NODE_SETUP + js], cwd=ROOT,
                                input=json.dumps(payload), text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_attack_local_ticks_advance_mesh_and_sprite_frames(self):
        spec = unitdb.load_unit('ant')
        self.assertEqual(spec.attack_speed, 1.5)
        self.assertEqual(spec.attack_duration, 2.933333396911621)
        world = WorldData({}, [], [], None,
                          [Start('A', (0., 0., 0.), (1., 0., 0.), 0, 0, ['B']),
                           Start('E', (2., 0., 0.), (-1., 0., 0.), 1, 0, ['B'])],
                          [Waypoint('B', (1000., 0., 0.), (1., 0., 0.), False, [])],
                          2, {'A': {'B'}, 'E': {'B'}, 'B': set()})
        level = LevelData({'Type': ['battle'], 'InitialNectar': ['100'],
                           'NectarOnPaths': ['0'], 'PlayerBaseSize': ['100'],
                           'EnemyBaseSize': ['100']}, [], [],
                          [('sendenemy', ['ant', '0', 'null', '0'])], None)
        units = {'ant': web_data.unit_to_dict(spec)}
        bridge = WebBridge()
        opened = bridge.init('attack-clock-public', 42, web_data.level_to_dict(level),
                             web_data.world_to_dict(world), units, {'buyable': ['ant']})
        self.assertTrue(bridge.submit({'type': 'buy', 'commandId': 'clock-buy',
                                     'sessionId': opened['sessionId'],
                                     'unit': 'ant', 'lane': 0})['queued'])
        snapshots = []
        for _ in range(80):
            self.assertEqual(bridge.advance(1)['advanced'], 1)
            snapshot = bridge.snapshot()
            if any(b['side'] == 0 and b['attackTick'] in (0, 3, 18)
                   for b in snapshot['bugs']):
                snapshots.append(snapshot)
            if len(snapshots) == 3:
                break
        self.assertEqual([next(b for b in s['bugs'] if b['side'] == 0)['attackTick']
                          for s in snapshots], [0, 3, 18])
        # Native rate 1.5: local .225 and 1.35 seconds fall in sampled bins 1 and 7.
        self.node(r"""
assert.deepEqual(input.snapshots.map(frames),[[0,0],[1,1],[7,7]]);
for(const snapshot of input.snapshots){const later={...snapshot,tick:snapshot.tick+500};
 assert.deepEqual(frames(later),frames(snapshot),'global time cannot change local attack pose');}
""", {'units': units, 'snapshots': snapshots})

    def test_rates_restart_and_pause_do_not_use_global_or_wall_time(self):
        self.node(r"""
const snapshot={tick:900,bugs:[{id:7,side:0,unit:'ant',pos:[0,0,0],attackTick:10}]};
// 10 ticks at rate 1.5 is .75 s: sampled bin 4, independently of render time.
assert.deepEqual(frames(snapshot),[4,4]);
assert.deepEqual(frames(snapshot),[4,4],'a paused snapshot keeps its attack pose');
snapshot.bugs[0].attackTick=0;assert.deepEqual(frames(snapshot),[0,0],'next attack restarts');
state.units.ant.props.AttackSpeed=['2'];snapshot.bugs[0].attackTick=10;
assert.deepEqual(frames(snapshot),[5,5],'rate 2 places one second in bin 5');
state.units.ant.props.AttackSpeed=['0'];assert.deepEqual(frames(snapshot),[2,2],'Sim zero-rate default is 1');
delete state.units.ant.props.AttackSpeed;assert.deepEqual(frames(snapshot),[2,2]);
state.units.ant.props.AttackSpeed=['1.5'];snapshot.bugs[0].attackTick=40;
assert.deepEqual(frames(snapshot),[15,15],'no loop wraps an attack beyond its last frame');
""", {'units': {'ant': {'props': {'AttackSpeed': ['1.5']}}}})

    def test_nonattack_mesh_and_sprite_time_contracts_are_preserved(self):
        self.node(r"""
render.meshAssets.units.ant.clips.walk={kind:'sampled',frames:Array(4).fill({}),duration:2};
const bug={id:7,side:0,unit:'ant',pos:[0,0,0],mode:'lane',attackTick:-1};
assert.equal(scope.meshDrawRecords({tick:10,bugs:[bug]})[0].frame,1);
state.tick=10;state.testMode=true;
assert.equal(scope.frameIndex({frames:4,duration:2,def_kind:'loop'},bug,7000),1);
state.testMode=false;
assert.equal(scope.frameIndex({frames:4,duration:2,def_kind:'loop'},bug,1250),2);
assert.equal(scope.frameIndex({frames:1,duration:0,def_kind:'attack'},bug,9000),0);
""", {'units': {}})
