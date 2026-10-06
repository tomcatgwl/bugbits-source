"""Script 解释器与敌波编排（T4.5; T5.6 H5 校准重写）。

10 子命令状态机（时间轴 = 文件序）：只经 sim 公共接口发指令（D4）。
语义定调（登记 hypotheses-runtime.md; H5 定点 = T5.5 asm, docs/exe-econ.md §5）:
  wait 秒 / waituntilnectar N        阻塞推进
  sendenemy 单位 路线 对话 延迟参数  免费敌方出兵恰1只（H19: 路线号 START Index）
  sendplayer 单位 路线 对话 延迟参数 免费我方增援恰1只
  H6: 对话!=null 时末参进入显示延迟；计时/AI等待已接入，相机/物理仍有差异
      见 docs/runtime-calibration.md，不能把数量修正宣称为完整命令保真。
  setflow 泳道 A B C                 H5 定点: 泳道出兵相位状态机参数重装载——
                                      A=出兵间隔秒(A==0 关闭)/B=活跃相秒/C=休止相秒;
                                      清累加器、相位字节不写;
                                      无预算/花蜜扣减, BugSetup 花蜜值=抽签权重
  setlight 保存请求及固定20Hz的有限光照过渡状态；其余表现命令 no-op 记 log
敌方无钱包（H5/H11e: 预算模型整体证伪）: setflow 相位机 + sendenemy 单只全部
免费出生, sim.nectar[1] 恒 ENEMY_START_NECTAR（敌方收入维度不存在）。
[切片取舍: 依据 H5] 空军支(AirDefenseLevel 8 案换种+威慑评分)不建模;
引擎相位机 rng=[cLevel+0xA0] LCG → 本切片共用 sim.rng（D3 确定性手段, 非复刻）。
时间轴消费节奏（NC-02-MECH A3 STATIC）: 每 tick 恰消费一条命令——对齐原作
cLevel::Update 每帧 pop 一条（state4 0x4826a3 无 while 循环），固定 20Hz 步长
近似原作变步长 Update，非逐帧逐字节等价。
wait 恢复边界（NC-02 WAIT-BOUNDARY STATIC, research/nc02_wait_boundary.py）:
  wait D 到期那一帧只恢复 state1→4、不消费；下一帧（state4）才消费下一条。
  wait_until 语义 = 「最后一个仍阻塞的 tick（含）」，_blocked() 用 tick<=wait_until
  承载该到期过渡帧；离散化 k=ceil(D·TICK_HZ) 个减帧 → 下一条消费于 T0+k+1。
  wait 0 在 EXE 下无限阻塞（0.0==remaining 分支永不转 state4），数据无 wait 0，
  本实现映射 0 阻塞 tick（分歧登记于 out RESULT.md，见 research 脚本 q4）。
  waituntilnectar 生命周期（NC-02 WAIT-NECTAR STATIC, research/nc02_waituntilnectar.py）:
    waituntilnectar N 命令处理器 0x480578 写 state=2 + 阈值存 [cLevel+0x104]；state2
    处理器 0x482671 轮询 [Player0+0x180]（NectarCount int）≥ 阈值 → 0x482698 写 state=4
    （一次性退出）。达标当帧仅恢复门、不消费，下一帧 state4 才 pop 下一条——与 wait 到期
    过渡帧同构。退出后旧阈值不再参与门禁（state4 不读 [ebp+0x104]；只有下一条
    wait/waituntilnectar 才重写）。sim 用 wait_nectar 承载门（None=无门），on_tick 在
    条件检测后单帧清除，避免「已放行阈值重新阻塞后续命令」。
"""
import math

from bugbits.sim import consts
from bugbits.level import light_tokens
from bugbits.presentation_light import LightState


