"""Original pending-member stages and live names through real Sim seams."""
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from test_sim_gather import make_sim,make_ready_sim,world_with,advance_bridge
from bugbits.web_bridge import WebBridge
from bugbits.sim.entities import NectarItem
from bugbits.sim.nectar import NectarState


class NectarMembershipTests(unittest.TestCase):
    def test_actual_deposit_defers_membership_exit_and_pending_fields_still_update(self):
        sim=make_ready_sim(world_with([('F',(110,0,0))]))
        nectar=sim.nectar_entities[sim.flowers[0].nectar_id]
        bug=sim.buy(0,'ant',0);sim.run(32)
        self.assertTrue(bug.carrying)
        sim._deposit(bug)
        self.assertTrue(nectar.alive,'requesting deletion is not physical destruction')
        self.assertTrue(nectar.classification_member)
        self.assertTrue(nectar.delete_requested)
        self.assertFalse(nectar.delete_ready)
        before=nectar.core_angle
        sim._nectar_step()
        self.assertTrue(nectar.delete_ready)
        self.assertTrue(nectar.classification_member)
        self.assertGreater(nectar.core_angle,before)
        before=nectar.snapshot()
        sim._nectar_step()
        self.assertFalse(nectar.alive)
        self.assertFalse(nectar.classification_member)
        self.assertTrue(nectar.destroyed)
        self.assertEqual(nectar.core_angle,before['coreAngle'])

    def test_pending_member_counts_at_40_until_eligible_outer_removal(self):
        sim=make_ready_sim(world_with([('F',(110,0,0))]))
        others=[sim._new_nectar((1000,0,0)) for _ in range(39)]
        others[-1].request_delete()
        flower=sim.flowers[0]
        # Isolate a restart boundary after the existing track has finished;
        # make_ready_sim stops at birth, while that first track still plays.
        flower.cycle.playing=False
        flower.cycle.phase=flower.cycle.previous_phase=flower.cycle.duration
        flower.cycle.timer=flower.cycle.threshold+.1
        sim._nectar_step()
        self.assertFalse(flower.cycle.playing)
        self.assertEqual(sim.nectar_member_count(),40)
        sim._nectar_step()
        self.assertEqual(sim.nectar_member_count(),39)
        self.assertTrue(flower.cycle.playing)

    def test_pending_ground_nectar_cannot_be_picked_up_but_remains_a_member(self):
        for kind in ('flower','item'):
            with self.subTest(kind=kind):
                sim=make_ready_sim(world_with([('F',(44,0,0))])) if kind=='flower' else make_sim(world_with([]))
                if kind=='item':
                    sim.path_nectar.append(NectarItem(0,(44,0,0)))
                    sim._sync_nectar_entities()
                nectar=next(iter(sim.nectar_entities.values()))
                self.assertEqual(len(sim._available_nectar()),1)
                nectar.request_delete()
                bug=sim.buy(0,'ant',0)
                self.assertFalse(sim._pickup_check(bug))
                self.assertEqual(bug.carrying,0)
                self.assertEqual(sim.nectar_member_count(),1)
                self.assertTrue(nectar.alive)

    def test_zero_arg2_preserves_pending_flight_without_arming_removal(self):
        nectar=NectarState(1,(0,0,0),0)
        nectar.start_flight((100,2.5,0),waypoint='W')
        nectar.request_delete()
        nectar.update(1)
        nectar.finish_update(0)
        self.assertEqual(nectar.pos,(50,51.25,0))
        self.assertEqual(nectar.flight_elapsed,1)
        self.assertGreater(nectar.size,0)
        self.assertTrue(nectar.classification_member)
        self.assertFalse(nectar.delete_ready)
        nectar.finish_update(.05)
        self.assertTrue(nectar.delete_ready)

    def test_pending_attached_member_still_receives_flower_cached_position(self):
        sim=make_ready_sim(world_with([('F',(44,0,0))]))
        flower=sim.flowers[0];nectar=sim.nectar_entities[flower.nectar_id]
        nectar.pos=(0,0,0)
        flower.cached_point=(44,1,2)
        nectar.request_delete()
        sim._nectar_step()
        self.assertEqual(nectar.pos,(44,1,2))
        self.assertTrue(nectar.classification_member)

    def test_disabled_sweep_keeps_ready_member_updating_until_reenabled(self):
        sim=make_sim(world_with([]))
        nectar=sim._new_nectar((1000,0,0));nectar.request_delete()
        sim.nectar_sweep_enabled=False
        sim._nectar_step()
        self.assertTrue(nectar.delete_ready)
        before=nectar.core_angle
        sim._nectar_step()
        self.assertTrue(nectar.classification_member)
        self.assertGreater(nectar.core_angle,before)
        sim.nectar_sweep_enabled=True
        sim._nectar_step()
        self.assertTrue(nectar.destroyed)

    def test_adjacent_ready_members_preserve_original_left_shift_skip(self):
        sim=make_sim(world_with([]))
        entries=[sim._new_nectar((1000,0,0)) for _ in range(3)]
        for entry in entries:entry.request_delete()
        sim._nectar_step()
        self.assertEqual(sim.nectar_member_count(),3)
        sim._nectar_step()
        self.assertEqual([n.classification_member for n in entries],[False,True,False])
        self.assertEqual(sim.nectar_member_count(),1)
        sim._nectar_step()
        self.assertEqual(sim.nectar_member_count(),0)
        replacement=sim._new_nectar((1000,0,0))
        self.assertEqual(replacement.instance_name,'nectar')
        self.assertGreater(replacement.entity_id,entries[-1].entity_id)

    def test_actual_live_insertion_before_current_flower_repeats_that_flower(self):
        sim=make_sim(world_with([('zflower',(110,0,0)),('Aflower',(210,0,0))]))
        for flower in sim.flowers:
            flower.cycle.phase=flower.cycle.edge
            flower.cycle.previous_phase=flower.cycle.edge-.1
            flower.cycle.playing=True
        sim._nectar_step()
        self.assertEqual([e[2][1] for e in sim.events if e[1]=='nectar_spawn'],[1,0])
        a=sim.nectar_entities[sim.flowers[1].nectar_id]
        z=sim.nectar_entities[sim.flowers[0].nectar_id]
        self.assertGreater(a.core_angle,z.core_angle)
        self.assertGreater(sim.flowers[0].cycle.phase,sim.flowers[1].cycle.phase)

    def test_lifecycle_scene_and_sweep_state_are_hashed_and_bridge_reset_owned(self):
        sim=make_ready_sim(world_with([('F',(110,0,0))]))
        nectar=next(iter(sim.nectar_entities.values()))
        for field,value in (('classification_member',False),('delete_requested',True),
                            ('delete_ready',True),('destroyed',True),('instance_name','nectar09')):
            with self.subTest(field=field):
                before=sim.state_hash();old=getattr(nectar,field);setattr(nectar,field,value)
                self.assertNotEqual(sim.state_hash(),before);setattr(nectar,field,old)
                self.assertEqual(sim.state_hash(),before)
        before=sim.state_hash();sim.nectar_sweep_enabled=False
        self.assertNotEqual(sim.state_hash(),before)
        template=make_sim(world_with([('F',(110,0,0))]));bridge=WebBridge()
        bridge.from_objects(template.level,template.world,template.units,42,{'buyable':['ant']})
        advance_bridge(bridge,370)
        snapshot=bridge.snapshot()
        self.assertEqual(snapshot['nectarLifecycle']['countScope'],'nectar-classification-members-v1')
        self.assertEqual(snapshot['nectarLifecycle']['memberCount'],1)
        self.assertEqual(snapshot['nectarLifecycle']['scene']['scope'],'engineering-flower-nectar-live-subset-v1')
        self.assertEqual(snapshot['nectarLifecycle']['scene']['containerScope'],'bounded-original-name-live-container-v1')
        snapshot['nectarEntities'][0]['lifecycle']['deleteRequested']=True
        self.assertFalse(bridge.snapshot()['nectarEntities'][0]['lifecycle']['deleteRequested'])
        snapshot['nectarLifecycle']['scene']['children'].clear()
        self.assertTrue(bridge.snapshot()['nectarLifecycle']['scene']['children'])
        bridge.dispose();bridge.from_objects(template.level,template.world,template.units,42,{'buyable':['ant']})
        self.assertEqual(bridge.snapshot()['nectarLifecycle']['memberCount'],0)


if __name__=='__main__':unittest.main()
