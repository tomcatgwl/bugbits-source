"""NC 相机交付：有界相机预设表（web_build.camera_presets_for）——DATA 锚定断言。"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

from bugbits import worlddb  # noqa: E402
from bugbits.assets import data_dir  # noqa: E402
from bugbits.web_build import CAMERA_PRESET_WORLDS, camera_presets_for  # noqa: E402


class TestCameraPresets(unittest.TestCase):
    """预设参数与 world .vsc DATA 逐字段锚定（loop-harness-camera-delivery.md）。"""

    def _presets(self, world, units=("ant", "littlebeetle")):
        wd = worlddb.parse_world(data_dir("worlds", world + ".vsc"))
        return camera_presets_for(world, wd, list(units)), wd

    def test_bounded_worlds(self):
        """预设世界集合有界（候选预算控制，非全部世界）。"""
        self.assertEqual(CAMERA_PRESET_WORLDS, ("world_02", "world_03"))

    def test_world02_original_cam_anchored(self):
        """world_02：pitch=MinAngle(0.7rad)、yaw=0（中性）、距离=MinCamDistance、
        目标=Offset（CAM-PARAM STATIC 取证锚定，param-forensics/report.md）。"""
        presets, wd = self._presets("world_02")
        self.assertIn("original_cam", presets)
        ps = presets["original_cam"]
        cam = ps["camera"]
        # DATA 为 float32（0.6999999881），对照 f32 值而非理想 0.7
        self.assertAlmostEqual(
            cam["pitchDeg"],
            math.degrees(float(wd.props["MinAngle"][0])), places=9)
        self.assertEqual(cam["yawDeg"], 0.0)      # MaxYaw=缩放上限，非固定值
        self.assertEqual(cam["aspect"], 1.6)
        self.assertEqual(cam["fovDeg"], 60.0)
        self.assertEqual(cam["distance"], 180.0)  # STATIC 0x48509e 跟踪距离目标
        offset = [float(v) for v in wd.props["Offset"]]
        self.assertEqual(cam["target"][0], offset[0])
        self.assertEqual(cam["target"][2], offset[1])
        # 证据逐字段随行（未闭合项显式标注，不冒充已证）
        ev = ps["evidence"]
        for key in ("pitchDeg", "yawDeg", "aspect", "distance", "target"):
            self.assertIn(key, ev)
        self.assertIn("UNVERIFIED", ev["yawDeg"])      # 旋转方向符号
        self.assertIn("STATIC", ev["distance"])        # 跟踪距离=MinCamDistance
        # 单位预设 atlasScale 为正（预设 pitch 重算）
        for u, v in ps["unitAtlasScale"].items():
            self.assertGreater(v, 0.0, u)
        self.assertGreater(ps["flowerAtlasScale"], 0.0)
        # 指标：两端巢穴投影都有记录
        self.assertIn("0", ps["metrics"]["hivePx"])
        self.assertIn("1", ps["metrics"]["hivePx"])

    def test_world03_low_pitch(self):
        """world_03：MinAngle=0.4rad（22.9° 低机位）+ MinCamDistance=180。"""
        presets, wd3 = self._presets("world_03")
        cam = presets["original_cam"]["camera"]
        self.assertAlmostEqual(
            cam["pitchDeg"],
            math.degrees(float(wd3.props["MinAngle"][0])), places=9)
        self.assertEqual(cam["distance"], 180.0)

    def test_non_preset_world_empty(self):
        """预设世界之外（world_04）返回空表——预算边界。"""
        presets, _wd = self._presets("world_04", units=("ant",))
        self.assertEqual(presets, {})


if __name__ == "__main__":
    unittest.main()
