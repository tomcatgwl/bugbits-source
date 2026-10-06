"""Public V3D reference-slot contract from original binary loader evidence."""
from pathlib import Path
import json
import subprocess
import unittest

from bugbits.assets.v3d import parse_v3d
from bugbits.assets.pose import skin_at

DATA = Path(__file__).resolve().parents[1] / 'analyze/extracted/ccdzz/data'


class SkinReferenceContract(unittest.TestCase):
    def test_web_null_reference_contributes_source_without_root_transform(self):
        identity = [1., 0., 0., 0., 0., 1., 0., 0.,
                    0., 0., 1., 0., 0., 0., 0., 1.]
        rig = dict(contract='flower-node-keys-v1', assetId='fixture',
                   modelSource='fixture.v3d', modelSHA='a' * 64,
                   animationSource='fixture.van', animationSHA='b' * 64,
                   duration=1., nektarNode=0,
                   nodes=[dict(name='nektar', parent=-1, bind=identity,
                               keys=[[0, 0, 0, 0, 6, 0, 0],
                                     [1, 0, 0, 1.5707963267948966, 6, 0, 0]])])
        unsigned = json.dumps(rig, sort_keys=True, separators=(',', ':'))
        rig['rigSHA256'] = 'c' * 64
        prop = dict(animationScope='normal-flower-node-keys-v1', animationRig=rig,
                    animationRigJson=unsigned, positions=[2., 0., 0.], normals=[1., 0., 0.],
                    animationSkin=[[[2., 0., 0.], [1., 0., 0.], [[-1, .5], [0, .5]]]])
        result = subprocess.run(
            ['node', '-e', "const fs=require('fs');const api=require('./web/flower_pose.js');"
             "const p=JSON.parse(fs.readFileSync(0,'utf8'));"
             "const result=api.createSampler(p).sample(1);"
             "p.animationSkin[0][2][0][0]=-2;"
             "require('assert').throws(()=>api.createSampler(p));"
             "process.stdout.write(JSON.stringify(result));"],
            cwd=DATA.parents[3], input=json.dumps(prop), text=True,
            capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        for value, expected in zip(actual['positions'], (4., 1., 0.)):
            self.assertAlmostEqual(value, expected, places=12)
        for value, expected in zip(actual['normals'], (2 ** -.5, 2 ** -.5, 0.)):
            self.assertAlmostEqual(value, expected, places=12)

    def test_null_reference_contributes_source_without_root_transform(self):
        identity = (1., 0., 0., 0., 0., 1., 0., 0.,
                    0., 0., 1., 0., 0., 0., 0., 1.)
        rotate_translate = (0., 1., 0., 0., -1., 0., 0., 0.,
                            0., 0., 1., 0., 6., 0., 0., 1.)
        source = [((2., 0., 0.), (1., 0., 0.), (.25, .75))]
        result = skin_at([(source[0][0], source[0][1], [(-1, .5), (0, .5)])],
                         [identity], [rotate_translate], source_vertices=source)[0]
        # NULL contributes (2,0,0)/(1,0,0); root contributes
        # (6,2,0)/(0,1,0). Original weighted mean is (4,1,0).
        self.assertEqual(result[0], (4., 1., 0.))
        for actual, expected in zip(result[1], (2 ** -.5, 2 ** -.5, 0.)):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertEqual(result[2], (.25, .75))

    def test_ant_reference_slot_is_resolved_to_declared_node(self):
        _, skin, records, _ = parse_v3d(DATA / 'models/bugs/ant.v3d')
        # Original declared prefix ends at 87744. Its first reference table
        # contains slot 38 = node 32; source vertex 0 uses slot 38 at 100%.
        # A scanner record index is not a skin reference slot.
        self.assertEqual(skin[0][2], [(32, 1.)])
        self.assertEqual(len(records), 39)


if __name__ == '__main__':
    unittest.main()
