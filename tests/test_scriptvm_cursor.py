"""NC-02 / TA-CURSOR-IMPL：外层脚本游标（FIFO pop）语义的集成测试。

独立预期全部来自原 EXE 反汇编（STATIC，绝对 VA，ImageBase 0x400000；字节断言见
research/nc02_outer_cursor.py），不来自当前 VM 输出。三种结论区分（照上游 TA-CURSOR）：

1. handler null 返回 = 已证：SpawnUnit 0x4862eb 创建前查 +0x22c==0，非零返回空；
   sendenemy 0x4806ba `test edi,edi` / 0x4806bc `je 0x480c1d`（sendplayer 0x480839/
   0x48083b 对称）→ 共享 epilogue 0x480c32 `ret 0x4`，**不写 [cLevel+0x108]** →
   脚本状态保持 4 → 下一帧 0x4826a3 state4 处理器取队首 0x4826c4 call 0x402d60
   pop 队首（memmove + count--），执行下一条。
   ⇒ 失败出生 = 静默消费、无重试、无等待，下一条命令照常执行。

2. 外层游标 = FIFO 队首 + pop（0x402d60），非索引 inc。sim 的 cursor+=1 对
   「失败→下一条照常」功能等价（失败命令均被消费）。

3. 对话：出生成功且对话参数 != "null" 才进入显示延迟（H6）；wait 命令 0x480548
   `mov [edi+0x108],1` + 0x48055a `fstp [edi+0x104]` 写状态=1+秒，计时耗尽
   0x482669 `mov [ebp+0x108],ecx`(ecx=4) 恢复执行。null 仅作「不触发对话等待」负例。

[时序] 原作 cLevel::Update 每帧仅 pop 一条（state4 0x4826a3 每帧执行一次，无 while
循环；NC-02-MECH A3 STATIC）。本 sim 的 ScriptVM.on_tick 每 tick 恰消费一条
（`cursor += 1` 先增后执行 + if 单条），对齐原作每帧 pop 一条（固定 20Hz 步长
近似原作变步长 Update，非逐帧逐字节等价）。相邻两条命令间隔 ≥1 tick，连续 send*
不再同一 tick 同时出生（可用 test_one_command_per_tick 锚定）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir, vln  # noqa: E402
from bugbits import level as levelmod, unitdb, worlddb  # noqa: E402
from bugbits import sim as simmod  # noqa: E402
from bugbits import scriptvm  # noqa: E402
from bugbits.level import LevelData  # noqa: E402
from bugbits.sim import consts  # noqa: E402
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


_LANG4 = None


def lang4_keys():
    """有效 lang4 文本键集合（DATA：scripts/lang4.vln）。"""
    global _LANG4
    if _LANG4 is None:
        _LANG4 = set(vln.parse_vln(data_dir("scripts", "lang4.vln")).keys())
    return _LANG4


class TestFailedSpawnConsumption(unittest.TestCase):
    """handler null 返回 = 静默消费：失败出生后下一条命令照常，无重试无等待。"""

    def test_failed_sendenemy_consumed_then_next_command(self):
        # +0x22c 发射冷却门禁（SpawnUnit 0x4862eb）非零 → 返回 null → sendenemy
        # 0x4806ba je 0x480c1d（不写 [cLevel+0x108]）→ 状态保持 4 → 下一条照常执行。
        # 每 tick 恰消费一条（NC-02-MECH A3）：失败命令与下一条命令间隔 1 tick。
        vm, sim = make_vm([("sendenemy", ["ant", "0", "null", "1"]),
                           ("addhint", ["HINT_ANT"])])
        sim.lane_cd_until[(1, 0)] = sim.tick + consts.LANE_COOLDOWN_TICKS
        vm.run(1)
        self.assertEqual([b for b in sim.bugs if b.side == 1], [])  # 失败：无实体
        self.assertEqual(vm.cursor, 1)                              # 仅消费第一条
        self.assertEqual([e[1] for e in vm.log], [])                # 下一条未执行
        self.assertEqual(vm.wait_until, -1)                         # 无等待（-1 哨兵）
        self.assertIsNone(vm.wait_nectar)
        vm.run(1)
        self.assertEqual(vm.cursor, 2)                              # 下一 tick 执行下一条
        self.assertEqual([e[1] for e in vm.log], ["addhint"])       # 下一条照常执行

    def test_failed_sendplayer_consumed_then_next_command(self):
        # sendplayer 0x480839/0x48083b je 0x480c1d 与 sendenemy 对称。
        vm, sim = make_vm([("sendplayer", ["bee", "0", "null", "1"]),
                           ("addhint", ["HINT_ANT"])])
        sim.lane_cd_until[(0, 0)] = sim.tick + consts.LANE_COOLDOWN_TICKS
        vm.run(1)
        self.assertEqual([b for b in sim.bugs if b.side == 0], [])
        self.assertEqual(vm.cursor, 1)                              # 仅消费第一条
        self.assertEqual([e[1] for e in vm.log], [])
        self.assertEqual(vm.wait_until, -1)                         # 无等待（-1 哨兵）
        vm.run(1)
        self.assertEqual(vm.cursor, 2)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])

    def test_failed_spawn_not_retried_across_ticks(self):
        # 失败命令已被 pop（消费一次），冷却过期后也不会重试同一命令。
        vm, sim = make_vm([("sendenemy", ["ant", "0", "null", "1"])])
        sim.lane_cd_until[(1, 0)] = sim.tick + 2   # t1/t2 拒绝，t3 冷却过期
        vm.run(3)
        self.assertEqual([b for b in sim.bugs if b.side == 1], [])  # 永不重试
        self.assertEqual(vm.cursor, 1)                              # 命令已越过

    def test_unknown_unit_failed_spawn_consumed(self):
        # 未知兵种 → spawn_free 返回 None → 同 handler-null 分支，下一条照常。
        # （注：+0x22c 门禁是 STATIC 证据路径；未知兵种是 sim 层 null 返回路径，
        #   映射同一 0x4806ba/0x480839 je 分支，未单独取证。）
        vm, sim = make_vm([("sendenemy", ["nonexistent_bug_xyz", "0", "null", "1"]),
                           ("sendplayer", ["bee", "0", "null", "1"])])
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)
        self.assertEqual(len([b for b in sim.bugs if b.side == 0]), 0)  # 下一条未执行
        self.assertEqual(vm.cursor, 1)
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 0]), 1)  # 下一 tick 照常
        self.assertEqual(vm.cursor, 2)

    def test_success_then_same_lane_failure_consumed(self):
        # [sim 统一冷却模型回归，非原作同 tick 证据] 第一条 sendenemy 出生 ant 后，
        # sim 立即 arm 泳道冷却（_arm_lane_cd → lane_cd_until），紧邻同泳道第二条
        # wasp 被冷却门禁拒绝 → spawn 返回 null → 静默消费，第三条照常执行。
        # 证据归属：原作区分出生 arm +0x228（SpawnUnit 0x4863b6→0x49a750=2.0s）与
        # 发射 arm +0x22c（0x49a4c0=10.0s）；本用例「出生即 arm 泳道冷却」是 sim
        # 统一模型，不能据它断言原作同一 tick 会以 +0x22c 拒绝第二条。
        # 每 tick 恰消费一条（NC-02-MECH A3）：ant/wasp/addhint 分处三个连续 tick。
        vm, sim = make_vm([("sendenemy", ["ant", "0", "null", "1"]),
                           ("sendenemy", ["wasp", "0", "null", "1"]),
                           ("addhint", ["HINT_ANT"])])
        vm.run(1)
        self.assertEqual([b.unit_name for b in sim.bugs], ["ant"])   # 仅第一条出生
        self.assertEqual(vm.cursor, 1)
        vm.run(1)
        self.assertEqual([b.unit_name for b in sim.bugs], ["ant"])   # wasp 被冷却拒
        self.assertEqual(vm.cursor, 2)
        vm.run(1)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])
        self.assertEqual(vm.cursor, 3)
        self.assertEqual(vm.wait_until, -1)                         # 无等待（-1 哨兵）


class TestDialogueWait(unittest.TestCase):
    """对话分支：非 null 有效文本键 = 正例；null = 不触发对话等待的负例。"""

    def test_nonnull_valid_key_dialogue_applies_wait(self):
        # 正例必须用非 null 且 lang4 有效的文本键（fidelity-execution §4）。
        key = "D_01_THREAT"
        self.assertIn(key, lang4_keys())          # 有效文本键（DATA）
        vm, sim = make_vm([("sendenemy", ["littlebeetle", "0", key, "0.25"])])
        vm.on_tick()
        bug = sim.bugs[0]
        self.assertEqual(bug.dialogue_text, key)
        self.assertEqual(bug.dialogue_delay, 0.25)
        self.assertTrue(bug.dialogue_pending)
        sim.run(25)                               # trigger = ceil((0.25+1)*20)=25
        self.assertEqual([e[0] for e in sim.events if e[1] == "dialogue_wait"], [25])

    def test_null_dialogue_negative_control(self):
        # null 仅作「不触发对话等待」负例：不读末参、不计时、无等待事件。
        vm, sim = make_vm([("sendenemy", ["ant", "0", "null", "10.3"])])
        vm.on_tick()
        bug = sim.bugs[0]
        sim.run(50)
        self.assertEqual(bug.dialogue_age, -1)
        self.assertEqual(bug.dialogue_text, "")
        self.assertEqual([e for e in sim.events if e[1] == "dialogue_wait"], [])


class TestWaitAndTiming(unittest.TestCase):
    def test_wait_blocks_fifo_then_next_executes(self):
        # wait 0x480548 写 [cLevel+0x108]=1 + [cLevel+0x104]=秒，阻塞 FIFO 消费；
        # 计时耗尽 0x482669 写回 state=4（到期过渡帧仍阻塞），下一帧 state4 才 pop 下一条。
        vm, sim = make_vm([("wait", ["5"]),
                           ("sendenemy", ["ant", "0", "null", "1"])])
        vm.run(101)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)   # t101 到期过渡帧仍阻塞
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)   # t102 执行

    def test_one_command_per_tick(self):
        """锚定「每调用恰一条」= 对齐原作每帧 pop 一条（NC-02-MECH A3 STATIC）。

        原作 cLevel::Update 每帧仅 pop 一条（state4 0x4826a3 每帧执行一次，无 while
        循环）；sim 的 on_tick 每次调用恰消费一条（无 while 排空）。本测试两次 on_tick
        调用（中间无 sim.step()）仅证明「每调用恰一条」，**不声称跨 tick**——跨 tick
        节奏由 vm.run(n)（step→on_tick）类测试覆盖（见 TestWaitBoundaryTicks）。
        """
        vm, sim = make_vm([("sendenemy", ["ant", "0", "null", "1"]),
                           ("sendplayer", ["bee", "0", "null", "1"])])
        vm.on_tick()                                # 单次 on_tick（无 step）
        self.assertEqual(len(sim.bugs), 1)          # 每调用恰一条：仅第一条出生
        self.assertEqual(vm.cursor, 1)
        vm.on_tick()                                # 再次调用（仍无 step）：恰一条
        self.assertEqual(len(sim.bugs), 2)
        self.assertEqual(vm.cursor, 2)


class TestWaitBoundaryTicks(unittest.TestCase):
    """NC-02 wait 恢复边界（STATIC, research/nc02_wait_boundary.py）——vm.run(n) 逐 tick。

    独立预期来自 EXE state1/state4 状态转移（不来自当前 sim 输出）：
    wait D 于 tick T0 消费 → k=ceil(D·TICK_HZ) 个减帧 → 到期过渡帧 T0+k 仍阻塞
    （state1→4 恢复帧，不消费）→ 下一条消费于 T0+k+1。
    """

    def test_wait_positive_at_expiry_still_blocked(self):
        # 期限前(t100)/期限当(t101=到期过渡帧)/期限后(t102) 三分界。
        vm, sim = make_vm([("wait", ["5"]),
                           ("sendenemy", ["ant", "0", "null", "1"])])
        vm.run(100)                                    # t100（期限前）
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)
        self.assertEqual(vm.cursor, 1)                 # 仍指向下一条
        vm.run(1)                                      # t101 = 到期过渡帧（仍阻塞）
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)
        self.assertEqual(vm.cursor, 1)                 # 恢复帧不消费
        vm.run(1)                                      # t102（期限后）
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)
        self.assertEqual(vm.cursor, 2)

    def test_wait_zero_divergence(self):
        # EXE(STATIC q4)：wait 0 → [0x104]=0.0 → state1 首帧 fcom 0.0==0.0 → jnp
        # 0x482615 跳过且不写 state4 → 无限阻塞。数据普查无 wait 0（全整数≥5s）。
        # sim 当前映射 k=ceil(0)=0 → 0 阻塞 tick，下一条次 tick 消费（分歧登记 RESULT）。
        vm, sim = make_vm([("wait", ["0"]),
                           ("sendenemy", ["ant", "0", "null", "1"])])
        vm.run(2)                                      # t1 消费 wait0，t2 消费下一条
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)
        self.assertEqual(vm.cursor, 2)

    def test_two_consecutive_waits(self):
        # 两条 wait 相邻：每条到期都经 1 帧过渡，第二条消费后重新起算。
        vm, sim = make_vm([("wait", ["5"]), ("wait", ["5"]),
                           ("sendenemy", ["ant", "0", "null", "1"])])
        # wait#1 t1 消费，阻塞 t2..t101；wait#2 t102 消费，阻塞 t103..t202；
        # sendenemy t203 消费。
        vm.run(202)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 0)  # t202 仍阻塞
        self.assertEqual(vm.cursor, 2)
        vm.run(1)
        self.assertEqual(len([b for b in sim.bugs if b.side == 1]), 1)  # t203 出兵
        self.assertEqual(vm.cursor, 3)


class TestWaitUntilNectarLifecycle(unittest.TestCase):
    """NC-02 waituntilnectar 阈值等待完整生命周期（STATIC, research/nc02_waituntilnectar.py）。

    独立预期来自 EXE state2 处理器 0x482671（fild [Player0+0x180] vs fld [ebp+0x104]
    阈值 → fcompp → test ah,0x41+jp：阈值>花蜜继续等，否则 0x482698 写 state=4），
    不来自当前 sim 输出。关键结论：**达标后一次性退出 state2→state4，退出后旧阈值
    不再参与门禁**（state4 不读 [ebp+0x104]）。与 wait 到期过渡帧同构：达标当帧仅恢复、
    下一帧消费下一条。
    """

    def test_released_does_not_regate_after_wallet_drop(self):
        # 核心反例（P0）：waituntilnectar 9 达标放行后，花蜜回跌到 9 以下不应重新阻塞
        # 后续命令（旧实现 _blocked() 持久重测 wait_nectar → 已退出的等待被重新门禁）。
        # 直接写钱包 = 机制夹具（生产路径见 test_release_survives_legal_buy）。
        vm, sim = make_vm([("waituntilnectar", ["9"]),
                           ("addhint", ["HINT_ANT"]),
                           ("addhint", ["HINT_NECTAR"])])
        vm.run(3)                                  # t1 消费 w9；t2 达标(10≥9)恢复帧；t3 消费 A
        self.assertEqual(vm.cursor, 2)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])
        self.assertIsNone(vm.wait_nectar)          # 一次性退出：阈值已清除
        sim.nectar[0] = 0                          # 花蜜回跌 < 阈值
        vm.run(1)                                  # t4 应继续消费 B（不被旧阈值重阻塞）
        self.assertEqual(vm.cursor, 3)
        self.assertEqual([e[1] for e in vm.log], ["addhint", "addhint"])

    def test_release_survives_legal_buy(self):
        # 生产路径：达标放行后经合法购买（sim.buy 扣花蜜）回跌到阈值下，后续命令仍推进。
        vm, sim = make_vm([("waituntilnectar", ["9"]),
                           ("addhint", ["HINT_ANT"]),
                           ("addhint", ["HINT_NECTAR"])])
        vm.run(3)                                  # t1 消费 w9；t2 恢复帧；t3 消费 A
        self.assertIsNone(vm.wait_nectar)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])
        b = sim.buy(0, "littlebeetle", 0, cost=5)  # 合法购买：10 → 5
        self.assertIsNotNone(b)
        self.assertEqual(sim.nectar[0], 5)         # 花蜜 5 < 阈值 9
        vm.run(1)                                  # t4 应继续消费 B
        self.assertEqual(vm.cursor, 3)
        self.assertEqual([e[1] for e in vm.log], ["addhint", "addhint"])

    def test_boundary_equal_releases(self):
        # 极性：完成 ⟺ 花蜜≥阈值（==阈值即放行）。阈值前(<N)阻塞、相等(==N)达标恢复、
        # 下一帧消费。
        vm, sim = make_vm([("waituntilnectar", ["50"]),
                           ("addhint", ["HINT_ANT"])])
        vm.run(2)                                  # t1 消费 w50；t2 花蜜10<50 阻塞
        self.assertEqual(vm.cursor, 1)
        self.assertEqual(sim.nectar[0], 10)
        sim.nectar[0] = 49                         # 阈值前
        vm.run(1)                                  # t3 仍阻塞
        self.assertEqual(vm.cursor, 1)
        self.assertEqual(vm.wait_nectar, 50)
        sim.nectar[0] = 50                         # 相等
        vm.run(1)                                  # t4 达标恢复帧（不消费）
        self.assertEqual(vm.cursor, 1)
        self.assertIsNone(vm.wait_nectar)          # 一次性退出
        vm.run(1)                                  # t5 消费下一条
        self.assertEqual(vm.cursor, 2)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])

    def test_boundary_above_releases(self):
        # 超过阈值(>N)即放行。
        vm, sim = make_vm([("waituntilnectar", ["50"]),
                           ("addhint", ["HINT_ANT"])])
        vm.run(1)                                  # t1 消费 w50
        self.assertEqual(vm.cursor, 1)
        sim.nectar[0] = 51                         # 超过
        vm.run(1)                                  # t2 达标恢复帧
        self.assertEqual(vm.cursor, 1)
        self.assertIsNone(vm.wait_nectar)
        vm.run(1)                                  # t3 消费下一条
        self.assertEqual(vm.cursor, 2)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])

    def test_initially_satisfied(self):
        # 初始已达标（10≥9）：t1 消费 w9、t2 恢复帧、t3 消费下一条（仍含 1 帧过渡）。
        vm, sim = make_vm([("waituntilnectar", ["9"]),
                           ("addhint", ["HINT_ANT"])])
        self.assertEqual(sim.nectar[0], 10)
        vm.run(2)                                  # t1 消费 + t2 恢复帧
        self.assertEqual(vm.cursor, 1)             # 恢复帧不消费
        self.assertIsNone(vm.wait_nectar)
        vm.run(1)                                  # t3 消费下一条
        self.assertEqual(vm.cursor, 2)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])

    def test_new_waituntilnectar_regates_with_new_threshold(self):
        # 旧 waituntilnectar 放行后，只有再次遇到新 waituntilnectar 才按新条件等待。
        vm, sim = make_vm([("waituntilnectar", ["9"]),
                           ("waituntilnectar", ["50"]),
                           ("addhint", ["HINT_ANT"])])
        vm.run(3)                                  # t1 消费 w9；t2 恢复帧；t3 消费 w50
        self.assertEqual(vm.cursor, 2)
        self.assertEqual(vm.wait_nectar, 50)       # 新阈值激活
        sim.nectar[0] = 0                          # 花蜜 0 < 50 → 阻塞
        vm.run(1)                                  # t4 阻塞
        self.assertEqual(vm.cursor, 2)
        self.assertEqual(vm.wait_nectar, 50)
        sim.nectar[0] = 50
        vm.run(2)                                  # t5 达标恢复帧 + t6 消费 addhint
        self.assertEqual(vm.cursor, 3)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])

    def test_waituntilnectar_then_wait_combination(self):
        # waituntilnectar 放行后紧接 wait：两条阻塞命令各自完整生命周期，互不残留。
        vm, sim = make_vm([("waituntilnectar", ["9"]),
                           ("wait", ["5"]),
                           ("addhint", ["HINT_ANT"])])
        vm.run(3)                                  # t1 消费 w9；t2 恢复帧；t3 消费 wait
        self.assertEqual(vm.cursor, 2)
        self.assertIsNone(vm.wait_nectar)          # w9 已一次性退出
        self.assertEqual(vm.wait_until, 3 + 100)   # wait 5 → ceil(5·20)=100 减帧
        vm.run(100)                                # t4..t103：t103 = 到期过渡帧（仍阻塞）
        self.assertEqual(vm.cursor, 2)
        vm.run(1)                                  # t104 消费 addhint
        self.assertEqual(vm.cursor, 3)
        self.assertEqual([e[1] for e in vm.log], ["addhint"])


if __name__ == "__main__":
    unittest.main()