class ScriptVM:
    def __init__(self, sim, level):
        self.sim = sim
        self.level = level
        self.cursor = 0              # 下一条待执行脚本序号
        self.wait_until = -1         # 无等待哨兵；否则 = 最后一个仍阻塞的 tick（含）
        self.wait_nectar = None      # waituntilnectar 阈值
        self.flows = {}              # lane -> {"A","B","C","acc1","acc2","rest"}
        self.log = []                # 表现类子命令记录 [(tick, sub, args)]
        self._light_request = None
        self._light_state = LightState()
        for args in level.light_requests:
            self._light_state.accept(args, 0, 'level')
            self._light_request = (0, 'level', light_tokens(args))

    def light_request(self):
        """A detached JSON request, not a claim about original light state."""
        if self._light_request is None:
            return None
        tick, source, args = self._light_request
        return {'args': list(args), 'tick': tick, 'source': source,
                'scope': 'raw-vsc-request-v1'}

    def light_state(self):
        """Detached fixed-tick STATIC arithmetic; no original frame claim."""
        return self._light_state.snapshot()

    # ── 时间轴推进 ──────────────────────────────────────────────────────
    def _blocked(self):
        # wait_until = 最后一个仍阻塞的 tick（含）：到期过渡帧（tick==wait_until）仍阻塞，
        # 对齐原作「wait 到期帧只恢复 state1→4、下一帧 state4 才消费」。-1 = 无等待。
        # wait_nectar = waituntilnectar 阈值（None=无门）：达标后的「恢复帧」由 on_tick 在
        # 条件检测后单帧清除（state2→state4，research/nc02_waituntilnectar.py），此处仅在
        # 仍等待阶段（nectar<阈值）判定阻塞；达标后旧阈值不参与门禁。
        if self.sim.tick <= self.wait_until:
            return True
        if self.wait_nectar is not None and self.sim.nectar[0] < self.wait_nectar:
            return True
        return False

    def _exec(self, sub, args):
        sim = self.sim
        if sub == "wait":
            # EXE state1 每帧减 dt（remaining−dt），耗尽(<=0)当帧写回 state4、下一帧才消费
            # （research/nc02_wait_boundary.py q1/q2/q3）。离散化：k=ceil(D·TICK_HZ) 个减帧；
            # wait_until=T0+k=最后一个仍阻塞 tick，下一条消费于 T0+k+1。数据 wait 均为整数秒。
            k = int(math.ceil(float(args[0]) * consts.TICK_HZ))
            self.wait_until = sim.tick + k
        elif sub == "waituntilnectar":
            self.wait_nectar = int(args[0])
        elif sub in ("sendenemy", "sendplayer"):
            bug = sim.spawn_free(int(sub == "sendenemy"), args[0], int(args[1]))
            if bug is not None and args[2] != "null":
                sim.set_dialogue(bug, args[2], float(args[3]))
                sim.focus_camera(bug)
        elif sub == "setflow":
            lane = int(float(args[0]))
            a, b, c = (float(x) for x in args[1:4])
            hz = consts.TICK_HZ
            # H5: 清累加器(→相位机当帧立即出 1 只), 相位字节不写=沿用原相位
            rest = bool(self.flows[lane]["rest"]) if lane in self.flows else False
            self.flows[lane] = {"A": int(round(a * hz)), "B": int(round(b * hz)),
                                "C": int(round(c * hz)), "acc1": 0, "acc2": 0,
                                "rest": rest}
        elif sub == 'setlight':
            self.log.append((sim.tick, sub, tuple(args)))
            # Historical synthetic partial commands remain logged, never used
            # as a valid lighting request. Real commands have nine raw tokens.
            if len(args) == 9:
                self._light_state.accept(args, sim.tick, 'script')
                self._light_request = (sim.tick, 'script', light_tokens(args))
        else:  # addhint/removehint/sethintfreq/sp → 表现类
            self.log.append((sim.tick, sub, tuple(args)))

    def on_tick(self):
        """脚本时间轴 + 泳道相位状态机（H5 校准, 引擎 0x480C80 每帧模型）。

        setflow(lane,A,B,C): A=出兵间隔秒(A==0 关闭) / B=活跃相秒 / C=休止相秒。
        每帧: 休止相 acc1 钉 0、acc2−=dt, 耗尽→acc2=B 转活跃; 活跃相 acc1/acc2
        −=dt, acc1≤0 且在场敌方<20 → acc1=A 出兵; acc2≤0→acc2=C 转休止
        (C=0 → 休止 1 帧即回活跃 = 周期边界双生, 引擎同款)。
        出兵 = BugSetup 花蜜值加权抽签 + SetLanes 路线池随机(池空不出)。
        敌方无钱包(H5/H11e): 免费出生, sim.nectar[1] 恒 ENEMY_START_NECTAR。
        [切片取舍: 依据 H5] 空军支(AirDefenseLevel 8 案换种+威慑)不建模;
        脚本时间轴每 tick 恰消费一条命令（对齐原作每帧 pop 一条，NC-02-MECH A3，
        固定 20Hz 步长近似原作变步长 Update，非逐帧逐字节等价）；脚本时间轴先于
        相位机执行——引擎"setflow 后下一帧出 1"压缩为本帧出 1
        (整数 tick 下相位差 1, 时序断言已按此定值)。
        """
        sim = self.sim
        self._light_state.advance(sim.tick)
        # waituntilnectar 条件检测→状态恢复（EXE state2 0x48268f fcompp 判花蜜≥阈值 →
        # 0x482698 写 state=4，research/nc02_waituntilnectar.py）：达标当帧仅恢复门、不消费，
        # 下一帧 state4 才 pop 下一条（与 wait 到期过渡帧同构）。恢复后旧阈值不再参与门禁
        # （state2 是唯一把 [ebp+0x104] 当阈值做 fcompp 的状态处理器，state4 不读它）。
        releasing = False
        if self.wait_nectar is not None and sim.nectar[0] >= self.wait_nectar:
            self.wait_nectar = None
            releasing = True
        if not releasing and self.cursor < len(self.level.scripts) and not self._blocked():
            sub, args = self.level.scripts[self.cursor]
            self.cursor += 1
            self._exec(sub, args)
        for lane, f in sorted(self.flows.items()):
            if f["A"] <= 0:
                continue                                   # A==0 泳道关闭
            if f["rest"]:
                f["acc1"] = 0
                f["acc2"] -= 1
                if f["acc2"] <= 0:
                    f["acc2"] = f["B"]
                    f["rest"] = False
            else:
                f["acc1"] -= 1
                f["acc2"] -= 1
                if f["acc1"] <= 0:
                    f["acc1"] = f["A"]
                    self._spawn_lane(lane)
                if f["acc2"] <= 0:
                    f["acc2"] = f["C"]
                    f["rest"] = True

    def _spawn_lane(self, lane):
        """H5: 花蜜加权抽签 + SetLanes 路线池随机; 在场敌方<20 门(0x481CC7)。"""
        sim = self.sim
        alive = sum(1 for b in sim.bugs if b.side == 1 and not b.dead)
        if alive >= 20:                                    # 0x481CC7
            return
        cands = [(int(bg), u) for (l, u, bg) in self.level.bug_setups
                 if l == lane and u in sim.units]
        routes = [r for (l, r) in self.level.set_lanes if l == lane]
        if not cands or not routes:
            return
        total = sum(bg for bg, _ in cands)
        pick = sim.rng.uniform(0, total)
        acc = 0.0
        unit = cands[-1][1]
        for bg, u in cands:
            acc += bg
            if pick < acc:
                unit = u
                break
        sim.spawn_free(1, unit, sim.rng.choice(sorted(routes)))

    def run(self, n):
        for _ in range(n):
            self.sim.step()
            self.on_tick()
            if self.sim.winner is not None:
                break

    def state_repr(self):
        """解释器状态（确定性断言用; 与 sim.state_hash 分开比对）。"""
        flows = {l: (f["A"], f["B"], f["C"], f["acc1"], f["acc2"], int(f["rest"]))
                 for l, f in sorted(self.flows.items())}
        return f"cur{self.cursor}|w{self.wait_until}|n{self.wait_nectar}|f{flows}|log{len(self.log)}|light{self._light_request!r}"
