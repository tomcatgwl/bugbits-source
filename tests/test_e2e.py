"""T4.7: E2E 垂直切片——bot 取胜/确定性/墙钟（level_02 全流程）。"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits import bot, level as levelmod, scriptvm, sim as simmod, unitdb, worlddb  # noqa: E402


def make_game(seed=2026, level_name="level_02"):
    lv = levelmod.parse_level(data_dir("scripts", "levels", level_name + ".vsc"))
    w = worlddb.parse_world(data_dir("worlds", lv.world_name + ".vsc"))
    sim = simmod.Sim(lv, w, unitdb.load_all(), seed=seed)
    vm = scriptvm.ScriptVM(sim, lv)
    b = bot.Bot()
    return sim, vm, b


def full_state(sim, vm, bots):
    """REVIEW-02: Sim(含 RNG/胜负/ID 分配器) + ScriptVM + Bot 完整状态合并。"""
    v = vm.state_repr() if vm is not None else "-"
    b = "|".join(x.state_repr() for x in bots) if bots else "-"
    return f"{sim.state_hash()}|vm[{v}]|bot[{b}]"


def run_game(sim, vm, b, max_ticks=6000, record=None, every=100):
    bots = b if isinstance(b, list) else ([b] if b is not None else [])
    t0 = time.time()
    for _ in range(max_ticks):
        sim.step()
        vm.on_tick()
        for bot_ in bots:
            bot_.on_tick(sim)
        if record is not None and sim.tick % every == 0:
            record.append((sim.tick, full_state(sim, vm, bots)))
        if sim.winner is not None:
            break
    return time.time() - t0


class TestE2E(unittest.TestCase):
    def test_bot_wins_level_02(self):
        """出口: bot 摧毁敌方蜂巢取胜。"""
        sim, vm, b = make_game(seed=2026)
        dt = run_game(sim, vm, b)
        self.assertEqual(sim.winner, 0, f"未取胜 (tick={sim.tick}, 墙钟 {dt:.1f}s)")
        self.assertLess(dt, 60.0)                       # 出口: 全程墙钟 <60s
        # 事件链证据: 买兵→巢伤→巢破→胜
        kinds = [e[1] for e in sim.events]
        self.assertIn("buy", kinds)
        self.assertIn("hive_damage", kinds)
        self.assertIn("hive_destroyed", kinds)
        self.assertIn("victory", kinds)
        self.assertLess(kinds.index("hive_damage"), kinds.index("hive_destroyed"))
        self.assertEqual(kinds[-1], "victory")
        destroyed = next(e for e in sim.events if e[1] == "hive_destroyed")
        self.assertEqual(destroyed[2][0], 1)            # 被摧毁的是敌方(侧1)巢

    def test_determinism_two_runs(self):
        """出口: 同种子两次运行逐 tick 完整状态一致（Sim+VM+Bot）。"""
        runs = []
        for _ in range(2):
            sim, vm, b = make_game(seed=2026)
            rec = []
            run_game(sim, vm, b, record=rec, every=1)
            runs.append(rec)
        self.assertEqual(runs[0], runs[1])
        self.assertGreater(len(runs[0]), 5)             # 至少跑了 5 tick

    def test_state_hash_field_sensitive(self):
        """REVIEW-02: 任一状态字段变更必须改变 hash（完整性, 非巧合）。"""
        sim, vm, b = make_game(seed=2026)
        run_game(sim, vm, b, max_ticks=50)
        h0 = sim.state_hash()
        sim.rng.random()                                # 多消费一次 RNG → hash 变
        self.assertNotEqual(h0, sim.state_hash())

        sim2, vm2, b2 = make_game(seed=2026)
        run_game(sim2, vm2, b2, max_ticks=50)
        h = sim2.state_hash()
        sim2.winner = 1                                 # 胜负字段 → hash 变
        self.assertNotEqual(h, sim2.state_hash())

        sim3, vm3, b3 = make_game(seed=2026)
        run_game(sim3, vm3, b3, max_ticks=50)
        h = sim3.state_hash()
        sim3._next_id += 1                              # ID 分配器 → hash 变
        self.assertNotEqual(h, sim3.state_hash())

    def test_independent_process_determinism(self):
        """REVIEW-02: 不同 PYTHONHASHSEED 独立进程回放，完整状态逐 tick 一致。"""
        script = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from bugbits.assets import data_dir\n"
            "from bugbits import bot, level, scriptvm, sim, unitdb, worlddb\n"
            "lv = level.parse_level(data_dir('scripts','levels','level_02.vsc'))\n"
            "w = worlddb.parse_world(data_dir('worlds', lv.world_name + '.vsc'))\n"
            "s = sim.Sim(lv, w, unitdb.load_all(), seed=2026)\n"
            "v = scriptvm.ScriptVM(s, lv)\n"
            "b = bot.Bot()\n"
            "hashes = []\n"
            "for _ in range(300):\n"
            "    s.step(); v.on_tick(); b.on_tick(s)\n"
            "    hashes.append(s.state_hash() + '|' + v.state_repr()\n"
            "                  + '|' + b.state_repr())\n"
            "    if s.winner is not None: break\n"
            "print('\\n'.join(hashes))\n"
        )
        env0 = dict(os.environ, PYTHONHASHSEED="0")
        env1 = dict(os.environ, PYTHONHASHSEED="1")
        out0 = subprocess.check_output([sys.executable, "-c", script],
                                       env=env0, text=True)
        out1 = subprocess.check_output([sys.executable, "-c", script],
                                       env=env1, text=True)
        self.assertEqual(out0, out1)
        self.assertGreater(out0.count("\n"), 5)         # 至少 5 个采样点

    def test_bot_parameters_exposed(self):
        """bot = 切片驱动器（参数暴露）: 换单位/节奏仍可跑。"""
        sim, vm, _ = make_game(seed=7)
        b = bot.Bot(gather_ants=2, attack_unit="bee", attack_every=5)
        run_game(sim, vm, b, max_ticks=800)
        self.assertIn(sim.winner, (None, 0, 1))         # 不误判


DEFENSE_LEVELS = ["level_04", "level_07", "level_10", "level_12", "level_15",
                  "level_16", "level_17", "level_19", "level_22"]


class TestDefenseE2E(unittest.TestCase):
    """T6.1: defense 关 E2E——速攻取胜 + 倒计时存活取胜 + 9 关冒烟。"""

    def test_bot_wins_level_04_rush(self):
        """出口: bot 速攻敌巢取胜（敌巢破路径, 倒计时未到）, 我巢存活。"""
        sim, vm, b = make_game(level_name="level_04")
        dt = run_game(sim, vm, b, max_ticks=6000)
        self.assertEqual(sim.winner, 0, f"未取胜 (tick={sim.tick}, 墙钟 {dt:.1f}s)")
        self.assertLess(sim.tick, sim.defense_deadline)   # 胜因=敌巢破非倒计时
        self.assertGreater(sim.hives[0].hp, 0)            # bot 存活
        self.assertNotIn("survived", [e[1] for e in sim.events])
        self.assertLess(dt, 30.0)

    def test_defense_countdown_survives(self):
        """出口: DefenseTime 内存改写 15s → 倒计时存活取胜（survived→victory）。"""
        sim, vm, _ = make_game(level_name="level_04")
        sim.level.props["DefenseTime"] = ["15"]
        sim.defense_deadline = int(round((15 + 0.5) * 20))   # 死线同步改写
        dt = run_game(sim, vm, None, max_ticks=320)
        self.assertEqual(sim.winner, 0)
        self.assertEqual(sim.tick, sim.defense_deadline)
        self.assertGreater(sim.hives[0].hp, 0)            # 存活到倒计时
        kinds = [e[1] for e in sim.events]
        self.assertEqual(kinds[-2:], ["survived", "victory"])
        self.assertLess(dt, 30.0)

    def test_nine_defense_levels_smoke(self):
        """出口: 9 defense 关装载+500t 回放无异常, 胜负不误判。"""
        for name in DEFENSE_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                self.assertIsNotNone(sim.defense_deadline, name)
                run_game(sim, vm, None, max_ticks=500)
                self.assertIn(sim.winner, (None, 0, 1), name)
                if sim.winner is not None:
                    self.assertIn("victory",
                                  [e[1] for e in sim.events], name)


GATHER_LEVELS = ["level_01", "level_06", "level_13", "level_14", "level_21"]


class TestGatherE2E(unittest.TestCase):
    """T6.2: gather 关 E2E——守军维持采集取胜 + 5 关冒烟。"""

    def test_bot_wins_level_01_tutorial(self):
        """出口: 守军维持 bot 攒蜜 60 取胜, 我巢存活（教程关全流程）。"""
        sim, vm, _ = make_game(level_name="level_01")
        b = bot.Bot(gather_ants=20, attack_unit="stinkbug",
                    attack_lanes=(0, 1, 2), garrison=12, attack_every=10,
                    defend=True)      # H15/W3: 攻巢=自杀后守军驻守本巢，不行军送死
        dt = run_game(sim, vm, b, max_ticks=9000)
        self.assertEqual(sim.winner, 0, f"未取胜 (tick={sim.tick}, 墙钟 {dt:.1f}s)")
        self.assertEqual(sim.nectar[0], sim.level.goal_nectar)
        self.assertGreater(sim.hives[0].hp, 0)            # 存活到蜜达标
        kinds = [e[1] for e in sim.events]
        self.assertIn("deposit", kinds)
        self.assertEqual(kinds[-1], "victory")
        self.assertLess(dt, 60.0)

    def test_five_gather_levels_smoke(self):
        """出口: 5 gather 关装载+1000t 回放无异常, 胜负不误判。"""
        for name in GATHER_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                self.assertIsNotNone(sim.level.goal_nectar, name)
                run_game(sim, vm, None, max_ticks=1000)
                self.assertIn(sim.winner, (None, 0, 1), name)
                if sim.winner is not None:
                    self.assertIn("victory", [e[1] for e in sim.events], name)


RESCUE_LEVELS = [f"rescue_{i:02d}" for i in range(1, 15)]


class TestRescueE2E(unittest.TestCase):
    """T6.3: rescue 关 E2E——bee 速攻救援取胜 + 14 关冒烟。"""

    def test_bot_rescues_rescue_01(self):
        """出口: bot bee 速攻（接触即胜, 引擎语义）→ rescued→victory。

        飞行速攻是最优救援策略（无需杀守军）; 5 种子 294-462t 稳定取胜
        （research/t63_rescue_e2e_probe.py）。
        """
        sim, vm, _ = make_game(level_name="rescue_01")
        b = bot.Bot(gather_ants=10, attack_unit="bee",
                    attack_lanes=(1,), garrison=16, attack_every=10)
        dt = run_game(sim, vm, b, max_ticks=8000)
        self.assertEqual(sim.winner, 0, f"未取胜 (tick={sim.tick}, 墙钟 {dt:.1f}s)")
        kinds = [e[1] for e in sim.events]
        self.assertEqual(kinds[-2:], ["rescued", "victory"])
        self.assertLess(dt, 60.0)

    def test_fourteen_rescue_levels_smoke(self):
        """出口: 14 rescue 关装载+1000t 回放无异常, 胜负不误判。"""
        for name in RESCUE_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                self.assertIsNotNone(sim.trapped_bug, name)
                self.assertIsNotNone(sim.defense_deadline, name)
                run_game(sim, vm, None, max_ticks=1000)
                self.assertIn(sim.winner, (None, 0, 1), name)
                if sim.winner is not None:
                    self.assertIn("victory", [e[1] for e in sim.events], name)


MULTI_LEVELS = sorted([f"multi_{i:02d}" for i in range(1, 10)]
                      + [f"multir_{i:02d}" for i in range(1, 10)])


class TestMultiE2E(unittest.TestCase):
    """T6.4: multi 关 E2E——敌我同构双 bot 对局 + 18 关冒烟。"""

    def test_bot_vs_bot_multi_01(self):
        """出口: 双 bot 同构 wasp 对局, 正常终局（CR 后: 敌侧经济完整参战）。"""
        sim, vm, _ = make_game(level_name="multi_01")
        b0 = bot.Bot(gather_ants=10, attack_unit="wasp",
                     attack_lanes=(0,), garrison=12, attack_every=10, side=0)
        b1 = bot.Bot(gather_ants=10, attack_unit="wasp",
                     attack_lanes=(0,), garrison=12, attack_every=10, side=1)
        dt = run_game(sim, vm, [b0, b1], max_ticks=8000)   # 攻巢=自杀后 wasp(HiveDamage1) 需更多波次拆 10HP 巢
        self.assertIsNotNone(sim.winner, f"未终局 (tick={sim.tick}, 墙钟 {dt:.1f}s)")
        self.assertIn(sim.winner, (0, 1))
        kinds = [e[1] for e in sim.events]
        # 敌侧实际参战（采集入账+买兵; CR 次要-4——严重-1 饿死会被此断言暴露）
        self.assertTrue(any(e[1] == "deposit" and e[2][0] == 1
                            for e in sim.events), "敌侧采集未入账")
        self.assertTrue(any(e[1] == "buy" and e[2][0] == 1
                            for e in sim.events), "敌侧未买兵")
        destroyed = next(e for e in sim.events if e[1] == "hive_destroyed")
        self.assertEqual(destroyed[2][0], 1 - sim.winner)   # 被毁=败方巢
        self.assertEqual(kinds[-1], "victory")
        self.assertLess(dt, 60.0)

    def test_eighteen_multi_levels_smoke(self):
        """出口: 18 multi 关装载+500t 回放无异常且不误判（botless+死线
        12010t≫500t 下 winner 只能 None; CR 次要-3 恒真断言修正）。"""
        for name in MULTI_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                self.assertIsNotNone(sim.defense_deadline, name)
                run_game(sim, vm, None, max_ticks=500)
                self.assertIsNone(sim.winner, name)


CHALLENGE_LEVELS = [f"challenge_{i:02d}" for i in range(1, 6)]

BATTLE_LEVELS = ["level_02", "level_03", "level_05", "level_08", "level_09",
                 "level_11", "level_18", "level_20", "level_23", "level_24",
                 "level_25"]

# 62 可玩关（8 类型除去 menu）——T6.8 合并回放全集
PLAYABLE_LEVELS = sorted(BATTLE_LEVELS + DEFENSE_LEVELS + GATHER_LEVELS
                         + RESCUE_LEVELS + MULTI_LEVELS + CHALLENGE_LEVELS)


class TestBattleE2E(unittest.TestCase):
    """T6.8: battle 11 关冒烟——装载+500t botless 回放无异常且不误判。"""

    def test_eleven_battle_levels_smoke(self):
        for name in BATTLE_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                run_game(sim, vm, None, max_ticks=500)
                self.assertIn(sim.winner, (None, 0, 1), name)


class TestReplayRegression(unittest.TestCase):
    """T6.8: 62 关合并回放——无异常 / 胜负不误判 / 单位数包络 / 墙钟预算。"""

    def test_all_playable_levels_replay(self):
        self.assertEqual(len(PLAYABLE_LEVELS), 62)
        t0 = time.time()
        for name in PLAYABLE_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                run_game(sim, vm, None, max_ticks=500)
                self.assertIn(sim.winner, (None, 0, 1), name)
                if sim.winner == 1:                          # 负⟹我巢破（500t 无超时）
                    self.assertLessEqual(sim.hives[0].hp, 0, name)
                self.assertLess(len(sim.bugs), 200, name)     # 单位数包络（防失控出生）
        self.assertLess(time.time() - t0, 600.0)              # 墙钟 < 10min


class TestChallengeE2E(unittest.TestCase):
    """T6.6: challenge 关——生存模式（Objective=SURVIVELONG, 胜负总函数 0x48E830
    "四 Type" 不含 challenge）无胜出分支，仅公共负路径 0x49261a 我巢破→负。"""

    def test_five_challenge_levels_no_win(self):
        """5 challenge 关装载+500t 回放无异常，且 winner 永不 0（无胜出条件）。"""
        for name in CHALLENGE_LEVELS:
            with self.subTest(level=name):
                sim, vm, _ = make_game(level_name=name)
                run_game(sim, vm, None, max_ticks=500)
                self.assertIn(sim.winner, (None, 1), name)   # 永不 0

    def test_challenge_base_destroyed_is_loss(self):
        """我巢破 → 负（公共负路径），非胜出。"""
        sim, vm, _ = make_game(level_name="challenge_01")
        sim.hives[0].hp = 0
        sim._check_victory()
        self.assertEqual(sim.winner, 1)
        self.assertEqual([e[2][0] for e in sim.events if e[1] == "victory"], [1])


if __name__ == "__main__":
    unittest.main()
