"""Original ordinary-ground route policy through public Sim gameplay."""
import unittest

from bugbits import level,sim,unitdb,worlddb


def fork_world():
    starts=[worlddb.Start('O',(0.,0.,0.),(0.,0.,1.),0,0,['W','D']),
            worlddb.Start('T',(20.,0.,0.),(0.,0.,1.),1,0,[])]
    nodes=[worlddb.Waypoint('W',(10.,0.,0.),(0.,0.,1.),True,['T']),
           worlddb.Waypoint('D',(0.,0.,100.),(0.,0.,1.),False,['T'])]
    return worlddb.WorldData({},[],[],None,starts,nodes,4,
        {'O':{'W','D'},'W':{'O','T'},'D':{'O','T'},'T':{'W','D'}})


def game_for(world):
    lv=level.LevelData({'InitialNectar':['10'],'NectarOnPaths':['0'],
                       'PlayerBaseSize':['100'],'EnemyBaseSize':['100']})
    return sim.Sim(lv,world,{'ant':unitdb.load_unit('ant')},2026)


class DirectedActorRoute(unittest.TestCase):
    def test_reverse_level_uses_incoming_after_start_side_application(self):
        world=fork_world();game=game_for(world)
        game.level.props['IsReversed']=['1']
        game=sim.Sim(game.level,world,game.units,2026)
        bug=game.buy(0,'ant',0)
        self.assertEqual(bug.spawn_pos,(20.,0.,0.))
        self.assertEqual(bug.route_current,'T')
        game.run(2)  # Native state1 transition, then target-null selection.
        self.assertEqual(bug.route_target,'D')
        game.run(2)
        self.assertGreater(bug.pos(game)[2],0.)
        self.assertEqual(world.start(0,0).name,'O')

    def test_route_flag_changes_hash_and_bridge_reset_publishes_fresh_fields(self):
        from bugbits import web_data
        from bugbits.web_bridge import WebBridge
        game=game_for(fork_world());bug=game.buy(0,'ant',0)
        before=game.state_hash();bug.route_returning=True
        self.assertNotEqual(game.state_hash(),before)
        raw_world=fork_world();units={'ant':unitdb.load_unit('ant')}
        ld=web_data.level_to_dict(game.level);wd=web_data.world_to_dict(raw_world)
        ud={'ant':web_data.unit_to_dict(units['ant'])}
        options={'buyable':['ant']}
        bridge=WebBridge();opened=bridge.init('fixture',2026,ld,wd,ud,options)
        ack=bridge.submit({'type':'buy','commandId':'route-buy','sessionId':opened['sessionId'],
                       'unit':'ant','lane':0})
        self.assertTrue(ack['queued'],ack)
        bridge.advance(3)  # Buy is after step; two mover calls follow birth.
        route=bridge.snapshot()['bugs'][0]['route']
        audit=bridge.audit_state()['bugs'][0]
        self.assertEqual(route['current'],'O')
        self.assertEqual(route['target'],'D')
        self.assertFalse(route['returning'])
        self.assertEqual(audit['routeCurrent'],route['current'])
        self.assertEqual(audit['routeTarget'],route['target'])
        self.assertEqual(audit['routeReturning'],route['returning'])
        bridge.reset('fixture',2026,ld,wd,ud,options)
        self.assertEqual(bridge.snapshot()['bugs'],[])

    def test_pickup_changes_logical_current_without_teleporting_physical_point(self):
        from bugbits.sim.entities import NectarItem
        world=fork_world();world.starts[0].connect_to=['W'];world.waypoints[0].water=False
        game=game_for(world);game.path_nectar.append(NectarItem(0,(0.,0.,0.)))
        bug=game.buy(0,'ant',0);game.run(2)
        self.assertEqual(bug.route_current,'W')
        self.assertEqual(bug.route_target,'O')
        self.assertTrue(bug.route_returning)
        self.assertEqual(bug.carrying,1)
        # Selection still uses constructor cap0. Pickup changes CC, not P.
        self.assertEqual(bug.pos(game)[0],0.)
        self.assertEqual(bug.pos(game)[2],0.)
        game.step()
        self.assertTrue(bug.route_returning)
        self.assertIsNone(bug.route_target)  # Arrival clears D0, no deposit yet.
        game.step()  # Next target-null controller call deposits.
        self.assertFalse(bug.route_returning)
        self.assertEqual(bug.carrying,0)
        self.assertEqual(game.nectar[0],13)

    def test_same_side_candidate_penalty_and_pending_nectar_membership(self):
        from bugbits.sim.nectar import NectarState
        world=fork_world();world.waypoints[0].water=False
        game=game_for(world)
        game.bugs.append(sim.Bug(100,0,'ant',22,False,True,15,(10000.,0.,0.),route_current='D'))
        # -1/denom atD, W0 =>W. Pending original classification remains
        # a member and +3F4=D adds10/denom, despite its far physical point.
        nectar=NectarState(1,(10000.,0.,0.),born_tick=0,waypoint='D')
        nectar.request_delete()
        game.nectar_entities[1]=nectar
        bug=game.buy(0,'ant',0)
        game.run(2)
        self.assertEqual(bug.route_target,'D')

    def test_equal_score_preserves_unsigned_name_order_instead_of_distance(self):
        world=fork_world();world.waypoints[0].water=False
        game=game_for(world);bug=game.buy(0,'ant',0)
        game.run(2)
        self.assertEqual(bug.route_target,'D')  # D sorts beforeW; both0.

    def test_named_bugs_enemy_at_candidate_contributes_without_spatial_filter(self):
        world=fork_world();world.waypoints[0].water=False
        game=game_for(world)
        peer=sim.Bug(100,1,'ant',22,False,True,15,(10000.,0.,0.),route_current='W')
        game.bugs.append(peer)  # Controlled valid group/CC input, not spawn proof.
        bug=game.buy(0,'ant',0)
        game.run(2)
        # Original2/(0.2*1+1) atW, D0; no distance gate in score loop.
        self.assertEqual(bug.route_target,'W')

    def test_current_zero_outgoing_does_not_take_incoming_or_set_return_flag(self):
        starts=[worlddb.Start('A',(0.,0.,0.),(0.,0.,1.),0,0,[]),
                worlddb.Start('E',(200.,0.,0.),(0.,0.,1.),1,0,['B'])]
        nodes=[worlddb.Waypoint('B',(100.,0.,0.),(0.,0.,1.),False,['A'])]
        world=worlddb.WorldData({},[],[],None,starts,nodes,2,
              {'A':{'B'},'B':{'A','E'},'E':{'B'}})
        game=game_for(world);bug=game.buy(0,'ant',0)
        game.run(4)
        self.assertEqual(bug.pos(game),(0.,0.,0.))
        self.assertIsNone(bug.route_target)
        self.assertFalse(bug.route_returning)

    def test_empty_gatherer_turns_before_terminal_target_without_becoming_a_carrier(self):
        starts=[worlddb.Start('A',(0.,0.,0.),(1.,0.,0.),0,0,['B']),
                worlddb.Start('E',(200.,0.,0.),(0.,0.,1.),1,0,[])]
        nodes=[worlddb.Waypoint('B',(20.,0.,0.),(1.,0.,0.),False,['E'])]
        world=worlddb.WorldData({},[],[],None,starts,nodes,2,
              {'A':{'B'},'B':{'A','E'},'E':{'B'}})
        game=game_for(world);bug=game.buy(0,'ant',0)
        game.run(4)  # Independent R389/R390: strict<20 and old-V integration.
        self.assertAlmostEqual(bug.pos(game)[0],.28025,places=6)
        self.assertEqual(bug.route_current,'B')
        self.assertIsNone(bug.route_target)
        game.step()  # Terminal selection/return occurs on the next call.
        self.assertTrue(bug.route_returning)
        self.assertEqual(bug.carrying,0)
        self.assertEqual(bug.route_target,'A')
        game.step()
        self.assertLess(bug.pos(game)[0],20.)

    def test_ordinary_ant_selects_dry_local_branch_instead_of_short_water_path(self):
        game=game_for(fork_world())
        bug=game.buy(0,'ant',0)
        self.assertIsNotNone(bug)
        game.run(2)
        # Original normal fork score, no Bugs/Nectars contribution: dry0,
        # water-500. Strictmax selectsD regardless the much shorter W route.
        self.assertEqual(bug.path_nodes[1],'D')
        game.run(2)
        self.assertEqual(bug.pos(game)[0],0.)
        self.assertGreater(bug.pos(game)[2],0.)


if __name__=='__main__':unittest.main()
