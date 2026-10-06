"""T4.2: 63 关 + 9 世界装载冒烟——语义定调断言全集（research/t42_semantics.py 结论固化）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits import level, unitdb, worlddb  # noqa: E402

ENGINE_SPECIALS = {"nectarbonus", "trapped"}  # BugSetup 在用但无 buginfos (引擎特例)
SCRIPT_SUBS = {"addhint", "removehint", "sendenemy", "sendplayer", "setflow",
               "sethintfreq", "setlight", "sp", "wait", "waituntilnectar"}


def _levels():
    d = data_dir("scripts", "levels")
    return sorted(f[:-4] for f in os.listdir(d) if f.endswith(".vsc"))


def _worlds():
    d = data_dir("worlds")
    return sorted(f[:-4] for f in os.listdir(d) if f.endswith(".vsc"))


def _load_level(name):
    return level.parse_level(os.path.join(data_dir("scripts", "levels"), name + ".vsc"))


class TestAllLevels(unittest.TestCase):
    def test_63_levels_load(self):
        names = _levels()
        self.assertEqual(len(names), 63)
        for name in names:
            lv = _load_level(name)
            self.assertEqual(lv.world_name[:6], "world_", name)
            self.assertTrue(os.path.isfile(data_dir("worlds", lv.world_name + ".vsc")),
                            f"{name}: 世界 {lv.world_name} 不可解")

    def test_bugsetup_units_known(self):
        units = set(unitdb.load_all()) | ENGINE_SPECIALS
        for name in _levels():
            lv = _load_level(name)
            for _, u, _ in lv.bug_setups:
                self.assertIn(u, units, f"{name}: 未知单位 {u}")

    def test_setlanes_semantics(self):
        """SetLanes <敌方经济泳道 a> <路线 b=START Index>; 空集 ⟺ 非单人-vs-AI 型。"""
        for name in _levels():
            lv = _load_level(name)
            if not lv.set_lanes:
                self.assertIn(lv.type, {"menu", "multibattle", "multirandom"},
                              f"{name}: 单人关卡 SetLanes 不应为空")
                continue
            lanes = {lane for lane, _, _ in lv.bug_setups}
            w = worlddb.parse_world(data_dir("worlds", lv.world_name + ".vsc"))
            n_idx = len({s.index for s in w.starts if s.side_id == 0})
            for a, b in lv.set_lanes:
                self.assertIn(a, lanes, f"{name}: SetLanes 泳道 {a} 无 BugSetup")
                self.assertLess(b, n_idx, f"{name}: SetLanes 路线 {b} ≥ START 数 {n_idx}")

    def test_scripts_subcommands_known(self):
        for name in _levels():
            lv = _load_level(name)
            for sub, _ in lv.scripts:
                self.assertIn(sub, SCRIPT_SUBS, f"{name}: 未知子命令 {sub}")

    def test_win_condition_props_by_type(self):
        for name in _levels():
            lv = _load_level(name)
            if lv.type == "gather":
                self.assertIsNotNone(lv.goal_nectar, name)
            elif lv.type == "rescue":
                self.assertIsNotNone(lv.rescue_bug, name)
            elif lv.type == "defense":
                self.assertIsNotNone(lv.defense_time, name)
            else:
                self.assertIsNone(lv.goal_nectar, name)


class TestAllWorlds(unittest.TestCase):
    def test_entity_projection_within_terrain(self):
        """轴映射 (x,y,z)=(p1,p2,p0): 9 世界全部实体投影落地形 bounds 内 (±5)。"""
        for name in _worlds():
            w = worlddb.parse_world(data_dir("worlds", name + ".vsc"))
            self.assertIsNotNone(w.terrain, name)
            t = w.terrain
            ents = list(w.waypoints) + list(w.starts) + list(w.flowers)
            for e in ents:
                self.assertTrue(t[0] - 5 <= e.grid_pos[0] <= t[1] + 5,
                                f"{name}/{e.name}: x 出界 {e.grid_pos[0]:.1f}")
                self.assertTrue(t[4] - 5 <= e.grid_pos[2] <= t[5] + 5,
                                f"{name}/{e.name}: z 出界 {e.grid_pos[2]:.1f}")

    def test_waypoint_edge_lengths(self):
        """wp↔wp 边长 ∈ [5.0, 125.9]（9 世界 675 边实测; >100 仅 3 条）。"""
        for name in _worlds():
            w = worlddb.parse_world(data_dir("worlds", name + ".vsc"))
            by_name = {wp.name: wp for wp in w.waypoints}
            for n, nbrs in w.adjacency.items():
                for m in nbrs:
                    if n not in by_name or m not in by_name:
                        continue
                    a, b = by_name[n].grid_pos, by_name[m].grid_pos
                    d = ((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
                    self.assertTrue(5.0 <= d <= 126.0, f"{name}: wp 边 {n}-{m} 长 {d:.1f}")

    def test_water_binary_and_starts_complete(self):
        for name in _worlds():
            w = worlddb.parse_world(data_dir("worlds", name + ".vsc"))
            n_idx = len({s.index for s in w.starts if s.side_id == 0})
            self.assertGreaterEqual(n_idx, 2, name)
            for side in (0, 1):
                for i in range(n_idx):
                    self.assertIsNotNone(w.start(side, i), f"{name}: 缺 start({side},{i})")


if __name__ == "__main__":
    unittest.main()
