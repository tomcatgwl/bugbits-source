"""Finite ceNectar slot20 contracts, distinct from native scheduling acceptance."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from bugbits.sim.nectar import NectarState
from test_sim_gather import make_ready_sim, world_with


class NectarPositionTests(unittest.TestCase):
    def test_setter_copies_both_endpoints_without_resetting_clocks_or_identity(self):
        # Original 49BAA0 has four groups of three f32 writes, no clock writes.
        entity = NectarState(7,(0,0,0),born_tick=9,carrier_id=3)
        entity.start_flight((100,2.5,0),waypoint='W')
        entity.update(.5)
        retained = (entity.entity_id,entity.born_tick,entity.carrier_id,entity.waypoint,
                    entity.size,entity.core_angle,entity.glow_angle,
                    entity.flight_elapsed,entity.flight_duration)
        entity.set_position((.1,-.2,.3))
        expected = (.10000000149011612,-.20000000298023224,.30000001192092896)
        self.assertEqual(entity.pos,expected)
        self.assertEqual(entity.flight_start,expected)
        self.assertEqual(entity.flight_target,expected)
        self.assertEqual((entity.entity_id,entity.born_tick,entity.carrier_id,entity.waypoint,
                          entity.size,entity.core_angle,entity.glow_angle,
                          entity.flight_elapsed,entity.flight_duration),retained)

    def test_equal_new_endpoints_preserve_remaining_flight_arc(self):
        entity = NectarState(1,(0,0,0),born_tick=0)
        entity.start_flight((100,2.5,0),waypoint='W')
        entity.update(.5)
        entity.set_position((-7,11,13))
        entity.update(.5)
        # t=.5, arc=200*.5*.5=50; no old target interpolation survives.
        self.assertEqual(entity.pos,(-7,61,13))
        self.assertEqual(entity.flight_elapsed,1)
        self.assertEqual(entity.flight_duration,2)
        self.assertEqual(entity.waypoint,'W')

    def test_position_assignment_does_not_start_an_inactive_flight(self):
        entity = NectarState(1,(0,0,0),born_tick=0)
        entity.set_position((17.25,-29.5,6.125))
        entity.update(.01)
        self.assertEqual(entity.pos,(17.25,-29.5,6.125))
        self.assertEqual(entity.flight_start,entity.pos)
        self.assertEqual(entity.flight_target,entity.pos)
        self.assertEqual(entity.flight_elapsed,0)
        self.assertEqual(entity.flight_duration,0)

    def test_flower_follow_uses_setter_while_flight_clock_remains_active(self):
        sim = make_ready_sim(world_with([('F',(110,0,0))]))
        flower = sim.flowers[0]
        entity = sim.nectar_entities[flower.nectar_id]
        entity.start_flight((1000,2.5,0),waypoint='W')
        # A legal local marker prevents contact without unregistering/follow.
        entity.request_delete()
        cached = flower.cached_point
        sim._nectar_step()
        self.assertEqual(entity.flight_start,cached)
        self.assertEqual(entity.flight_target,cached)
        self.assertGreater(entity.flight_elapsed,0)
        self.assertEqual(entity.flight_duration,2)
        self.assertTrue(entity.classification_member)

    def test_carry_does_not_skip_setter_for_an_active_flight(self):
        sim = make_ready_sim(world_with([('F',(110,0,0))]))
        entity = sim.nectar_entities[sim.flowers[0].nectar_id]
        bug = sim.buy(0,'ant',0)
        sim.run(32)
        self.assertTrue(bug.carrying)
        self.assertEqual(bug.carried_nectar_id,entity.entity_id)
        sim.run(11)
        self.assertTrue(bug.carrying)
        self.assertGreater(sim.tick-bug.carry_pickup_tick,10)
        # Static integration fixture isolates the original local carry gate;
        # it does not claim this artificial active-flight state is a native frame.
        bug.mode='idle'
        bug.cur_pos=(8,9,10)
        entity.start_flight((1000,2.5,0),waypoint='W')
        age = (entity.size,entity.core_angle,entity.glow_angle)
        sim.step()
        self.assertEqual(entity.pos,(8,14,10))  # ant Radius=5, carry weight=1.
        self.assertEqual(entity.flight_start,(8,14,10))
        self.assertEqual(entity.flight_target,(8,14,10))
        self.assertGreater(entity.flight_elapsed,0)
        self.assertEqual(entity.flight_duration,2)
        self.assertEqual(entity.carrier_id,bug.bug_id)
        self.assertNotEqual((entity.size,entity.core_angle,entity.glow_angle),age)


if __name__=='__main__':
    unittest.main()
