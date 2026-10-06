"""T4.5: scriptvm——脚本时间轴/免费出兵/胜负/no-op 组（合成+level_02）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits import level as levelmod, unitdb, worlddb  # noqa: E402
from bugbits import sim as simmod  # noqa: E402
from bugbits import scriptvm  # noqa: E402
from bugbits.level import LevelData  # noqa: E402
from bugbits.worlddb import Start, Waypoint, WorldData  # noqa: E402


def synth_world():
    starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
              Start("E", (200, 0, 0), (0, 0, 1), 1, 0, [])]
    wps = [Waypoint("wp", (100, 0, 0), (0, 0, 1), False, [])]
    adj = {"A": {"wp"}, "wp": {"A", "E"}, "E": {"wp"}}
    return WorldData({}, [], [], None, starts, wps, 2, adj, None)


def synth_level(scripts, itype="battle", goal=None):
    props = {"InitialNectar": ["10"], "NectarOnPaths": ["0"],
             "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"], "Type": [itype]}
    if goal is not None:
        props["GoalNectar"] = [str(goal)]
    return LevelData(props, [], [], scripts, None)


def make_vm(scripts, seed=42, itype="battle", goal=None):
    units = unitdb.load_all()
    sim = simmod.Sim(synth_level(itype=itype, goal=goal, scripts=scripts),
                     synth_world(), units, seed)
    return scriptvm.ScriptVM(sim, sim.level), sim


class TestSpawnFree(unittest.TestCase):
    def test_sendenemy_spawns_free(self):
        vm, sim = make_vm([("sendenemy", ["littlebeetle", "0", "D_NONE", "5"])])
        wallet = sim.nectar[1]
        vm.run(1)
        spawned = [b for b in sim.bugs if b.unit_name == "littlebeetle"]
        self.assertEqual(len(spawned), 1)  # 末参是对话参数，不是数量
        self.assertEqual(sim.nectar[1], wallet)          # 免费
        self.assertTrue(all(b.side == 1 and b.mode == "lane" for b in spawned))

    def test_sendplayer_free(self):
        vm, sim = make_vm([("sendplayer", ["bee", "0", "D_02_WHY", "2"])])
        vm.run(1)
        spawned = [b for b in sim.bugs if b.unit_name == "bee" and b.side == 0]
        self.assertEqual(len(spawned), 1)
        self.assertEqual(sim.nectar[0], 10)              # 不扣费

    def test_sendenemy_ignores_null_duration(self):
        vm, sim = make_vm([("sendenemy", ["ant", "0", "null", "10.3"])])
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)

    def test_noop_group_logs(self):
        vm, sim = make_vm([("setlight", ["20", "ffc0c0ff"]),
                           ("addhint", ["HINT_DAMAGEDBASE"]),
                           ("sethintfreq", ["30"]),
                           ("sp", ["AirDefenseLevel", "3"]),
                           ("removehint", ["HINT_RMB"])])
        vm.run(5)   # 每 tick 恰一条（NC-02-MECH A3）：5 条 no-op 需 5 tick
        # 不触 sim 实体/经济（hash 含 tick 不比; 比不变量）
        self.assertEqual(len(vm.log), 5)
        self.assertEqual(sim.bugs, [])
        self.assertEqual(sim.nectar, {0: 10, 1: 0})
        self.assertEqual([e[1] for e in sim.events], [])  # 无任何 sim 事件


class TestWaitAndVictory(unittest.TestCase):
    def test_wait_blocks_timeline(self):
        # wait 于首个 on_tick(t=1) 起算: wait 5 → k=ceil(5·20)=100 减帧，
        # 到期过渡帧 t101 仍阻塞（state1→4 恢复帧，不消费），t102 才消费下一条出兵。
        # 旧预期 t101 出兵错在：把「到期帧恢复」与「下一帧消费」压到同一 tick；
        # 新预期独立来源 = EXE state1 0x482669 写 state4 与 state4 0x4826a3 pop
        # 严格相邻两帧（research/nc02_wait_boundary.py q3）。
        vm, sim = make_vm([("wait", ["5"]),
                           ("sendenemy", ["ant", "0", "null", "1"])])
        vm.run(101)
        self.assertEqual(len(sim.bugs), 0)               # t101 到期过渡帧仍阻塞
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)  # t102 出兵

    def test_waituntilnectar_blocks(self):
        # 阈值 9 ≤ 初始 10 → t1 消费 waituntilnectar、t2 达标恢复帧（不消费）、t3 消费
        # 下一条（与 wait 到期过渡帧同构，research/nc02_waituntilnectar.py state2→state4）。
        vm, sim = make_vm([("waituntilnectar", ["9"]),
                           ("sendenemy", ["ant", "0", "null", "1"])])
        vm.run(2)                                     # t1 消费 + t2 恢复帧
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)
        vm.run(1)                                     # t3 出兵
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)
        # 阈值 50 → 阻塞至达标
        vm2, sim2 = make_vm([("waituntilnectar", ["50"]),
                             ("sendenemy", ["ant", "0", "null", "1"])])
        vm2.run(200)
        self.assertEqual(len(sim2.bugs), 0)           # 阻塞中
        sim2.nectar[0] = 50
        vm2.run(1)                                    # 达标恢复帧（不消费）
        self.assertEqual(len([b for b in sim2.bugs if b.side == 1]), 0)
        vm2.run(1)                                    # 下一帧出兵
        self.assertEqual(len([b for b in sim2.bugs if b.side == 1]), 1)

    def test_victory_battle_player_wins(self):
        vm, sim = make_vm([])
        # H15/W3: 攻巢=自杀 → 摧毁 3 HP 敌巢需 3 只 littlebeetle 各一击(HiveDamage 1)。
        for _ in range(3):
            sim.lane_cd_until.clear()   # 清冷却（装配 3 攻巢者，不验冷却门禁）
            b = sim.buy(0, "littlebeetle", 0)
            b.mode = "lane"
            b.cur_pos = (200, 0, 0)
            b.progress_sub = b.route_len_sub - 1
        vm.run(80)
        self.assertEqual(sim.winner, 0)

    def test_victory_battle_enemy_wins(self):
        vm, sim = make_vm([])
        sim.hives[0].hp = 1
        b = sim.spawn_free(1, "littlebeetle", 0)
        b.mode = "lane"
        b.cur_pos = (0, 0, 0)
        b.progress_sub = b.route_len_sub - 1
        vm.run(80)
        self.assertEqual(sim.winner, 1)

    def test_victory_gather(self):
        vm, sim = make_vm([], itype="gather", goal=13)
        vm.run(1)
        self.assertIsNone(sim.winner)
        sim.nectar[0] = 13
        vm.run(1)
        self.assertEqual(sim.winner, 0)


class TestSetflowPhaseMachine(unittest.TestCase):
    """H5 校准: setflow=泳道相位状态机(非预算模型)——A 间隔/B 活跃/C 休止。"""

    def _lane_level(self, scripts, setups=None, lanes=None):
        # 注: 空列表是合法入参(test_no_setlanes_no_spawn) → 用 is None 判默认,
        # 不可用 `or`(空列表为假会把 lanes=[] 换成默认路线池)
        setups = [(0, "ant", 100)] if setups is None else setups
        lanes = [(0, 0)] if lanes is None else lanes
        return LevelData({"InitialNectar": ["10"], "NectarOnPaths": ["0"],
                          "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"],
                          "Type": ["battle"]},
                         setups, lanes, scripts, None)

    def test_setflow_immediate_spawn_then_rest(self):
        # setflow(0, A=10s=200t, B=20s=400t, C=30s=600t): 下一帧立即出 1 只
        # (acc1=0≤0) → acc2≤0 → acc2=C 转休止; 休止 600t 内不出
        lv = self._lane_level([("setflow", ["0", "10", "20", "30"])])
        units = unitdb.load_all()
        sim = simmod.Sim(lv, synth_world(), units, 42)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)   # 立即 1 只
        self.assertEqual(sim.nectar[1], 0)     # H5: 无预算扣减/收入(免费)
        vm.run(599)                            # t600 休止中
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)
        vm.run(2)                              # t602: acc2 耗尽转活跃, 首帧再出 1
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 2)

    def test_active_phase_interval_spawns(self):
        # A=5s=100t, B=20s=400t, C=0: 活跃相每 100t 尝试出 1 只；但 OFR-02B/PBA-12
        # 脚本也经 SpawnUnit，受每泳道 +0x22c 冷却(10s=200t)门禁——setflow 相位机
        # 想每 100t 出一只，但冷却每 200t 才放行一次 → 520t 内实际 3 只
        # （约 t≈1 / t≈203 / t≈404，相位机其余尝试被冷却拒绝）。
        # H5 asm 语义(exe-econ.md §5)仅证相位机时序，未含冷却门禁；冷却为叠加门。
        lv = self._lane_level([("setflow", ["0", "5", "20", "0"])])
        sim = simmod.Sim(lv, synth_world(), unitdb.load_all(), 42)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(520)
        n = len([b for b in sim.bugs if b.side == 1])
        self.assertEqual(n, 3, n)

    def test_no_setlanes_no_spawn(self):
        # W4: SetLanes 路线池空 → 永不出兵
        lv = self._lane_level([("setflow", ["0", "5", "20", "0"])], lanes=[])
        sim = simmod.Sim(lv, synth_world(), unitdb.load_all(), 42)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(1000)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)

    def test_weighted_lottery_by_budget(self):
        # BugSetup 花蜜值=抽签权重: littlebeetle 90 vs bee 10 → 长跑频率 ≈ 9:1
        lv = self._lane_level([("setflow", ["0", "2", "10000", "0"])],
                              setups=[(0, "littlebeetle", 90), (0, "bee", 10)],
                              lanes=[(0, 0)])
        sim = simmod.Sim(lv, synth_world(), unitdb.load_all(), 7)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(1200)
        names = [b.unit_name for b in sim.bugs if b.side == 1]
        self.assertGreater(names.count("littlebeetle"), names.count("bee"))
        self.assertEqual(sim.nectar[1], 0)     # 零扣减

    def test_onfield_cap_twenty(self):
        # 在场敌方 ≥20 → 不再出兵(0x481CC7 cmp 0x14)
        lv = self._lane_level([("setflow", ["0", "1", "100000", "0"])])
        sim = simmod.Sim(lv, synth_world(), unitdb.load_all(), 42)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(3000)
        alive = [b for b in sim.bugs if b.side == 1 and not b.dead]
        self.assertLessEqual(len(alive), 20)

    def test_level_02_replay_determinism(self):
        """出口条件: level_02 headless 两次运行逐 tick 状态 hash 一致。"""
        runs = []
        for _ in range(2):
            w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
            lv = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
            sim = simmod.Sim(lv, w, unitdb.load_all(), seed=2026)
            vm = scriptvm.ScriptVM(sim, lv)
            out = []
            for _ in range(36):                          # 3600t = 3 分钟
                vm.run(100)
                out.append((sim.tick, sim.state_hash(), vm.state_repr()))
            runs.append(out)
        self.assertEqual(runs[0], runs[1])
        # 敌方确有脚本/相位机出兵（回放非空转; H5 后敌无钱包全免费出生）
        sim = None
        w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
        lv = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
        sim = simmod.Sim(lv, w, unitdb.load_all(), seed=2026)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(3600)
        self.assertTrue(any(e[1] == "spawn_free" for e in sim.events))

    def test_level_02_enemy_spawn_rate_envelope(self):
        """H5 校准后出口: level_02 敌方(相位机)自然出兵速率 ∈ [0.5, 2]× 引擎推算值。

        引擎推算: lane0 (20,40,40)→2 只/80s + lane1 (10,30,30)→3 只/60s
        ≈ 4.5 只/min (W4 §6); 本实现自然速率 = lane0 3只/80s + lane1 3只/60s
        ≈ 5.25 只/min。
        隔离跑(无 bot)敌方后期无伤亡 → 引擎真值门「在场敌方<20」(0x481CC7)
        会饱和钳制, 满窗 [1210,6610) 速率被低估(实测 8 只/5.5min≈1.45);
        故按事件重放定位首个饱和点 t_cap, 以饱和前段 [1210, t_cap] 计自然速率
        (计划稿满窗口径在引擎 20 门下不可达, 此为语义等价修正)。
        """
        w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
        lv = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
        lv.props["PlayerBaseSize"] = ["100000"]          # 测试隔离: 不测战斗胜负
        sim = simmod.Sim(lv, w, unitdb.load_all(), seed=2026)
        vm = scriptvm.ScriptVM(sim, lv)
        vm.run(6600)
        self.assertIsNone(sim.winner)                    # 隔离生效(窗口未被胜负截断)
        # 事件重放求在场敌方曲线 → 首个饱和点 t_cap(第 20 只存活出生 tick)
        side_of, alive, t_cap = {}, 0, 6610
        for t, kind, d in sim.events:
            if kind in ("spawn_free", "buy"):
                side_of[d[3]] = d[0]
                if d[0] == 1:
                    alive += 1
                    if alive >= 20:
                        t_cap = t
                        break
            elif kind == "death" and side_of.get(d[0]) == 1:
                alive -= 1
        window = [e for e in sim.events
                  if e[1] == "spawn_free" and 1210 <= e[0] <= t_cap]
        per_min = len(window) / ((t_cap - 1210) / 1200.0)
        self.assertGreaterEqual(per_min, 2.2, per_min)   # ≥ 0.5× 引擎 4.5/min
        self.assertLessEqual(per_min, 9.0, per_min)      # ≤ 2× 引擎 4.5/min
        # 引擎门钳制在真实关卡数据上成立
        alive_end = sum(1 for b in sim.bugs if b.side == 1 and not b.dead)
        self.assertLessEqual(alive_end, 20)

    def test_eleven_battle_levels_smoke(self):
        """出口条件: 11 个 battle 关全量装载 + 回放冒烟（600t 无异常）。"""
        battles = []
        for f in sorted(os.listdir(data_dir("scripts", "levels"))):
            if not f.endswith(".vsc"):
                continue
            lv = levelmod.parse_level(data_dir("scripts", "levels", f))
            if lv.type == "battle":
                battles.append((f[:-4], lv))
        self.assertEqual(len(battles), 11)
        for name, lv in battles:
            w = worlddb.parse_world(data_dir("worlds", lv.world_name + ".vsc"))
            sim = simmod.Sim(lv, w, unitdb.load_all(), seed=7)
            vm = scriptvm.ScriptVM(sim, lv)
            vm.run(600)
            self.assertIn(sim.winner, (None, 0, 1), name)   # 不误触胜负
            self.assertLess(sim.tick, 700, name)             # 未因胜负提前停则正常推进


if __name__ == "__main__":
    unittest.main()
