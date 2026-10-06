"""Normal cLevel load mode0 + START id12; public gameplay, raw world untouched."""
import unittest
import json
from pathlib import Path
import subprocess
import struct

from bugbits import level, sim, unitdb, worlddb, web_data
from bugbits.assets import data_dir
from bugbits.web_bridge import WebBridge


class NormalLevelStartSides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = worlddb.parse_world(data_dir('worlds', 'world_01.vsc'))
        cls.units = {'ant': unitdb.load_unit('ant')}

    def test_real_reverse_level_buys_at_opposite_raw_start(self):
        # Original SideID setter: reverse && mode112==0 => raw zero becomes1,
        # raw nonzero becomes0. DATA raw StartRight0 is below in loaded Y-up.
        lv = level.parse_level(data_dir('scripts', 'levels', 'level_11.vsc'))
        game = sim.Sim(lv, self.world, self.units, seed=2026)
        bug = game.buy(0, 'ant', 0)
        self.assertIsNotNone(bug)
        expected = (-60.0650177002, 4.8231506348, 221.5774230957)
        for got, want in zip(bug.pos(game), expected):
            self.assertAlmostEqual(got, want, places=8)
        self.assertEqual(self.world.start(0, 0).name, 'StartLeft0')

    def test_shared_raw_world_initializes_each_session_once(self):
        expected = {
            'level_11': ((-60.0650177002, 4.8231506348, 221.5774230957),
                         (-24.8668556213, -2.7717857361, -185.767288208)),
            'level_01': ((-24.8668556213, -2.7717857361, -185.767288208),
                         (-60.0650177002, 4.8231506348, 221.5774230957)),
        }
        for name in ('level_11', 'level_11', 'level_01'):
            game = sim.Sim(level.parse_level(data_dir('scripts', 'levels', name + '.vsc')),
                           self.world, self.units, seed=2026)
            for side in (0, 1):
                bug = game.spawn_free(side, 'ant', 0)
                self.assertIsNotNone(bug)
                # Original motion fields store IEEE754 binary32; the raw
                # parsed world/hive below retain their source text values.
                stored = tuple(struct.unpack('<f',struct.pack('<f',v))[0]
                               for v in expected[name][side])
                self.assertEqual(bug.pos(game), stored)
                self.assertEqual(game.hives[side].pos, expected[name][side])
            self.assertEqual(self.world.start(0, 0).name, 'StartLeft0')
            self.assertEqual(self.world.start(1, 0).name, 'StartRight0')

    def test_snapshot_and_reset_publish_effective_lanes(self):
        lv = level.parse_level(data_dir('scripts', 'levels', 'level_11.vsc'))
        ld, wd, ud = (web_data.level_to_dict(lv), web_data.world_to_dict(self.world),
                      {name: web_data.unit_to_dict(spec) for name, spec in self.units.items()})
        bridge = WebBridge()
        bridge.init('level_11', 2026, ld, wd, ud)
        for iteration in range(3):
            if iteration:
                bridge.reset('level_11', 2026, ld, wd, ud)
            snap = bridge.snapshot()
            own = next(s for s in snap['starts'] if s['side'] == 0 and s['index'] == 0)
            self.assertEqual(own['name'], 'StartRight0')
            self.assertEqual(own['pos'], [-60.0650177002, 4.8231506348, 221.5774230957])
            self.assertEqual(snap['hives'][0]['pos'], own['pos'])
            self.assertEqual(next(s for s in wd['starts'] if s['name'] == 'StartRight0')['sideId'], 1)

    def test_real_host_refresh_uses_effective_snapshot_lane_markers(self):
        lv = level.parse_level(data_dir('scripts', 'levels', 'level_11.vsc'))
        bridge = WebBridge()
        bridge.from_objects(lv, self.world, self.units, 2026)
        snapshot = json.dumps(bridge.snapshot())
        body = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const snapshot=JSON.parse(process.argv[1]);
const state={generation:1,starts0:{0:[-24.8668556213,-2.7717857361,-185.767288208]}};
const scope=vm.createContext({state,$:()=>({textContent:''}),
 call:async()=>({ok:true,result:snapshot}),updateHud(){},pollEvents:async()=>{}});
const host=fs.readFileSync('web/host.js','utf8'),start=host.indexOf('async function refresh(');
vm.runInContext(host.slice(start,host.indexOf('\nfunction updateHud(',start)),scope);
(async()=>{await scope.refresh({tick:0,winner:null},1);
 assert.deepEqual(Array.from(state.starts0[0]),[-60.0650177002,4.8231506348,221.5774230957]);
 assert.equal(Object.keys(state.starts0).length,3); // DATA world01 has 3 lanes.
 // Old generation replies leave every current-session marker untouched.
 const before=JSON.stringify(state.starts0);await scope.refresh({tick:0,winner:null},0);
 assert.equal(JSON.stringify(state.starts0),before);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-e', body, snapshot],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reverse_side_setter_maps_any_nonzero_to_player(self):
        # Typed original setter uses SETE(rawSide,0), not 1-rawSide or XOR1.
        for raw_side in (1, 2, -1):
            with self.subTest(raw_side=raw_side):
                raw = worlddb.WorldData({}, [], [], None,
                    [worlddb.Start('NonzeroStart', (100, 0, 0), (0, 0, 1),
                                   raw_side, 0, [])], [], 0)
                lv = level.LevelData({'InitialNectar':['10'], 'IsReversed':['1']})
                game = sim.Sim(lv, raw, self.units, seed=2026)
                bug = game.buy(0, 'ant', 0)
                self.assertIsNotNone(bug)
                self.assertEqual(bug.pos(game), (100, 0, 0))
                self.assertEqual(raw.starts[0].side_id, raw_side)


if __name__ == '__main__':
    unittest.main()
