"""Independent literals for the queued cSprite XY / camera inverse basis."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NectarSpriteBasisTests(unittest.TestCase):
    def node(self, body):
        result = subprocess.run(['node', '-e', "const assert=require('assert');const api=require('./web/mesh_scene.js');" + body],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_full_quad_rotates_in_camera_plane_and_keeps_world_translation(self):
        self.node("""
const projection={kind:'matrix-yup-v1',basis9:[0,0,-1,0,1,0,1,0,0],cameraPosition:[100,200,300],size:400,cot:1,aspect:1.6,near:1,far:100};
const record={positionYup:[11,23,5],width:4,height:2,angleRadians:Math.PI/2,basisPolicy:'queued-camera-basis-v1'};
const expected=[11,21,6,11,25,6,11,21,4,11,25,4];
const result=api.spriteVertices(record,projection);
result.forEach((v,i)=>assert(Math.abs(v-expected[i])<1e-12));
assert.deepStrictEqual(record.positionYup,[11,23,5]);
const centered=api.spriteVertices({...record,width:0,height:0},projection);
assert.deepStrictEqual(centered,[11,23,5,11,23,5,11,23,5,11,23,5]);
// Camera translation must not move a queued object's saved WORLD translation.
assert.deepStrictEqual(api.spriteVertices(record,{...projection,cameraPosition:[0,0,0]}),result);
""")

    def test_invalid_dimensions_and_unproven_basis_are_rejected(self):
        self.node("""
const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:1,far:100};
const record={positionYup:[0,0,4],width:4,height:2,angleRadians:0,basisPolicy:'queued-camera-basis-v1'};
for(const bad of [{width:-1},{height:NaN},{angleRadians:Infinity},{positionYup:[0,0,NaN]},{basisPolicy:'apply-flower-owner-again'}])assert.throws(()=>api.spriteVertices({...record,...bad},projection));
assert.throws(()=>api.spriteVertices(record,{...projection,basis9:[2,0,0,0,1,0,0,0,1]}));
""")
