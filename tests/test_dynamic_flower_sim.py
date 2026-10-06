"""Public cached flower placement; expected points use independent raw X keys."""
import copy
import hashlib
import json
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bugbits import web_data, worlddb
from bugbits.assets import data_dir
from bugbits.sim.nectar import f32
from bugbits.web_bridge import WebBridge
from test_sim_gather import make_sim,world_with,advance_bridge


def rig():
    identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
    duration=4.333333492279053
    value={'contract':'flower-node-keys-v1','assetId':'flower_a',
           'modelSource':'models/props/flower_a.v3d','modelSHA':'a'*64,
           'animationSource':'models/props/flower_a.van','animationSHA':'b'*64,
           'duration':duration,'nektarNode':1,'nodes':[
               {'name':'unused-root','parent':-1,'bind':identity,
                'keys':[[0,0,0,0,999,0,0],[duration,0,0,0,999,0,0]]},
               {'name':'nektar','parent':-1,'bind':identity,
                'keys':[[0,0,0,0,1,0,0],[duration,0,0,0,10,0,0]]}]}
    value['rigSHA256']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return value


def prepared_world():
    w=world_with([('F',(110,0,0))]);w.flower_rigs={'flower_a':rig()}
    return w


class DynamicFlowerSimTests(unittest.TestCase):
    def test_birth_reads_old_cache_and_only_outer_boundary_propagates_pose(self):
        s=make_sim(prepared_world());flower=s.flowers[0]
        flower.cycle.phase=f32(3.3);flower.cycle.previous_phase=3.25
        flower.cycle.playing=True
        s.step()
        entity=s.nectar_entities[flower.nectar_id]
        # Raw X=1 stays X through S; Q maps it to Yup Z, owner identity.
        self.assertEqual(entity.pos,(110,0,2.5))
        self.assertEqual(flower.pose_generation,1)
        self.assertEqual(flower.cached_phase,flower.cycle.phase)
        old_phase=flower.cached_phase
        self.assertNotEqual(flower.cached_point,entity.pos)
        s.step()
        expected=f32(2.5+22.5*old_phase/rig()['duration'])
        self.assertEqual(entity.pos,(110,0,expected))
        self.assertEqual(flower.pose_generation,2)
        self.assertNotEqual(flower.cached_point,entity.pos)

    def test_pickup_freezes_entity_point_and_pose_future_fields_change_hash(self):
        s=make_sim(prepared_world());flower=s.flowers[0]
        flower.nectar=1;s._sync_nectar_entities();s.buy(0,'ant',0);s.run(40)
        bug=s.bugs[0]
        self.assertTrue(bug.carrying)
        self.assertEqual(bug.carry_source_pos,(110,0,2.5))
        frozen=bug.carry_source_pos
        flower.cycle.phase=2;flower.cycle.playing=True;s.step()
        self.assertEqual(bug.carry_source_pos,frozen)
        for field,value in (('cached_phase',.125),('cached_point',(999,0,0)),('pose_generation',999)):
            with self.subTest(field=field):
                before=s.state_hash();old=getattr(flower,field);setattr(flower,field,value)
                self.assertNotEqual(s.state_hash(),before);setattr(flower,field,old)
                self.assertEqual(s.state_hash(),before)

    def test_world_packet_restores_rig_without_original_io_and_rejects_tampering(self):
        w=prepared_world();packet=web_data.world_to_dict(w)
        self.assertEqual(packet['flowerRigContract'],'flower-node-keys-v1')
        restored=web_data.restore_world(json.loads(json.dumps(packet)))
        self.assertEqual(restored.flower_rigs,w.flower_rigs)
        self.assertEqual(make_sim(restored).flowers[0].cached_point,(110,0,2.5))
        hashes={'models/props/flower_a.v3d':'a'*64,'models/props/flower_a.van':'b'*64}
        web_data.validate_world_rig_sources(restored,hashes)
        with self.assertRaises(ValueError):web_data.validate_world_rig_sources(restored,{})
        degraded=copy.deepcopy(packet)
        degraded.update(worldId='world_01',flowerRigs={},flowerRigContract=None)
        with self.assertRaises(ValueError):web_data.restore_world(degraded)
        packet['flowerRigs']['flower_a']['nodes'][1]['keys'][0][4]=9
        with self.assertRaises(ValueError):web_data.restore_world(packet)

    def test_real_world_has_normal_rigs_and_snapshot_reset_deep_copy(self):
        w=worlddb.parse_world(data_dir('worlds','world_01.vsc'))
        self.assertEqual(w.world_id,'world_01')
        self.assertEqual(set(w.flower_rigs),{'flower_a'})
        template=make_sim(prepared_world());bridge=WebBridge()
        bridge.from_objects(template.level,template.world,template.units,42,{'buyable':['ant']})
        old=bridge.snapshot();self.assertEqual(old['flowers'][0]['pose']['generation'],0)
        old['flowers'][0]['pose']['cachedPositionYup'][2]=999
        self.assertEqual(bridge.snapshot()['flowers'][0]['pose']['cachedPositionYup'][2],2.5)
        advance_bridge(bridge,3)
        self.assertEqual(bridge.audit_state()['flowers'][0]['pose']['generation'],3)
        bridge.dispose();bridge.from_objects(template.level,template.world,template.units,42,{'buyable':['ant']})
        self.assertEqual(bridge.snapshot()['flowers'][0]['pose']['generation'],0)


if __name__=='__main__':unittest.main()
