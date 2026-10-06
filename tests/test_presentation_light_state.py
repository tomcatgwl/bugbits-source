"""Public fixed-tick light state; original variable frame timing is not claimed."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugbits import presentation_light
from bugbits import level, worlddb, unitdb
from bugbits.assets import data_dir
from bugbits.web_bridge import WebBridge


class LightStateTests(unittest.TestCase):
    def test_real_ten_digit_white_requests_do_not_block_level_initialization(self):
        units = unitdb.load_all()
        for name in ('challenge_04', 'level_05', 'level_10', 'level_21'):
            with self.subTest(level=name):
                lv = level.parse_level(data_dir('scripts', 'levels', name+'.vsc'))
                world = worlddb.parse_world(data_dir('worlds', lv.world_name+'.vsc'))
                bridge = WebBridge()
                bridge.from_objects(lv, world, units, 42)
                packet = bridge.snapshot()['presentation']['lightState']
                self.assertEqual(packet['sourceTokens'][3], 'ffffffffff')
                self.assertEqual(packet['current']['colors'][2], 0xFFFFFFFF)

    def test_interruption_uses_last_committed_base_and_snapshot_is_read_only(self):
        state = presentation_light.LightState()
        state.accept(['0', '80402010', '80000000', '10203040', '2', '11', '23', '5', '4'], 0, 'level')
        state.accept(['1', 'f0c08040', 'f0000000', '8090a0b0', '10', '40', '3', '-7', '12'], 0, 'script')
        state.advance(5)
        state.accept(['1', '00000000', '00000000', '00000000', '0', '0', '0', '0', '0'], 5, 'script')
        state.advance(15)
        actual = state.snapshot()
        self.assertEqual(actual['current']['colors'][0], 0x40201008)
        self.assertEqual(actual['current']['scalars'], [1, 2])
        self.assertEqual(actual['current']['anglesDegrees'], [5.5, 11.5, 2.5])
        state.advance(15)
        self.assertEqual(state.snapshot(), actual)

    def test_color_weight_uses_float32_ratio_before_multiplying_by_255(self):
        state = presentation_light.LightState()
        state.accept(['0', 'ffffffff', 'ffffffff', 'ffffffff', '1', '0', '0', '0', '1'], 0, 'level')
        state.accept(['6.375000000812813', '00000000', '00000000', '00000000', '0', '0', '0', '0', '0'], 0, 'script')
        state.advance(1)
        self.assertEqual(state.snapshot()['current']['colors'], [0xFCFCFCFC] * 3)

    def test_unsigned_hex_overflow_saturates_instead_of_wrapping(self):
        state = presentation_light.LightState()
        state.accept(['0', '100000000', 'ffffffffff', '1', '1', '0', '0', '0', '1'], 0, 'level')
        self.assertEqual(state.snapshot()['current']['colors'], [0xFFFFFFFF, 0xFFFFFFFF, 1])

    def test_invalid_requests_reject_before_changing_published_state(self):
        state = presentation_light.LightState()
        tokens = ['0', '80402010', '80000000', '10203040', '2', '11', '23', '5', '4']
        state.accept(tokens, 0, 'level')
        before = state.snapshot()
        for index, value in [(0, '-1'), (0, 'nan'), (1, 'xyz'), (4, 'inf'), (5, 'NaN')]:
            bad = list(tokens);bad[index] = value
            with self.assertRaises(ValueError):
                state.accept(bad, 10, 'script')
            self.assertEqual(state.snapshot(), before)
        for tick in [-1, True, .5]:
            with self.assertRaises(ValueError):
                state.advance(tick)
            self.assertEqual(state.snapshot(), before)

    def test_zero_request_and_color_boundary_literals(self):
        state = presentation_light.LightState()
        state.accept(['0', '80402010', '80000000', '10203040', '2', '11', '23', '5', '4'], 0, 'level')
        self.assertEqual(state.snapshot()['current']['colors'][0], 0x80402010)
        state.accept(['1', 'f0c08040', 'f0000000', '8090a0b0', '10', '40', '3', '-7', '12'], 0, 'script')
        self.assertEqual(state.snapshot()['current']['colors'][0], 0x7F3F1F0F)
        state.advance(5)
        packet = state.snapshot()
        self.assertEqual(packet['current']['colors'][0], 0x9B5F371B)
        self.assertEqual(packet['current']['scalars'], [4, 6])
        self.assertEqual(packet['current']['anglesDegrees'], [18.25, 18, 2])
        state.advance(20)
        self.assertTrue(state.snapshot()['transitionActive'])
        self.assertEqual(state.snapshot()['current']['colors'][0], 0xEFBF7F3F)
        state.advance(21)
        self.assertFalse(state.snapshot()['transitionActive'])
        self.assertEqual(state.snapshot()['current']['colors'][0], 0xF0C08040)

    def test_public_bridge_real_boundary_reset_and_detachment(self):
        bridge = WebBridge()
        lv = level.parse_level(data_dir('scripts', 'levels', 'level_01.vsc'))
        world = worlddb.parse_world(data_dir('worlds', 'world_01.vsc'))
        units = unitdb.load_all()
        bridge.from_objects(lv, world, units, 42)
        initial = bridge.snapshot()['presentation']['lightState']
        self.assertEqual(initial['current']['scalars'], [.7, 180])
        self.assertEqual(initial['current']['anglesDegrees'], [10, 0, 0])
        for _ in range(102):
            bridge.advance(1)
        self.assertEqual(bridge.snapshot()['presentation']['lightState']['requestTick'], 0)
        bridge.advance(1)
        packet = bridge.snapshot()['presentation']['lightState']
        self.assertEqual(packet['requestTick'], 103)
        self.assertEqual(packet['target']['colors'], [0xFFC0C0FF, 0x20242420, 0xFFFFFFFF])
        self.assertEqual(packet['target']['scalars'], [1, 200])
        self.assertEqual(packet['target']['anglesDegrees'], [40, 0, -30])
        packet['current']['colors'][0] = 0
        self.assertNotEqual(bridge.snapshot()['presentation']['lightState'], packet)
        self.assertEqual(bridge.snapshot(), bridge.snapshot())
        bridge.from_objects(lv, world, units, 42)
        self.assertEqual(bridge.snapshot()['presentation']['lightState'], initial)


if __name__ == '__main__':
    unittest.main()
