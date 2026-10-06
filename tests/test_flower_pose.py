import copy
import hashlib
import json
import math
import unittest
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch
from bugbits.assets.flower_pose import (CONTRACT, validate_rig, worlds_at,
    attachment_at, world_attachment, owner_matrix, load_normal_rig)

I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
def seal(r):
    r.pop('rigSHA256',None)
    r['rigSHA256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return r

def fixture():
    return seal(dict(contract=CONTRACT,assetId='fixture',modelSource='fixture.v3d',modelSHA='a'*64,
        animationSource='fixture.van',animationSHA='b'*64,duration=1.,nektarNode=0,
        nodes=[dict(name='nektar',parent=2,bind=I,keys=[[0,0,0,0,1,0,0],[1,0,0,0,3,0,0]]),
               dict(name='other',parent=-1,bind=I,keys=[[0,0,0,0,90,0,0],[1,0,0,0,90,0,0]]),
               dict(name='parent',parent=-1,bind=I,keys=[[0,0,0,math.pi/2,0,2,0],[1,0,0,math.pi/2,0,2,0]])]))

class FlowerPoseTests(unittest.TestCase):
    def test_parent_after_child_and_second_root(self):
        r=fixture();validate_rig(r)
        self.assertAlmostEqual(attachment_at(r,.5)[0],0,places=12)
        self.assertAlmostEqual(attachment_at(r,.5)[1],4)
        self.assertEqual(worlds_at(r,0)[1][12],90)
        self.assertEqual(attachment_at(r,10),attachment_at(r,1))

    def test_reject_contract_and_graph(self):
        for mutate in [lambda r:r['nodes'][2].update(parent=0),
                       lambda r:r['nodes'][0].update(parent=7),
                       lambda r:r['nodes'][1].update(name='nektar'),
                       lambda r:r['nodes'][0]['keys'][1].__setitem__(0,0),
                       lambda r:r['nodes'][0]['bind'].__setitem__(3,1),
                       lambda r:r['nodes'][0]['keys'][0].__setitem__(0,.1),
                       lambda r:r['nodes'][0]['keys'][1].__setitem__(0,.9),
                       lambda r:r['nodes'][0].update(keys=[]),
                       lambda r:r.update(nektarNode=1),
                       lambda r:r.update(modelSHA='bad')]:
            r=copy.deepcopy(fixture());mutate(r);seal(r)
            with self.assertRaises(ValueError):validate_rig(r)
        r=fixture();r['duration']=2
        with self.assertRaises(ValueError):validate_rig(r)
        for t in [-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):attachment_at(fixture(),t)

    def test_owner_and_world_axes(self):
        from bugbits.web_geometry import flower_owner_matrix
        for d in [(1,2,3),(0,1,0),(0,0,1)]:
            self.assertEqual(owner_matrix(d),flower_owner_matrix(d))
        m=owner_matrix((0,0,1),observed=True)
        self.assertEqual(len(m),16)
        r=fixture();p=world_attachment(r,0,(10,20,30),(0,1,0),2)
        # raw (0,3,0), Rx(-pi/2), Q, then engineering owner of Yup +Y.
        angle=struct.unpack('<f',struct.pack('<f',-math.pi/2))[0]
        for actual,expected in zip(p,(10.-6*math.sin(angle),20.,30.-6*math.cos(angle))):
            self.assertAlmostEqual(actual,expected,places=11)
        # Raw forward +X => c=-Y, f=X, -u=+Z; conjugated Q axes.
        self.assertEqual(owner_matrix((0,0,1),observed=True),
                         [0,0,-1,0,0,1,0,0,1,0,0,0,0,0,0,1])
        with self.assertRaises(ValueError):owner_matrix((0,0,0))

    def test_source_change_invalidates_cache(self):
        import bugbits.assets.flower_pose as fp
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            for ext in ('.v3d','.van'):
                (folder/('flower_a'+ext)).write_bytes((Path(fp.data_dir('models','props'))/('flower_a'+ext)).read_bytes())
            with patch.object(fp,'data_dir',return_value=folder):
                before=load_normal_rig('flower_a')
                path=folder/'flower_a.van';blob=bytearray(path.read_bytes())
                # First key's x translation, without modifying time/count structure.
                struct.pack_into('<f',blob,24,struct.unpack_from('<f',blob,24)[0]+1)
                path.write_bytes(blob)
                after=load_normal_rig('flower_a')
                self.assertNotEqual(before['animationSHA'],after['animationSHA'])
                self.assertNotEqual(before['rigSHA256'],after['rigSHA256'])
                self.assertNotEqual(before['nodes'][0]['keys'],after['nodes'][0]['keys'])
                path.unlink()
                with self.assertRaises(FileNotFoundError):load_normal_rig('flower_a')

    def test_three_sources_and_no_shared_mutation(self):
        for asset in ('flower_a','flower_b','cactus_a'):
            r=load_normal_rig(asset);validate_rig(r)
            self.assertEqual(r['nodes'][r['nektarNode']]['name'],'nektar')
            self.assertTrue(all(math.isfinite(v) for v in attachment_at(r,r['duration']/2)))
            r['nodes'][0]['name']='mutated'
            self.assertNotEqual(load_normal_rig(asset)['nodes'][0]['name'],'mutated')
