"""Finite public skinning contract from original 44C5B0, not native frames."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from bugbits.assets.pose import skin_at

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


class SkinWeightContract(unittest.TestCase):
    def test_nonunit_weight_sum_preserves_identity_position(self):
        result = skin_at([((2., 4., 6.), (1., 0., 0.), [(0, .5)])],
                         [IDENTITY], [IDENTITY])[0]
        # Literal identity pose: dividing the original accumulation by .5
        # restores the source point; it cannot shrink the model by half.
        self.assertEqual(result[0], (2., 4., 6.))
        self.assertEqual(result[1], (1., 0., 0.))

    def test_zero_total_preserves_source_position_and_zero_normal(self):
        result = skin_at([((2., 4., 6.), (1., 0., 0.), [(0, 0.)])],
                         [IDENTITY], [IDENTITY])[0]
        self.assertEqual(result[0], (2., 4., 6.))
        self.assertEqual(result[1], (0., 0., 0.))

    def test_web_sampler_normalizes_accepted_nearunit_weights(self):
        keys = [[0, 0, 0, 0, 6, 0, 0], [1, 0, 0, 0, 6, 0, 0]]
        rig = dict(contract='flower-node-keys-v1', assetId='fixture',
                   modelSource='fixture.v3d', modelSHA='a' * 64,
                   animationSource='fixture.van', animationSHA='b' * 64,
                   duration=1., nektarNode=0,
                   nodes=[dict(name=name, parent=-1, bind=list(IDENTITY), keys=keys)
                          for name in ('nektar', 'other')])
        unsigned = json.dumps(rig, sort_keys=True, separators=(',', ':'))
        rig['rigSHA256'] = hashlib.sha256(unsigned.encode()).hexdigest()
        prop = dict(animationScope='normal-flower-node-keys-v1', animationRig=rig,
                    animationRigJson=unsigned, positions=[2., 4., 6.], normals=[0., 1., 0.],
                    animationSkin=[[[2., 4., 6.], [0., 1., 0.], [[0, .5], [1, .500004]]]])
        result = subprocess.run(
            ['node', '-e', "const fs=require('fs');const api=require('./web/flower_pose.js');"
             "process.stdout.write(JSON.stringify(api.createSampler(JSON.parse(fs.readFileSync(0,'utf8'))).sample(0)));"],
            cwd=Path(__file__).resolve().parents[1], input=json.dumps(prop),
            text=True, capture_output=True, timeout=10, check=True)
        # Both bones translate by six: the identity point must become (8,4,6),
        # even when the accepted source weights differ slightly from one.
        actual = json.loads(result.stdout)
        for value, expected in zip(actual['positions'], (8., 4., 6.)):
            self.assertAlmostEqual(value, expected, places=12)
        self.assertEqual(actual['normals'], [0., 1., 0.])

    def test_small_positive_normal_is_normalized(self):
        result = skin_at([((2., 4., 6.), (0., 1., 0.), [(0, 1e-13)])],
                         [IDENTITY], [IDENTITY])[0]
        self.assertEqual(result[1], (0., 1., 0.))

    def test_opposing_rotations_leave_cancelled_normal_zero(self):
        half_turn = (-1., 0., 0., 0., 0., -1., 0., 0.,
                     0., 0., 1., 0., 0., 0., 0., 1.)
        result = skin_at([((0., 0., 0.), (1., 0., 0.), [(0, .5), (1, .5)])],
                         [IDENTITY, IDENTITY], [IDENTITY, half_turn])[0]
        self.assertEqual(result[1], (0., 0., 0.))


if __name__ == '__main__':
    unittest.main()
