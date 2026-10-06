"""FIX-03 U01（构建侧红例）: multi/multir 关演示配置——可买栏(采集+进攻兵种)
+ 敌方 Bot 进攻兵种纳入同一关卡策略与资产闭包。

版本化显式演示配置（非原作随机虫栏 H28；原 multibattle=8 槽 Priority 排序 /
multirandom=LCG 对称随机, docs/exe-econ.md §6）。独立预期来源 = unitdb 数值
（can_gather/price/hive_damage）手算校验，不反抄 web_build 输出。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import unitdb, web_build  # noqa: E402


def _hive_attacker(spec):
    """有效进攻兵种 = 能攻巢（HiveDamage>0, 决定胜负的通道）。

    ant/bee 有 MeleeDamage 但 can_gather（mode=patrol 永不行军攻巢）,
    故不据此判定进攻；只有 HiveDamage>0 的非采集兵种能拆巢取胜。
    """
    return (spec.hive_damage or 0) > 0


def _multi_closures():
    ids = [n for n in web_build.discover_levels("full")
           if n.startswith(("multi_", "multir_"))]
    closures, _, _ = web_build.survey(ids)
    return {c.id: c for c in closures}


class TestMultiDemoConfig(unittest.TestCase):
    def setUp(self):
        self.cs = _multi_closures()
        self.assertEqual(len(self.cs), 18, "应为 18 关 multi/multir")

    def test_buyable_has_gather_and_attack(self):
        for cid, c in self.cs.items():
            with self.subTest(level=cid):
                specs = {u: unitdb.load_unit(u) for u in c.buyable}
                gather = [u for u, s in specs.items() if s.can_gather]
                attack = [u for u, s in specs.items() if _hive_attacker(s)]
                self.assertTrue(gather, f"{cid}: 可买栏无采集兵种 {c.buyable}")
                self.assertTrue(attack, f"{cid}: 可买栏无进攻兵种 {c.buyable}")

    def test_enemy_bot_attack_unit_valid(self):
        for cid, c in self.cs.items():
            with self.subTest(level=cid):
                self.assertIsNotNone(c.enemy_bot, f"{cid}: 无敌方 Bot 配置")
                au = c.enemy_bot["attack_unit"]
                self.assertIn(au, c.units, f"{cid}: 敌方进攻兵种 {au} 不在闭包")
                spec = unitdb.load_unit(au)
                self.assertIsNotNone(spec.price, f"{cid}: {au} 无价格定义")
                self.assertTrue(_hive_attacker(spec),
                                f"{cid}: {au} 无实际进攻能力(HiveDamage>0)")

    def test_closure_includes_buyable_and_attack(self):
        for cid, c in self.cs.items():
            with self.subTest(level=cid):
                for u in list(c.buyable) + [c.enemy_bot["attack_unit"]]:
                    self.assertIn(u, c.units, f"{cid}: {u} 未入资产闭包")


if __name__ == "__main__":
    unittest.main()
