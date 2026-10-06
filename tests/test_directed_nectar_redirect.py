"""Public real pickup/combat death consumes original ordered nectar graph inputs."""
import unittest
from pathlib import Path
import tempfile

from bugbits import level, sim, unitdb, worlddb, web_data
from bugbits.assets import data_dir
from bugbits.sim.entities import NectarItem


def directed_world():
    # Original valid ConnectTo A->W->E; order is deliberately unrelated to names.
    starts = [worlddb.Start('E',(3,0,0),(0,0,1),1,0,[]),
              worlddb.Start('A',(0,0,0),(0,0,1),0,0,['W'])]
    nodes = [worlddb.Waypoint('W',(200,0,0),(0,0,1),False,['E'])]
    return worlddb.WorldData({},[],[],None,starts,nodes,2,
                            {'A':{'W'},'W':{'A','E'},'E':{'W'}})


def pickup_then_combat_death(seed, *, water_waypoint=False):
    lv = level.LevelData({'InitialNectar':['10'],'NectarOnPaths':['0'],
                         'PlayerBaseSize':['10'],'EnemyBaseSize':['3']})
    units = {n:unitdb.load_unit(n) for n in ('ant','littlebeetle')}
    world = directed_world()
    world.waypoints[0].water = water_waypoint
    game = sim.Sim(lv,world,units,seed)
    # Controlled already available resource; normal step owns its identity.
    game.path_nectar.append(NectarItem(0,(0,0,0)))
    carrier = game.buy(0,'ant',0)
    game.run(2)  # R390 state1 transition then target-null selection/pickup.
    if not carrier.carrying:
        raise AssertionError('public pickup precondition not reached')
    identity = carrier.carried_nectar_id
    game.spawn_free(1,'littlebeetle',0)
    for _ in range(150):
        game.step()
        if carrier.dead:
            return game, carrier, identity, game.nectar_entities[identity]
    raise AssertionError('real combat did not trigger carried-nectar death')


class DirectedNectarRedirect(unittest.TestCase):
    def test_water_waypoint_leaves_start_in_redirect_candidate_population(self):
        _, _, _, nectar = pickup_then_combat_death(6,water_waypoint=True)
        # W is disqualified, while distance gate relaxes below budget500.
        # Sorted A/E/W qualified countdown3 selects A; its water neighbor W
        # retains A's own position without consuming an interpolation draw.
        self.assertEqual(nectar.waypoint,'A')
        self.assertEqual(nectar.rng_state,3328985325)
        self.assertEqual(nectar.flight_target,(0.,2.5,0.))
        self.assertEqual(nectar.flight_duration,2.)

    def test_seed8_consumes_incoming_without_merging_outgoing(self):
        _, _, _, nectar = pickup_then_combat_death(8)
        self.assertEqual(nectar.rng_state,4216772212)
        self.assertEqual(nectar.waypoint,'A')
        self.assertAlmostEqual(nectar.flight_target[0],3.6412423476576805,delta=4e-5)

    def test_real_world_direction_survives_json_restore(self):
        raw = worlddb.parse_world(data_dir('worlds','world_01.vsc'))
        restored = web_data.restore_world(web_data.world_to_dict(raw))
        for world in (raw, restored):
            outgoing, incoming = world.directed_links()
            self.assertEqual(outgoing['path0_0'],('path0_1',))
            self.assertEqual(incoming['path0_0'],('StartLeft0',))
            self.assertEqual(outgoing['StartRight0'],())
            self.assertEqual(len(outgoing),74)
            self.assertEqual(sum(map(len,outgoing.values())),71)

    def test_links_are_deduplicated_unsigned_name_order_with_empty_incoming(self):
        world = directed_world()
        world.waypoints.extend([
            worlddb.Waypoint('a',(400,0,0),(0,0,1),False,[]),
            worlddb.Waypoint('Z',(400,0,0),(0,0,1),False,[])])
        world.waypoints[0].connect_to = ['a','Z','E','a','missing']
        outgoing, incoming = world.directed_links()
        self.assertEqual(outgoing['W'],('E','Z','a'))
        self.assertEqual(incoming['W'],('A',))
        self.assertEqual(incoming['A'],())

    def test_seed6_distinguishes_outgoing_from_merged_neighbor(self):
        game, carrier, identity, nectar = pickup_then_combat_death(6)
        # Original three-candidate/one-neighbor draws end at2908188362;
        # second quotient mod100=62 selects outgoing E, while mod2=0 would
        # select A in the old merged list. Seed0 alone masked this difference.
        self.assertEqual(nectar.rng_state,2908188362)
        self.assertEqual(nectar.waypoint,'E')
        self.assertAlmostEqual(nectar.flight_target[0],66.6082724663429,delta=4e-5)
        self.assertEqual(nectar.flight_target[1:],(2.5,0.))
        self.assertEqual(len(game.nectar_entities),1)
        self.assertEqual(game.path_nectar[0].nectar_id,identity)

        self.assertIn((game.tick,'nectar_release',(carrier.bug_id,'death')),game.events)

    def test_start_inherited_water_survives_parse_and_packet(self):
        # START typed property callback delegates Water to ceWayPoint; finite
        # negative nonzero is true in the original test AH44/JNP branch.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as directory:
            path = Path(directory)/'fixture.vsc'
            path.write_text('SpawnEntity A START\n> A\nsp Position 0 0 0\n'
                            'sp Direction 0 0 1\nsp SideID 0\nsp Index 0\nsp Water -1\n<\n')
            world = worlddb.parse_world(path)
            self.assertTrue(world.start(0,0).water)
            restored = web_data.restore_world(web_data.world_to_dict(world))
            self.assertTrue(restored.start(0,0).water)
    def test_combat_drop_consumes_outgoing_without_merging_incoming(self):
        game, carrier, identity, nectar = pickup_then_combat_death(0)
        self.assertEqual(len(game.nectar_entities),1)
        self.assertIsNone(nectar.carrier_id)
        self.assertEqual(nectar.rng_state,3277404108)
        self.assertEqual(nectar.waypoint,'E')
        # Original integer/segment worksheet R385: exact53336212481/2**30.
        # 4e-5 bounds intermediate f32 differences at <=200u; not x87 parity.
        self.assertAlmostEqual(nectar.flight_target[0],49.67321872804314,delta=4e-5)
        self.assertEqual(nectar.flight_target[1:],(2.5,0.))
        self.assertEqual(nectar.flight_duration,2.)
        self.assertIn((game.tick,'nectar_release',(carrier.bug_id,'death')),game.events)
        self.assertEqual(game.path_nectar[0].nectar_id,identity)


if __name__ == '__main__':
    unittest.main()
