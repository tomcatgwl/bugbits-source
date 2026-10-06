"""Bind attachment uses the named full ancestry, never a fixed world height."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bugbits import web_geometry as geometry


class NectarAttachmentTests(unittest.TestCase):
    def test_out_of_order_parent_rotation_translation_has_independent_point(self):
        local = (1,0,0,0,0,1,0,0,0,0,1,0,1,2,3,1)
        parent = (0,1,0,0,-1,0,0,0,0,0,1,0,10,0,0,1)
        records = [('nektar',1,0,local,None),('root',-1,0,parent,None)]
        point = geometry.bind_attachment(records)
        self.assertEqual(point['positionRaw'], [8,1,3])
        self.assertEqual(point['parentChain'], [0,1])
        self.assertEqual(point['poseScope'], 'bind-model-attachment-v1')

    def test_missing_is_explicit_but_duplicate_cycle_and_bad_parent_fail(self):
        identity = tuple(geometry.PROP_IDENTITY)
        self.assertIsNone(geometry.bind_attachment([('root',-1,0,identity,None)]))
        for records in ([('nektar',-1,0,identity,None)]*2,
                        [('nektar',0,0,identity,None)],
                        [('nektar',99,0,identity,None)]):
            with self.assertRaises(ValueError):
                geometry.bind_attachment(records)
