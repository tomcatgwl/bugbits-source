"""Original client input sampled through public camera/Bridge boundaries."""
import unittest
import json

from bugbits.sim.camera import NativeCamera
from bugbits.web_bridge import WebBridge, bridge_call


PROPS = {key: [str(value)] for key, value in dict(MinCamDistance=180,
    MaxCamDistance=400, MinAngle=.7, MaxYaw=.4, Width=350, Height=200).items()}
PROPS['Offset'] = ['0', '0', '0']


class NativeCameraPointer(unittest.TestCase):
    def test_world_constructor_zero_then_first_interface_sample_uses_default_centre(self):
        camera = NativeCamera(PROPS)
        self.assertEqual(camera.snapshot()['inputXY'], [0., 0.])
        camera.distance = 360.  # Explicit legal old-distance fixture, no input override.
        camera.advance(.125)
        state = camera.snapshot()
        self.assertEqual(state['inputXY'], [800., 600.])
        self.assertEqual(state['goalDistance'], 435.)
        self.assertEqual(state['distance'], 374.0625)

    def test_signed_client_input_is_sampled_only_on_world_update_even_with_zero_dt(self):
        camera = NativeCamera(PROPS)
        old = camera.snapshot()
        self.assertTrue(camera.set_client_input((-20, -30), (1024, 768), 1))
        self.assertEqual(camera.snapshot()['inputXY'], [0., 0.])
        camera.advance(0.)
        state = camera.snapshot()
        self.assertEqual(state['inputXY'], [-31.25, -46.875])
        self.assertEqual(state['clientInput']['positionClient'], [-20, -30])
        self.assertEqual(state['sampledInputSequence'], 1)
        self.assertEqual(state['distance'], old['distance'])
        self.assertEqual(state['targetRaw'], old['targetRaw'])
        self.assertEqual(state['goalDistance'], 402.65625)

    def test_untracked_goal_keeps_original_intermediate_float32_ratio_store(self):
        props = {key: list(value) for key, value in PROPS.items()}
        props['MinCamDistance'] = ['176.5']
        props['MaxCamDistance'] = ['319.25']
        camera = NativeCamera(props)
        camera.set_client_input((512, 158), (1024, 768), 1)
        camera.advance(0.)
        self.assertEqual(camera.snapshot()['inputXY'], [800., 246.875])
        self.assertEqual(camera.snapshot()['goalDistance'], 339.95074462890625)

    def test_bridge_keeps_interface_state_across_world_reset_and_rejects_old_sessions(self):
        from test_native_camera_driver import NativeCameraDriver
        _, payload = NativeCameraDriver().opened()
        bridge = WebBridge()
        opened = bridge.init('level_01', 2026, *payload)
        message = dict(sessionId=opened['sessionId'], sequence=1,
                       positionClient=[-20, -30], sizeClient=[1024, 768])
        accepted = json.loads(bridge_call(bridge, 'camera_input', json.dumps(message)))
        self.assertTrue(accepted['ok'], accepted)
        self.assertEqual(bridge.snapshot()['tick'], 0)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [0., 0.])
        bridge.advance(1)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [-31.25, -46.875])
        reset = bridge.reset('level_01', 2026, *payload)
        self.assertNotEqual(reset['sessionId'], opened['sessionId'])
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [0., 0.])
        self.assertEqual(bridge.snapshot()['nativeCamera']['clientInput']['positionClient'], [-20, -30])
        stale = json.loads(bridge_call(bridge, 'camera_input', json.dumps(dict(message, sequence=2))))
        self.assertFalse(stale['ok'])
        self.assertEqual(stale['result']['error'], 'E_SESSION')
        bridge.advance(1)
        self.assertEqual(bridge.snapshot()['nativeCamera']['inputXY'], [-31.25, -46.875])
        other, _ = NativeCameraDriver().opened()
        other.advance(1)
        self.assertEqual(other.snapshot()['nativeCamera']['inputXY'], [800., 600.])

    def test_interface_input_is_observable_without_native_camera_and_does_not_buy_or_step(self):
        from test_native_camera_driver import NativeCameraDriver
        _, payload = NativeCameraDriver().opened()
        level, world, units, opts = payload
        world = json.loads(json.dumps(world))
        world['props'].pop('MaxYaw')  # Explicit unsupported camera configuration.
        bridge = WebBridge()
        opened = bridge.init('level_01', 2026, level, world, units, opts)
        before = bridge.audit_state()
        self.assertIsNone(before['nativeCamera'])
        receipt = bridge.camera_input(dict(sessionId=opened['sessionId'], sequence=1,
            positionClient=[123, 456], sizeClient=[1024, 768]))
        self.assertTrue(receipt['accepted'])
        self.assertFalse(receipt['worldSamplePending'])
        after = bridge.audit_state()
        self.assertEqual(after['cameraClientInput']['positionClient'], [123, 456])
        self.assertEqual(bridge.snapshot()['cameraClientInput'], after['cameraClientInput'])
        self.assertEqual({k: v for k, v in after.items() if k != 'cameraClientInput'},
                         {k: v for k, v in before.items() if k != 'cameraClientInput'})
        after['cameraClientInput']['positionClient'][0] = 999
        self.assertEqual(bridge.audit_state()['cameraClientInput']['positionClient'], [123, 456])

    def test_invalid_and_stale_messages_leave_client_and_world_state_unchanged(self):
        from test_native_camera_driver import NativeCameraDriver
        bridge, _ = NativeCameraDriver().opened()
        valid = dict(sessionId=bridge.snapshot()['sessionId'], sequence=1,
                     positionClient=[-32768, 32767], sizeClient=[1024, 768])
        self.assertTrue(bridge.camera_input(valid)['accepted'])
        before = bridge.audit_state()
        invalid = [dict(valid, sequence=1), dict(valid, sequence=0),
            dict(valid, sequence=True), dict(valid, sequence=9007199254740992),
            dict(valid, sequence=2, positionClient=[32768, 0]),
            dict(valid, sequence=2, positionClient=[True, 0]),
            dict(valid, sequence=2, positionClient=[1.5, 0]),
            dict(valid, sequence=2, sizeClient=[0, 768]),
            dict(valid, sequence=2, sizeClient=[2147483648, 768]),
            dict(valid, sequence=2, sizeClient=[float('nan'), 768]),
            dict(valid, sequence=2, sizeClient=[float('inf'), 768]),
            dict(valid, sequence=2, source='unqualified-source'),
            dict(valid, sequence=2, sessionId='old-session')]
        for message in invalid:
            with self.subTest(message=message):
                response = json.loads(bridge_call(bridge, 'camera_input', json.dumps(message)))
                self.assertFalse(response['ok'], response)
                self.assertEqual(bridge.audit_state(), before)
        valid['positionClient'][0] = 100
        self.assertEqual(bridge.snapshot()['cameraClientInput']['positionClient'], [-32768, 32767])

    def test_invalid_update_seconds_do_not_sample_pending_client_input(self):
        camera = NativeCamera(PROPS)
        camera.set_client_input((-20, -30), (1024, 768), 1)
        before = camera.snapshot()
        for seconds in (-1., float('nan'), float('inf')):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                camera.advance(seconds)
            self.assertEqual(camera.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
