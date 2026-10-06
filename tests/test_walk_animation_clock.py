"""Normal public motion produces instance-local walk playback for the host."""
import unittest
import json
from pathlib import Path
import subprocess

from bugbits import unitdb, web_data, worlddb
from bugbits.web_bridge import WebBridge
from test_normal_motion import normal_game


class WalkAnimationClock(unittest.TestCase):
    def configured_bridge(self, *, base=20, ratio=0, duration=2):
        # Synthetic binary-friendly track inputs isolate the native loop rule.
        game = normal_game(acceleration=0, direction_factor=0, speed=5)
        spec = game.units['ant']
        spec.props['AnimBaseSpeed'], spec.props['AnimRatio'] = [str(base)], [str(ratio)]
        spec.walk_duration = duration
        payload = (web_data.level_to_dict(game.level), web_data.world_to_dict(game.world),
                   {'ant': web_data.unit_to_dict(spec)}, {'buyable': ['ant']})
        bridge = WebBridge()
        opened = bridge.init('walk-fixture', 2026, *payload)
        bridge.submit({'type': 'buy', 'commandId': 'walk-buy',
                       'sessionId': opened['sessionId'], 'unit': 'ant', 'lane': 0})
        return bridge, payload

    def test_public_overshoot_subtracts_once_and_zero_rate_preserves_phase(self):
        bridge, _ = self.configured_bridge(base=100)
        bridge.advance(3)
        clock = bridge.snapshot()['bugs'][0]['walkAnimation']
        self.assertEqual((clock['phase'], clock['loopCount'], clock['rate']), (3., 1, 100.))
        bridge.advance(1)
        clock = bridge.audit_state()['bugs'][0]['walkAnimation']
        self.assertEqual((clock['phase'], clock['loopCount']), (6., 2))
        stationary, _ = self.configured_bridge(base=0)
        self.assertEqual(stationary.advance(5)['advanced'], 5)
        self.assertEqual(stationary.advance(3)['advanced'], 3)
        clock = stationary.snapshot()['bugs'][0]['walkAnimation']
        self.assertEqual((clock['phase'], clock['rate'], clock['playing']), (0., 0., True))

    def test_static_playback_configuration_affects_future_hash_and_reset(self):
        stopped, _ = self.configured_bridge(base=0)
        moving, payload = self.configured_bridge(base=20)
        stopped.advance(1)
        moving.advance(1)
        self.assertEqual(stopped.snapshot()['bugs'][0]['pos'], moving.snapshot()['bugs'][0]['pos'])
        # Sim.state_hash is the public state summary seam; Bridge audit exposes
        # the corresponding clocks, without reaching into Bridge's session.
        games = [normal_game(acceleration=0), normal_game(acceleration=0)]
        for game, base in zip(games, (0, 20)):
            game.units['ant'].props['AnimBaseSpeed'] = [str(base)]
            self.assertIsNotNone(game.buy(0, 'ant', 0))
        self.assertNotEqual(games[0].state_hash(), games[1].state_hash())
        self.assertNotEqual(stopped.audit_state()['bugs'][0]['walkAnimation'],
                            moving.audit_state()['bugs'][0]['walkAnimation'])
        moving.advance(4)
        previous = moving.snapshot()['sessionId']
        opened = moving.reset('walk-reset', 2026, *payload)
        self.assertNotEqual(previous, opened['sessionId'])
        self.assertEqual(moving.snapshot()['bugs'], [])
        moving.submit({'type': 'buy', 'commandId': 'new-buy', 'sessionId': opened['sessionId'],
                       'unit': 'ant', 'lane': 0})
        moving.advance(1)
        clock = moving.snapshot()['bugs'][0]['walkAnimation']
        self.assertEqual((clock['phase'], clock['rate'], clock['playing'], clock['loopCount']),
                         (0., 1., False, 0))

    def test_units_born_at_different_ticks_keep_independent_track_states(self):
        bridge, payload = self.configured_bridge()
        world = web_data.restore_world(payload[1])
        world.starts.append(worlddb.Start('A2', (0., 0., 100.), (1., 0., 0.), 0, 1, ['B']))
        world.adjacency['A2'] = {'B'}
        opened = bridge.reset('walk-two', 2026, payload[0], web_data.world_to_dict(world),
                              payload[2], payload[3])
        for lane, tick in ((0, 1), (1, 3)):
            self.assertTrue(bridge.submit({'type': 'buy', 'commandId': 'lane-'+str(lane),
                'sessionId': opened['sessionId'], 'unit': 'ant', 'lane': lane,
                'targetTick': tick})['queued'])
        bridge.advance(4)
        clocks = [b['walkAnimation'] for b in bridge.snapshot()['bugs']]
        self.assertEqual([c['phase'] for c in clocks], [2., 0.])
        bridge.advance(1)
        clocks = [b['walkAnimation'] for b in bridge.snapshot()['bugs']]
        self.assertEqual([c['phase'] for c in clocks], [1., 1.])
        self.assertEqual([c['loopCount'] for c in clocks], [1, 0])

    def test_all_actual_unit_walk_durations_survive_web_restore(self):
        specs = unitdb.load_all()
        self.assertEqual(len(specs), 24)
        for name, spec in specs.items():
            restored = web_data.restore_unit(web_data.unit_to_dict(spec))
            self.assertEqual(restored.walk_duration, spec.walk_duration, name)
            self.assertGreater(restored.walk_duration, 0, name)

    def test_natural_contact_then_return_to_walk_restarts_the_local_track(self):
        bridge, payload = self.configured_bridge()
        level = web_data.restore_level(payload[0])
        level.scripts = [('wait', ['2']), ('sendenemy', ['ant', '0', 'null', '0'])]
        world = web_data.restore_world(payload[1])
        world.starts[1].grid_pos = (2., 0., 0.)
        units = payload[2]
        units['ant']['props']['InitialHealth'] = ['1']
        opened = bridge.reset('walk-contact', 2026, web_data.level_to_dict(level),
                              web_data.world_to_dict(world), units, payload[3])
        bridge.submit({'type': 'buy', 'commandId': 'contact-buy',
                       'sessionId': opened['sessionId'], 'unit': 'ant', 'lane': 0})
        had_walk, had_contact, resumed = False, False, None
        for _ in range(120):
            self.assertEqual(bridge.advance(1)['advanced'], 1)
            player = next(b for b in bridge.snapshot()['bugs'] if b['side'] == 0)
            clock = player['walkAnimation']
            if not had_contact and clock['loopCount'] > 0:
                had_walk = True
            if player['attackTick'] >= 0:
                had_contact = True
                self.assertFalse(clock['selected'])
                self.assertFalse(clock['playing'])
            elif had_contact and clock['selected']:
                resumed = clock
                break
        self.assertTrue(had_walk, 'contact must follow a running walk track')
        self.assertTrue(had_contact, 'natural Sim combat must select attack')
        self.assertIsNotNone(resumed, 'surviving unit must return to walk')
        self.assertEqual((resumed['phase'], resumed['loopCount']), (1., 0))

    def test_snapshot_walk_phase_selects_both_host_frames_without_modulo(self):
        bridge, payload = self.configured_bridge()
        snapshots = []
        for _ in range(5):
            bridge.advance(1)
            snapshots.append(bridge.snapshot())
        self.assertEqual([s['bugs'][0]['walkAnimation']['phase'] for s in snapshots],
                         [0., 0., 1., 2., 1.])
        script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),host=fs.readFileSync('web/host.js','utf8');
