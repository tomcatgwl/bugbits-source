"""OFR-01 BUG-01 回归：可买栏必须从原始 BugSetup + 既定 fallback 合同推导。

根因（2026-09-19 挖掘）：LevelClosure.buyable 曾从资产闭包 units 推导——
units 含脚本增援(sendenemy/sendplayer)与 rescue 被困虫，会把脚本-only 兵种漏进
可买栏，并把「既是 RescueBug 类型、又正常在 BugSetup」的兵种误删。

独立预期来源 = levelmod.parse_level(原始 .vsc).bug_setups ∪ {ant}，按 price 过滤；
不读被测 LevelClosure.buyable / .units。multi/multir 显式演示配置另测（test_web_multi_config）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import level as levelmod  # noqa: E402
from bugbits import unitdb, web_build  # noqa: E402
from bugbits.assets import data_dir  # noqa: E402


def _level(lid):
    return levelmod.parse_level(data_dir("scripts", "levels", lid + ".vsc"))


def _expected_buyable(lid):
    """可买栏合同（fallback）：BugSetup 兵种 ∪ {ant}，排除引擎特例，按 price 过滤。"""
    lv = _level(lid)
    src = {u for (_, u, _) in lv.bug_setups if u not in web_build.ENGINE_SPECIAL_UNITS}
    src.add("ant")
    return sorted(u for u in src if unitdb.load_unit(u).price is not None)


def _script_only_units(lv):
    """脚本增援(sendenemy/sendplayer)出现、但不在 BugSetup 的兵种（Class A 根因）。"""
    script = {a[0] for (sub, a) in lv.scripts
              if sub in ("sendenemy", "sendplayer") and a}
    return script - {u for (_, u, _) in lv.bug_setups}


class TestBuyableFromBugSetup(unittest.TestCase):
    def _fallback_closures(self):
        out = {}
        for lid in web_build.discover_levels("full"):
            c = web_build.LevelClosure(lid, _level(lid))
            if c.buyable_kind == "fallback":
                out[lid] = c
        return out

    def test_buyable_matches_independent_bugsetup_derivation(self):
        """核心回归：全可玩关 buyable == 独立从 BugSetup∪{ant} 推导（非 units）。"""
        closures = self._fallback_closures()
        self.assertGreater(len(closures), 40, "fallback 关数应 >40（排除 multi/menu）")
        for lid, c in closures.items():
            with self.subTest(level=lid):
                self.assertEqual(c.buyable, _expected_buyable(lid))

    def test_script_only_units_never_buyable(self):
        """Class A：脚本-only 兵种不得漏进买兵栏（通用不变量）。"""
        for lid, c in self._fallback_closures().items():
            for u in _script_only_units(_level(lid)):
                with self.subTest(level=lid, unit=u):
                    self.assertNotIn(u, c.buyable,
                                     f"{lid}: 脚本-only 兵种 {u} 漏进买兵栏")

    def test_rescue_bugsetup_unit_not_excluded(self):
        """Class B：RescueBug 类型若也在 BugSetup 且可定价 → 不得误删。"""
        for lid, c in self._fallback_closures().items():
            lv = _level(lid)
            rb = lv.rescue_bug
            if not rb:
                continue
            in_setup = any(u == rb for (_, u, _) in lv.bug_setups)
            priced = unitdb.load_unit(rb).price is not None
            with self.subTest(level=lid):
                if in_setup and priced:
                    self.assertIn(rb, c.buyable,
                                  f"{lid}: RescueBug 类型 {rb} 被误删")

    def test_named_class_a_regressions(self):
        """Class A 指名回归（挖掘报告锚点；期望=脚本-only 兵种不在可买栏）。"""
        named = {
            "level_03": ["littlebeetle"], "level_04": ["rhinobeetle"],
            "level_09": ["giantwaterbeetle"], "level_10": ["stagbeetle"],
            "level_11": ["beetlehero"], "level_18": ["toxichero"],
            "level_20": ["wasp"], "level_24": ["toxichero", "wasphero"],
        }
        closures = self._fallback_closures()
        for lid, units in named.items():
            for u in units:
                with self.subTest(level=lid, unit=u):
                    self.assertNotIn(u, closures[lid].buyable,
                                     f"{lid}: {u} 脚本-only 却进了买兵栏")

    def test_named_class_b_regressions(self):
        """Class B 指名回归：RescueBug 类型正常在 BugSetup → 必须在可买栏。"""
        named = {
            "rescue_04": "rhinobeetle", "rescue_07": "caterpillar",
            "rescue_08": "stagbeetle", "rescue_09": "bomberbee",
            "rescue_11": "bigbangbug", "rescue_12": "spider",
            "rescue_13": "toxicbug", "rescue_14": "poisonpillar",
        }
        closures = self._fallback_closures()
        for lid, u in named.items():
            with self.subTest(level=lid, unit=u):
                self.assertIn(u, closures[lid].buyable,
                              f"{lid}: {u} 在 BugSetup 却被误删")


if __name__ == "__main__":
    unittest.main()
