"""R368 independent original boundaries, plus public Sim integration."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bugbits.sim.flower import FlowerCycle, FlowerRandom
from bugbits.sim.nectar import f32
from test_sim_gather import make_sim, world_with


class FlowerCycleTests(unittest.TestCase):
    def test_initial_animation_stays_stopped_until_timer_restart(self):
        rng = FlowerRandom(42)
        flower = FlowerCycle.initial(1, rng)
        self.assertEqual(rng.state, 2900899)
        # Independent rational: 15 + (15*2900899)/2**32, rounded to IEEE f32.
        self.assertEqual(flower.timer, 15.010130882263184)
        self.assertFalse(flower.playing)
        for _ in range(68):
            self.assertFalse(flower.update(.05, occupied=False, nectar_count=0, rng=rng))
        self.assertEqual(flower.phase, 0)
        self.assertEqual(flower.previous_phase, 0)
        self.assertEqual(rng.state, 2900899)

    def test_timer_strict_boundary_and_parent_edge_precedes_child_advance(self):
        rng = FlowerRandom(0)
        flower = FlowerCycle.initial(1, rng)
        flower.timer = 29.5
        self.assertFalse(flower.update(.5, occupied=False, nectar_count=0, rng=rng))
        self.assertFalse(flower.playing)
        self.assertEqual(flower.timer, 30)
        self.assertFalse(flower.update(.5, occupied=False, nectar_count=0, rng=rng))
        self.assertTrue(flower.playing)
        self.assertEqual(flower.phase, .5)
        self.assertEqual(flower.previous_phase, 0)
        flower.phase, flower.previous_phase = f32(3.3), 3.25
        self.assertTrue(flower.update(.05, occupied=False, nectar_count=0, rng=rng))
        self.assertEqual(flower.previous_phase, f32(3.3))
        self.assertFalse(flower.update(.05, occupied=False, nectar_count=0, rng=rng))

    def test_finite_track_keeps_overshoot_and_stops_strictly_after_last_key(self):
        rng = FlowerRandom(0)
        flower = FlowerCycle.initial(1, rng)
        flower.playing = True
        flower.phase = flower.duration
        flower.previous_phase = flower.phase
        self.assertFalse(flower.update(0, occupied=False, nectar_count=0, rng=rng))
        self.assertTrue(flower.playing)
        flower.update(.1, occupied=False, nectar_count=0, rng=rng)
        self.assertFalse(flower.playing)
        self.assertGreater(flower.phase, flower.duration)
        stopped = flower.phase
        flower.update(.1, occupied=False, nectar_count=0, rng=rng)
        self.assertEqual(flower.phase, stopped)
        self.assertEqual(flower.completions, 1)

    def test_restart_gates_do_not_become_a_global_spawn_cap(self):
        for kind, occupied, count, allowed in ((1, False, 40, True),
                                              (1, True, 39, True),
                                              (1, True, 40, False),
                                              (2, True, 0, False)):
            with self.subTest(kind=kind, occupied=occupied, count=count):
                rng = FlowerRandom(42)
                flower = FlowerCycle.initial(kind, rng)
                flower.timer = flower.threshold
                before = rng.state
                flower.update(.05, occupied=occupied, nectar_count=count, rng=rng)
                self.assertEqual(flower.playing, allowed)
                self.assertEqual(rng.state == before, not allowed)
        rng = FlowerRandom(42)
        flower = FlowerCycle.initial(1, rng)
        flower.phase, flower.previous_phase = f32(3.3), 3.25
        self.assertTrue(flower.update(.05, occupied=True, nectar_count=40, rng=rng))

    def test_zero_arg2_and_inhibited_level_cache_behavior(self):
        rng = FlowerRandom(42)
        flower = FlowerCycle.initial(1, rng)
        flower.phase, flower.previous_phase, flower.playing = f32(3.3), 3.25, True
        before = flower.snapshot()
        self.assertFalse(flower.update(0, occupied=False, nectar_count=0, rng=rng))
        self.assertEqual(flower.snapshot(), before)
        for gate in ({'rescue': True}, {'level_present': False}, {'inhibited': True}):
            flower.phase, flower.previous_phase = f32(3.3), 3.25
            timer = flower.timer
            self.assertFalse(flower.update(.05, occupied=False, nectar_count=0, rng=rng, **gate))
            self.assertEqual(flower.timer, timer)
            self.assertEqual(flower.previous_phase, f32(3.3))
            self.assertGreater(flower.phase, f32(3.3))

    def test_original_types_and_multiplayer_thresholds(self):
        for kind, threshold, duration in ((1, 30, 4.333333492279053),
                                           (2, 15, 4.599999904632568),
                                           (3, 15, 3.933333396911621)):
            flower = FlowerCycle.initial(kind, FlowerRandom(42), multiplayer=True)
            self.assertEqual(flower.threshold, threshold / 2)
            self.assertEqual(flower.duration, duration)
        unknown = FlowerCycle.initial(0, FlowerRandom(42))
        self.assertEqual(unknown.threshold, 30)
        unknown.timer = 30
        self.assertFalse(unknown.update(20, occupied=False, nectar_count=0, rng=FlowerRandom(0)))
        self.assertFalse(unknown.has_nectar_node)


class FlowerIntegrationTests(unittest.TestCase):
    def test_buy_on_empty_world_then_natural_birth_pickup_and_deposit(self):
        sim = make_sim(world_with([('F', (110, 0, 0))]))
        bug = sim.buy(0, 'ant', 0)
        self.assertIsNotNone(bug)
        self.assertEqual(sim.nectar_entities, {})
        sim.run(366)
        self.assertFalse(any(e[1] == 'nectar_pickup' for e in sim.events))
        sim.run(100)
        spawns = [e for e in sim.events if e[1] == 'nectar_spawn']
        pickups = [e for e in sim.events if e[1] == 'nectar_pickup']
        deposits = [e for e in sim.events if e[1] == 'deposit']
        self.assertEqual(len(spawns), 1)
        self.assertEqual(len(pickups), 1)
        self.assertEqual(len(deposits), 1)
        self.assertGreater(pickups[0][0], spawns[0][0])
        self.assertGreater(deposits[0][0], pickups[0][0])
        self.assertEqual(sim.nectar[0], 13)
        self.assertFalse(sim.nectar_entities[spawns[0][2][0]].alive)
        self.assertIsNone(bug.carried_nectar_id)

    def test_other_normal_types_generate_from_their_own_timer_and_edge(self):
        for kind, deadline in ((2, 220), (3, 210)):
            world = world_with([('F', (110, 0, 0))])
            world.flowers[0].flower_type = kind
            sim = make_sim(world)
            sim.run(140)  # Seven seconds: initial timer has not crossed T=15.
            self.assertEqual(sim.nectar_entities, {})
            self.assertFalse(sim.flowers[0].cycle.playing)
            sim.run(deadline - 140)
            self.assertEqual(sim.flowers[0].nectar, 1)
            self.assertEqual(len(sim.nectar_entities), 1)

    def test_natural_first_birth_is_delayed_and_not_eager_or_phase_seconds(self):
        sim = make_sim(world_with([('F', (110, 0, 0))]))
        self.assertEqual(sim.flowers[0].nectar, 0)
        self.assertEqual(sim.nectar_entities, {})
        sim.run(68)
        self.assertEqual(sim.nectar_entities, {})
        sim.run(300)
        self.assertEqual(sim.flowers[0].nectar, 1)
        self.assertEqual(len(sim.nectar_entities), 1)
        self.assertEqual([e[0] for e in sim.events if e[1] == 'nectar_spawn'], [367])

    def test_occupied_birth_redirects_new_identity_and_preserves_old_slot(self):
        sim = make_sim(world_with([('F', (110, 0, 0))]))
        sim.run(368)
        flower = sim.flowers[0]
        old_id = flower.nectar_id
        old = sim.nectar_entities[old_id]
        flower.cycle.phase, flower.cycle.previous_phase = f32(3.3), 3.25
        sim.step()
        self.assertEqual(flower.nectar_id, old_id)
        self.assertEqual(flower.nectar, 1)
        self.assertIs(sim.nectar_entities[old_id], old)
        self.assertEqual(len(sim.path_nectar), 1)
        new = sim.nectar_entities[sim.path_nectar[0].nectar_id]
        self.assertNotEqual(new.entity_id, old_id)
        self.assertIsNone(new.flower_index)
        self.assertEqual(new.flight_duration, 2)
        self.assertEqual(new.born_tick, sim.tick)
        self.assertLess(new.size, old.size)

    def test_missing_node_does_not_allocate_and_new_fields_affect_hash(self):
        sim = make_sim(world_with([('F', (110, 0, 0))]))
        cycle = sim.flowers[0].cycle
        cycle.has_nectar_node = False
        cycle.phase, cycle.previous_phase = f32(3.3), 3.25
        sim.step()
        self.assertEqual(sim.nectar_entities, {})
        for field, value in (('timer', 1), ('threshold', 31), ('phase', 1),
                             ('previous_phase', 1), ('playing', True),
                             ('duration', 5), ('completions', 1),
                             ('has_nectar_node', True)):
            before = sim.state_hash()
            saved = getattr(cycle, field)
            setattr(cycle, field, value)
            self.assertNotEqual(before, sim.state_hash(), field)
            setattr(cycle, field, saved)
        before = sim.state_hash()
        sim.flower_random.state += 1
        self.assertNotEqual(before, sim.state_hash())


if __name__ == '__main__':
    unittest.main()