const walk={kind:'sampled',frames:Array(4).fill({}),duration:2};
const render={meshAssets:{units:{ant:{clips:{walk}}}},meshHeading:{},meshLastPos:{}};
const state={tick:0,units:input.units,testMode:false};
const scope=vm.createContext({state,render,TICK_HZ:20,unitScale:()=>1});
vm.runInContext(host.slice(host.indexOf('function clipFor('),host.indexOf('// ── CAM-03')),scope);
vm.runInContext(host.slice(host.indexOf('function attackElapsedSeconds('),host.indexOf('// Mesh snapshot adapter end')),scope);
function frames(s){state.tick=s.tick;const bug=s.bugs[0];
 return [scope.meshDrawRecords(s)[0].frame,
 scope.frameIndex({frames:4,duration:2,def_kind:'loop',clip:'walk'},bug,1250)];}
assert.deepEqual(input.snapshots.map(frames),[[0,0],[0,0],[2,2],[3,3],[2,2]]);
for(const s of input.snapshots){const expected=frames(s);
 assert.deepEqual(frames({...s,tick:s.tick+500}),expected);
 state.testMode=true;assert.deepEqual(frames(s),expected);state.testMode=false;}
// Native oversized advance subtracts only once: supplied phase3 stays last.
const end=JSON.parse(JSON.stringify(input.snapshots[4]));end.bugs[0].walkAnimation.phase=3;
assert.deepEqual(frames(end),[3,3]);
// Wrong track identity cannot silently borrow global time.
const bad=JSON.parse(JSON.stringify(end));bad.bugs[0].walkAnimation.duration=3;
assert.throws(()=>frames(bad),/Walk snapshot animation phase/);
// Resolve missing walk first: an idle fallback has its own legacy contract.
render.meshAssets.units.ant.clips.walk={kind:'missing',fallbackClip:'idle'};
render.meshAssets.units.ant.clips.idle=walk;
assert.equal(scope.meshDrawRecords(end)[0].clip,'idle');
assert.equal(scope.meshDrawRecords(end)[0].frame,0);
assert.equal(scope.frameIndex({frames:4,duration:2,def_kind:'loop',clip:'idle'},end.bugs[0],1250),2);
"""
        result = subprocess.run(['node', '-e', script],
                                cwd=Path(__file__).resolve().parents[1],
                                input=json.dumps({'units': payload[2], 'snapshots': snapshots}),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_controller_samples_old_velocity_before_advancing_walk_phase(self):
        game = normal_game(acceleration=100, direction_factor=0, speed=5)
        bridge = WebBridge()
        opened = bridge.init('local-walk', 2026, web_data.level_to_dict(game.level),
                             web_data.world_to_dict(game.world),
                             {'ant': web_data.unit_to_dict(game.units['ant'])},
                             {'buyable': ['ant']})
        self.assertTrue(bridge.submit({'type': 'buy', 'commandId': 'walk-buy',
                                     'sessionId': opened['sessionId'],
                                     'unit': 'ant', 'lane': 0})['queued'])
        observed = []
        for _ in range(4):
            self.assertEqual(bridge.advance(1)['advanced'], 1)
            snapshot = bridge.snapshot()
            self.assertEqual(snapshot, bridge.snapshot(), 'reading cannot advance playback')
            observed.append(snapshot['bugs'][0]['walkAnimation'])
        # Buy happens after the first step; state1's next step schedules state4.
        # State4 then samples OLD velocity5, rate1 and dt=f32(.05), twice.
        self.assertEqual([x['phase'] for x in observed],
                         [0., 0., 0.05000000074505806, 0.10000000149011612])
        self.assertEqual([x['playing'] for x in observed], [False, False, True, True])
        self.assertEqual(observed[-1]['rate'], 1.)
        self.assertEqual(bridge.audit_state()['bugs'][0]['motion']['velocity'][0], 9.75)
