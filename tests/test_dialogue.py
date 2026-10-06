"""T6.5：STATIC 阈值的独立时间表；20Hz 等待映射不是原作动态对照。"""
import math
import os
import sys
import unittest

# 扁平导入修复（NC-harness C）：兄弟测试模块 test_scriptvm/test_sim_combat 在 tests/
# 目录，`python -m unittest tests.test_dialogue` 时 tests/ 不在 sys.path。插入本目录
# 使 `from test_scriptvm import make_vm` 在 discover 与定向运行下解析同一模块。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_scriptvm import make_vm
from test_sim_combat import make_sim, place


class TestDialogue(unittest.TestCase):
    def test_delay_then_one_wait_and_resume(self):
        for delay in (0, 0.25, 2):
            with self.subTest(delay=delay):
                vm, sim = make_vm([("sendenemy", ["littlebeetle", "0", "D", str(delay)])])
                vm.on_tick()
                bug = sim.bugs[0]
                trigger = math.ceil((delay + 1) * 20)
                sim.run(trigger - 1)
                before = bug.pos(sim)
                self.assertNotEqual(before, bug.spawn_pos)  # 延迟期间没有初始冻结
                sim.step()
                self.assertEqual(bug.pos(sim), before)
                sim.run(59)
                self.assertEqual(bug.pos(sim), before)
                sim.step()
                self.assertNotEqual(bug.pos(sim), before)
                sim.run(5)
                self.assertEqual([e[0] for e in sim.events if e[1] == "dialogue_wait"],
                                 [trigger])

    def test_null_skips_reading_delay(self):
        vm, sim = make_vm([("sendplayer", ["ant", "0", "null", "unused"])])
        vm.on_tick()
        self.assertEqual(len(sim.bugs), 1)
        self.assertEqual(sim.bugs[0].dialogue_age, -1)

    def test_menu_skips_dialogue(self):
        vm, sim = make_vm([("sendplayer", ["littlebeetle", "0", "D", "0"])], itype="menu")
        vm.on_tick()
        sim.run(21)
        self.assertEqual(sim.bugs[0].dialogue_age, -1)
        self.assertFalse(any(e[1] == "dialogue_wait" for e in sim.events))

    def test_independent_speakers(self):
        # OFR-02B/PBA-12：同泳道脚本出生受 +0x22c 冷却门禁，同泳道连出会被拒；
        # 两名说话者改用敌我两侧（不同 (side,lane) 冷却键）以保持独立性。
        # 每 tick 恰一条（NC-02-MECH A3）：sendenemy 与 sendplayer 分处两 tick 消费，
        # 第二条对话等待起点晚 1 tick → 事件 (21, 27)（旧同 tick 排空为 (20, 25)）。
        vm, sim = make_vm([("sendenemy", ["littlebeetle", "0", "D1", "0"]),
                           ("sendplayer", ["littlebeetle", "0", "D2", "0.25"])])
        vm.run(2)
        sim.run(25)
        self.assertEqual([(e[0], e[2][0]) for e in sim.events if e[1] == "dialogue_wait"],
                         [(21, sim.bugs[0].bug_id), (27, sim.bugs[1].bug_id)])

    def test_wait_cancels_attack_but_speaker_can_be_hit(self):
        sim = make_sim()
        speaker = place(sim, 0, "ant", 0)
        other = place(sim, 1, "ant", 2)
        speaker.hp = other.hp = 10000
        spec = sim.units["ant"]
        spec.attack_speed = 1
        spec.attack_hit_frames = (1.5,)
        spec.attack_duration = 2
        sim.set_dialogue(speaker, "D", 0)
        sim.run(31)
        damage = [e[2][0] for e in sim.events if e[1] == "damage"]
        self.assertEqual(damage, [other.bug_id])
        self.assertEqual(speaker.attack_tick, -1)
        sim.run(49)  # 等待 t20..79；t80 从头起播
        self.assertEqual(speaker.attack_tick, 0)

    def test_dead_speaker_does_not_resume(self):
        for health, waits in ((1, []), (6, [20])):
            sim = make_sim()
            speaker = place(sim, 0, "tick", 0)
            place(sim, 1, "ant", 2)
            spec = sim.units["ant"]
            spec.attack_speed = 1
            spec.attack_hit_frames = (0.5,)
            spec.attack_duration = 0.6
            spec.attack_wait_min = spec.attack_wait_max = 0
            speaker.hp = health  # t11伤5，t27再伤5；覆盖触发前/等待中死亡
            sim.set_dialogue(speaker, "D", 0)
            sim.run(100)
            self.assertTrue(speaker.dead)
            self.assertEqual([e[0] for e in sim.events if e[1] == "dialogue_wait"], waits)

    def test_sendplayer_applies_wait(self):
        vm, sim = make_vm([("sendplayer", ["littlebeetle", "0", "D", "0"])])
        vm.on_tick()
        sim.run(20)
        self.assertEqual(sim.bugs[0].side, 0)
        self.assertEqual([e[0] for e in sim.events if e[1] == "dialogue_wait"], [20])

    def test_replacement_preserves_existing_wait(self):
        vm, sim = make_vm([])
        bug = sim.spawn_free(0, "littlebeetle", 0)
        sim.set_dialogue(bug, "D1", 0)
        sim.run(20)
        until = bug.dialogue_wait_until
        sim.set_dialogue(bug, "D2", 10)
        self.assertEqual(bug.dialogue_wait_until, until)
        self.assertEqual(bug.dialogue_text, "D2")
        sim.run(60)
        self.assertEqual(len([e for e in sim.events if e[1] == "dialogue_wait"]), 1)

    def test_expiry_and_skipped_window(self):
        vm, sim = make_vm([])
        bug = sim.spawn_free(0, "littlebeetle", 0)
        sim.set_dialogue(bug, "D", -8)  # 更新后已在淡出区间，不可补发等待
        sim.run(40)
        self.assertFalse(any(e[1] == "dialogue_wait" for e in sim.events))
        self.assertEqual(bug.dialogue_age, -1)

    def test_fields_affect_partial_hash(self):
        vm, sim = make_vm([])
        bug = sim.spawn_free(0, "littlebeetle", 0)
        for field, value in (("dialogue_text", "D"), ("dialogue_delay", 0.25),
                             ("dialogue_age", 2), ("dialogue_pending", True),
                             ("dialogue_wait_until", 99)):
            before = sim.state_hash()
            setattr(bug, field, value)
            self.assertNotEqual(before, sim.state_hash(), field)

    def test_nonfinite_delay_rejected(self):
        vm, sim = make_vm([])
        bug = sim.spawn_free(0, "littlebeetle", 0)
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                sim.set_dialogue(bug, "D", value)


if __name__ == "__main__":
    unittest.main()
