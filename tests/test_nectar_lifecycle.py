"""Original field literals, lifecycle identity, and real snapshot/host seams."""
import sys
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from bugbits.sim.nectar import NectarState, WorldClock, FlightWaypoint
from test_sim_gather import make_sim, make_ready_sim, advance_bridge, world_with
from bugbits.web_bridge import WebBridge


class NectarFieldTests(unittest.TestCase):
    def test_independent_entities_accumulate_original_float_fields(self):
        # R366 pinned EXE: 20 arg1=.01 updates; values are independent literals.
        old = NectarState(1, (0, 0, 0), born_tick=0)
        for _ in range(20):
            old.update(.01)
        new = NectarState(2, (0, 0, 0), born_tick=19)
        new.update(.01)
        self.assertEqual(old.size, 1.661960244178772)
        self.assertEqual(old.core_angle, .6283186674118042)
        self.assertEqual(new.size, .09999999403953552)
        self.assertEqual(new.core_angle, .03141592815518379)
        before = old.snapshot()
        old.update(0)
        self.assertEqual(old.snapshot(), before)

    def test_world_dispatch_uses_frame_arg_once_and_no_post_loop_remainder(self):
        clock = WorldClock()
        calls = clock.advance(.025, .3)
        self.assertEqual(len(calls), 2)
        self.assertAlmostEqual(calls[0][0], .01, places=8)
        self.assertAlmostEqual(calls[0][1], .3, places=7)
        self.assertEqual(calls[1][1], 0)
        self.assertEqual(len(clock.advance(.005, .2)), 1)
        low = WorldClock()
        self.assertEqual(low.advance(.005, .2)[0][0], 0)
        self.assertEqual(low.dispatch_count, 1)
        # Disabled normal dispatch still consumes accumulator, as 488015 does.
        self.assertEqual(WorldClock().advance(.025, .3, eligible=False), ())

    def test_existing_nectar_redirect_keeps_visual_age_and_strict_flight_end(self):
        nectar = NectarState(7, (0, 0, 0), born_tick=0)
        nectar.update(.01)
        visual = (nectar.size, nectar.core_angle, nectar.glow_angle)
        nectar.start_flight((100, 2.5, 0), waypoint='W')
        self.assertEqual((nectar.size, nectar.core_angle, nectar.glow_angle), visual)
        self.assertEqual(nectar.pos, (0, 0, 0))
        nectar.update(1)
        self.assertEqual(nectar.pos, (50, 51.25, 0))
        nectar.update(1)
        self.assertEqual(nectar.pos, (100, 2.5, 0))
        self.assertEqual(nectar.flight_duration, 2)
        nectar.update(.01)
        self.assertEqual(nectar.pos, (100, 2.5, 0))
        self.assertEqual(nectar.flight_duration, 0)
        self.assertEqual(nectar.flight_elapsed, 0)

    def test_redirect_failure_preserves_state_and_distance_100_is_eligible(self):
        nectar = NectarState(7, (0, 0, 0), born_tick=0)
        nectar.start_flight((20, 0, 0), waypoint='old')
        before = nectar.snapshot()
        self.assertFalse(nectar.redirect(()))
        self.assertEqual(nectar.snapshot(), before)
        self.assertFalse(nectar.redirect((FlightWaypoint('water', (100, 0, 0), water=True),)))
        self.assertEqual(nectar.snapshot(), before)
        self.assertTrue(nectar.redirect((FlightWaypoint('W', (100, 0, 0)),)))
        self.assertEqual(nectar.flight_start, (0, 0, 0))
        self.assertEqual(nectar.flight_target, (100, 2.5, 0))
        self.assertEqual(nectar.waypoint, 'W')
        self.assertEqual(nectar.rng_state, 1)  # One-candidate/no-neighbor consumes only chain draw.

    def test_redirect_updates_waypoint_at_halfway_including_equality(self):
        # Independent two-draw LCG inverse seeds yield t=.25/.5/.75 respectively.
        # 49BEBF compares the surviving interpolation t with float32 .5.
        neighbor = FlightWaypoint('N', (200, 0, 0))
        waypoint = FlightWaypoint('W', (100, 0, 0), links154=('N',), links130=('N',))
        for seed, expected_waypoint, x in ((3595686626, 'W', 125),
                                           (374461154, 'N', 150),
                                           (1448202978, 'N', 175)):
            with self.subTest(seed=seed):
                nectar = NectarState(7, (0, 0, 0), born_tick=0, rng_state=seed)
                self.assertTrue(nectar.redirect((waypoint,), {'W': waypoint, 'N': neighbor}))
                self.assertEqual(nectar.flight_target, (x, 2.5, 0))
                self.assertEqual(nectar.waypoint, expected_waypoint)

    def test_flight_retains_original_intermediate_float_stores(self):
        # Original target* t, start*(1-t), and their sum have distinct f32 stores.
        # Even equal endpoints can lose one ULP at t=f32(.17).
        x = .12345679104328156
        nectar = NectarState(1, (x, 0, 0), born_tick=0)
        nectar.start_flight((x, 0, 0), waypoint='W')
        nectar.update(.34)
        self.assertEqual(nectar.pos[0], .12345678359270096)

    def test_sim_pickup_and_deposit_transfer_and_destroy_same_identity(self):
        sim = make_ready_sim(world_with([('F', (110, 0, 0))]))
        entity_id = sim.flowers[0].nectar_id
        entity = sim.nectar_entities[entity_id]
        bug = sim.buy(0, 'ant', 0)
        sim.run(32)
        self.assertEqual(bug.carried_nectar_id, entity_id)
        self.assertIs(sim.nectar_entities[entity_id], entity)
        self.assertIsNone(sim.flowers[0].nectar_id)
        self.assertEqual(entity.carrier_id, bug.bug_id)
        self.assertGreater(entity.size, 0)
        sim.run(32)
        self.assertEqual(sim.nectar[0], 13)
        # R371 original deposit marks +12B; +12C needs a later positive arg2,
        # and classification exit follows in the subsequent outer sweep.
        self.assertTrue(entity.alive)
        self.assertTrue(entity.delete_requested)
        self.assertFalse(entity.delete_ready)
        self.assertIsNone(bug.carried_nectar_id)
        sim.step()
        self.assertTrue(entity.delete_ready)
        self.assertTrue(entity.classification_member)
        sim.step()
        self.assertFalse(entity.alive)
        self.assertFalse(entity.classification_member)
        self.assertEqual(len(sim.nectar_entities), 1)

    def test_bridge_exports_owned_entity_fields_deeply_and_reset_clears_age(self):
        template = make_sim(world_with([('F', (110, 0, 0))]))
        bridge = WebBridge()
        bridge.from_objects(template.level, template.world, template.units, 42, {'buyable': ['ant']})
        advance_bridge(bridge,370)  # Birth367; four frames of nectar substeps.
        snapshot = bridge.snapshot()
        entity_id = snapshot['flowers'][0]['nectarId']
        entity = snapshot['nectarEntities'][0]
        self.assertEqual(entity['id'], entity_id)
        self.assertEqual(entity['size'], 1.661960244178772)
        self.assertEqual(bridge.audit_state()['nectarClock']['dispatchCount'], 1850)
        # Original slot20 flower follow copies its point into both endpoints;
        # inactive clocks stay zero. The owned snapshot must preserve each copy.
        self.assertEqual(entity['flight']['start'], [110.0, 0.0, 0.0])
        self.assertEqual(entity['flight']['target'], [110.0, 0.0, 0.0])
        self.assertEqual(entity['flight']['duration'], 0)
        entity['flight']['start'][0] = 999
        entity['flight']['target'] = [999, 999, 999]
        entity['positionYup'][0] = 999
        self.assertEqual(bridge.snapshot()['nectarEntities'][0]['flight']['start'], [110.0, 0.0, 0.0])
        self.assertEqual(bridge.snapshot()['nectarEntities'][0]['flight']['target'], [110.0, 0.0, 0.0])
        self.assertNotEqual(bridge.snapshot()['nectarEntities'][0]['positionYup'][0], 999)
        old = bridge.snapshot()['sessionId']
        bridge.dispose()
        bridge.from_objects(template.level, template.world, template.units, 42, {'buyable': ['ant']})
        self.assertNotEqual(bridge.snapshot()['sessionId'], old)
        self.assertEqual(bridge.snapshot()['nectarEntities'], [])
        self.assertEqual(bridge.snapshot()['flowers'][0]['cycle']['phase'], 0)

    def test_actual_host_reads_entity_fields_instead_of_global_tick(self):
        template = make_sim(world_with([('F', (110, 0, 0))]))
        bridge = WebBridge()
        bridge.from_objects(template.level, template.world, template.units, 42, {'buyable': ['ant']})
        advance_bridge(bridge,370)
        packet = bridge.snapshot()
        code = """
const assert=require('assert'),fs=require('fs'),vm=require('vm');
const snapshot=JSON.parse(fs.readFileSync(0,'utf8'));
const render={meshAssets:{nectarSprites:{contract:'bind-flower-nectar-v1',texture:'core',glowTexture:'glow'},props:{flower_a:{attachments:{nektar:{}}}}}};
const ctx=vm.createContext({render,TICK_HZ:20});const source=fs.readFileSync('web/host.js','utf8');
vm.runInContext(source.slice(source.indexOf('function meshNectarRecords('),source.indexOf('// Mesh nectar adapter end')),ctx);
const props=[{id:'flower:F',assetId:'flower_a'}];const result=ctx.meshNectarRecords(snapshot,props);
assert.strictEqual(result[0].width,1.661960244178772);
assert.strictEqual(result[0].angleRadians,.6283186674118042);
assert.strictEqual(JSON.stringify(ctx.meshNectarRecords({...snapshot,tick:1000},props)),JSON.stringify(result));
assert.throws(()=>ctx.meshNectarRecords({...snapshot,nectarEntities:undefined},props));
assert.throws(()=>ctx.meshNectarRecords({...snapshot,nectarEntities:[]},props));
"""
        result = subprocess.run(['node', '-e', code], input=json.dumps(packet),
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_next_flower_cycle_creates_new_age_without_restarting_old_identity(self):
        sim = make_ready_sim(world_with([('F', (110, 0, 0))]))
        old = sim.nectar_entities[sim.flowers[0].nectar_id]
        sim.buy(0, 'ant', 0)
        sim.run(64)
        self.assertTrue(old.delete_requested)
        sim.run(2)
        self.assertTrue(old.destroyed)
        old_visual = (old.size, old.core_angle, old.glow_angle)
        for _ in range(1000):
            sim.step()
            if len(sim.nectar_entities) > 1:
                break
        self.assertGreater(len(sim.nectar_entities), 1)
        new = list(sim.nectar_entities.values())[-1]
        self.assertNotEqual(new.entity_id, old.entity_id)
        self.assertEqual(new.born_tick, sim.tick)
        self.assertLess(new.size, old.size)
        self.assertNotEqual(new.core_angle, old.core_angle)
        self.assertEqual((old.size, old.core_angle, old.glow_angle), old_visual)

    def test_lifecycle_future_fields_are_distinguishable_in_state_hash(self):
        sim = make_ready_sim(world_with([('F', (110, 0, 0))]))
        entity = next(iter(sim.nectar_entities.values()))
        for field, value in (('target_size', 6), ('core_angle', .1), ('glow_angle', -.1),
                             ('rng_state', 999), ('flight_elapsed', .1),
                             ('flight_duration', 2), ('flight_start', (1, 2, 3)),
                             ('flight_target', (4, 5, 6)), ('waypoint', 'W'),
                             ('carrier_id', 1), ('alive', False)):
            with self.subTest(field=field):
                before = sim.state_hash()
                original = getattr(entity, field)
                setattr(entity, field, value)
                self.assertNotEqual(sim.state_hash(), before)
                setattr(entity, field, original)
                self.assertEqual(sim.state_hash(), before)
        before = sim.state_hash()
        sim.nectar_clock.accumulator = .001
        self.assertNotEqual(sim.state_hash(), before)
