"""Real level light tokens and VM consumption; not an original light formula."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bugbits import level, unitdb, web_data, worlddb
from bugbits.assets import data_dir
from bugbits.web_bridge import WebBridge

TOP = ['0', 'ffffa0d0', '20303060', 'ffa0a0ff', '0.7', '10', '0', '0', '180']
SCRIPT = ['20', 'ffc0c0ff', '20242420', 'ffffffff', '1', '40', '0', '-30', '200']


class PresentationLight(unittest.TestCase):
    def level(self):
        return level.parse_level(data_dir('scripts', 'levels', 'level_01.vsc'))

    def bridge(self, lv=None):
        bridge = WebBridge()
        bridge.from_objects(lv or self.level(),
            worlddb.parse_world(data_dir('worlds', 'world_01.vsc')), unitdb.load_all(), 42)
        return bridge

    def advance_to(self, bridge, tick):
        while bridge.snapshot()['tick'] < tick:
            bridge.advance(min(5, tick - bridge.snapshot()['tick']))

    def test_real_top_level_tokens_roundtrip_and_legacy_shape(self):
        lv = self.level()
        self.assertEqual(lv.light_requests, [tuple(TOP)])
        packed = json.loads(json.dumps(web_data.level_to_dict(lv)))
        self.assertEqual(packed['lightRequests'], [TOP])
        self.assertEqual(web_data.restore_level(packed).light_requests, [tuple(TOP)])
        packed.pop('lightRequests')
        self.assertEqual(web_data.restore_level(packed).light_requests, [])
        packed['lightRequests'] = [TOP[:-1]]
        with self.assertRaises(ValueError):
            web_data.restore_level(packed)

    def test_actual_vm_boundary_snapshot_copy_and_reset(self):
        bridge = self.bridge()
        initial = {'args': TOP, 'tick': 0, 'source': 'level', 'scope': 'raw-vsc-request-v1'}
        self.assertEqual(bridge.snapshot()['presentation']['lightRequest'], initial)
        self.advance_to(bridge, 102)
        self.assertEqual(bridge.snapshot()['presentation']['lightRequest'], initial)
        self.advance_to(bridge, 103)
        expected = {'args': SCRIPT, 'tick': 103, 'source': 'script', 'scope': 'raw-vsc-request-v1'}
        snapshot = bridge.snapshot()
        self.assertEqual(snapshot['presentation']['lightRequest'], expected)
        snapshot['presentation']['lightRequest']['args'][1] = '00000000'
        self.assertEqual(bridge.snapshot()['presentation']['lightRequest'], expected)
        self.assertEqual(bridge.audit_state()['vm']['lightRequest'], expected)
        before = bridge.snapshot()
        self.assertEqual(bridge.snapshot(), before)  # no advance: request/tick frozen
        bridge.from_objects(self.level(), bridge.session.sim.world, unitdb.load_all(), 42)
        self.assertEqual(bridge.snapshot()['presentation']['lightRequest'], initial)

    def test_request_changes_do_not_change_gameplay_or_rng(self):
        lv = self.level()
        baseline = copy.deepcopy(lv)
        baseline.light_requests = []
        baseline.scripts = [('ignored_light', a) if s == 'setlight' else (s, a)
                            for s, a in baseline.scripts]
        live, control = self.bridge(lv), self.bridge(baseline)
        self.advance_to(live, 110)
        self.advance_to(control, 110)
        a, b = live.audit_state(), control.audit_state()
        a['vm'].pop('lightRequest'); b['vm'].pop('lightRequest')
        self.assertEqual(a, b)
        self.assertNotEqual(live.session.vm.state_repr(), control.session.vm.state_repr())


if __name__ == '__main__':
    unittest.main()
