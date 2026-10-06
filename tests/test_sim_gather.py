"""T5.6 H11c: sim 采集=图巡逻——图行走+接触拾取+反向回巢+死亡掉蜜。

直线往返最近蜜源模型证伪(H11c): 引擎=图巡逻+物理接触(0x49BFA0 扫描)+
Returning 即时反向。合成图: A(0,0)-wp(100,0)-E(200,0); ant Speed 22 → 1.1u/t。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import sim as simmod  # noqa: E402
from bugbits import unitdb  # noqa: E402
from bugbits.level import LevelData  # noqa: E402
from bugbits.worlddb import Flower as WFlower  # noqa: E402
from bugbits.worlddb import Start, Waypoint, WorldData  # noqa: E402


def world_with(flowers):
    starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
              Start("E", (200, 0, 0), (0, 0, 1), 1, 0, [])]
    wps = [Waypoint("wp", (100, 0, 0), (0, 0, 1), False, [])]
    adj = {"A": {"wp"}, "wp": {"A", "E"}, "E": {"wp"}}
    return WorldData({}, [WFlower(n, p, (0, 0, 1), 1) for n, p in flowers], [], None,
                     starts, wps, 2, adj, None)


def make_sim(world, seed=42):
    units = {"ant": unitdb.load_unit("ant")}
    lv = LevelData({"InitialNectar": ["10"], "NectarOnPaths": ["0"],
                    "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]}, [], [], [], None)
    return simmod.Sim(lv, world, units, seed)


def make_ready_sim(world, seed=42):
    """Controlled existing-honey precondition for movement/carry tests.

    Advance actual public Sim steps from a timer boundary to the type1 edge;
    this fixture does not claim natural first-birth timing (tested separately).
    """
    sim = make_sim(world, seed)
    for flower in sim.flowers:
        flower.cycle.timer = flower.cycle.threshold
    sim.run(68)
    return sim


def advance_bridge(bridge, ticks):
    """Respect the real public batch limit, including natural initial waits."""
    from bugbits.web_bridge import MAX_ADVANCE
    while ticks:
        count = min(MAX_ADVANCE, ticks)
        result = bridge.advance(count)
        if result.get('advanced') != count:
            raise AssertionError(result)
        ticks -= count


class TestFlowerCapacityAndRegen(unittest.TestCase):
    """R368: 单蜜槽、初始化动画停止；采蜜不重置独立timer。"""
    def test_capacity_is_one(self):
        s = make_sim(world_with([("F", (110, 0, 0))]))
        self.assertEqual(simmod.consts.FLOWER_CAPACITY, 1)
        self.assertEqual(s.flowers[0].nectar, 0)          # R368: 初始动画停止、槽为空

    def test_pickup_empties_without_resetting_flower_timer(self):
        s = make_ready_sim(world_with([("F", (110, 0, 0))]))
        s.buy(0, "ant", 0)
        s.run(31)
        timer = s.flowers[0].cycle.timer
        rng_state = s.flower_random.state
        s.step()
        self.assertEqual(s.flowers[0].nectar, 0)
        from bugbits.sim.nectar import f32
        self.assertEqual(s.flowers[0].cycle.timer, f32(timer + f32(.05)))
        self.assertEqual(s.flower_random.state, rng_state)

    def test_animation_edge_refills_single_slot(self):
        s = make_sim(world_with([("F", (110, 0, 0))]))
        s.flowers[0].cycle.timer = 30
        s.run(67)
        self.assertEqual(s.flowers[0].nectar, 0)
        s.step()
        self.assertEqual(s.flowers[0].nectar, 1)
        timer = s.flowers[0].cycle.timer
        s.step()
        self.assertGreater(s.flowers[0].cycle.timer, timer)  # 满槽不停止计时


class TestPatrolGather(unittest.TestCase):
    """H11c 校准: 图巡逻+接触拾取+反向回巢（直线往返最近蜜源证伪）。

    合成图: A(0,0)-wp(100,0)-E(200,0); 花 F(110,0) 落在 wp→E 段上。
    ant Speed 22 → 110u=2200sub=100t。
    """
    def test_patrol_pickup_and_deposit(self):
        # 巡逻路线 A→wp→E(蜜偏置=途经花所在边); 接触拾取 PICKUP_RADIUS=75:
        # t32 行至 x=35.2(距花 74.8≤75)拾取, 原段折返+回家 32t → t64 存款。
        # 时序为纯运动学定值(巡逻路径与半径决定, 与种子无关——评审 MINOR-3 更正)
        s = make_ready_sim(world_with([("F", (110, 0, 0))]))
        start_tick = s.tick
        b = s.buy(0, "ant", 0)
        self.assertEqual(b.mode, "patrol")                 # 出场即巡逻
        self.assertEqual(b.path_nodes[0], "A")             # 从本方 start 出发
        self.assertEqual(b.path_nodes, ("A", "wp", "E"))   # 途经花边 wp→E
        s.run(63)
        self.assertEqual(b.carrying, 1)                    # t32 接触拾取, 返程中
        self.assertEqual(s.nectar[0], 10)                  # 未到 64t 无存款
        s.step()
        self.assertEqual(s.tick, start_tick + 64)
        self.assertEqual(s.nectar[0], 13)                  # 存款 +3 (H11a)
        deposits = [e for e in s.events if e[1] == "deposit"]
        self.assertEqual([d[0] for d in deposits], [start_tick + 64])

    def test_path_item_pickup(self):
        # 路径蜜布在 A→wp 段 (44,0): 巡逻途经即接触拾取 + 回巢存款 + 再出发
        s = make_sim(world_with([]))
        s.path_nectar.append(simmod.NectarItem(0, (44, 0, 0)))
        b = s.buy(0, "ant", 0)
        s.run(80)
        self.assertTrue(s.path_nectar[0].taken)
        self.assertEqual(s.nectar[0], 13)                  # 10 + 3 (H11a)
        self.assertEqual(b.mode, "patrol")                 # 存款后再出发巡逻

    def test_far_end_turnaround_without_nectar(self):
        # 无蜜世界: 巡逻到敌方端点(E)掉头返程(引擎远端掉头 Returning=1)
        # (端点到达 t182 由后半断言锁定: 若未抵 E 则 x 不会回落)
        s = make_sim(world_with([]))
        b = s.buy(0, "ant", 0)
        s.run(182)                                         # 200u=4000sub→182t 抵 E
        pos_e = b.pos(s)
        self.assertAlmostEqual(pos_e[0], 200.0, places=1)  # 抵达敌方端点(当帧)
        s.run(200)
        # 已折返: 朝 A 走（x 坐标回落）
        self.assertLess(b.pos(s)[0], pos_e[0])

    def test_idle_stays_put(self):
        # 手动置 idle 的虫不自动巡逻(引擎 state1 待命; place() 类测试依赖)
        s = make_sim(world_with([("F", (110, 0, 0))]))
        b = s.buy(0, "ant", 0)
        b.mode = "idle"
        b.cur_pos = (0, 0, 0)
        s.run(50)
        self.assertEqual(b.mode, "idle")
        self.assertAlmostEqual(b.pos(s)[0], 0.0, places=1)

    def test_carry_drop_on_death_repositions(self):
        # W2: 携带者死亡 → 蜜弹回路径重布(近似: 蜜回花/原地重生为路径蜜)
        s = make_ready_sim(world_with([("F", (110, 0, 0))]))
        b = s.buy(0, "ant", 0)
        s.run(63)                                          # t32 拾取后返程中
        self.assertEqual(b.carrying, 1)
        b.hp = 0
        from bugbits.sim import combat
        combat._kill(s, b)
        self.assertEqual(b.carrying, 0)
        self.assertTrue(any(not it.taken for it in s.path_nectar))  # 蜜回场


class TestCalibrationReview(unittest.TestCase):
    """T5.6 核心评审发现项回归（MAJOR-1/2/4, MINOR-2）。"""

    def _world_branch(self):
        """A(0,0)-wp(100,0)-E(200,0) 主干(xz) + wp-B(100,0,100) z 向支线;
        另有孤岛 X(300,0)-Y(400,0)。坐标 (x,y,z) y 向上——平面几何写 x/z。"""
        starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
                  Start("E", (200, 0, 0), (0, 0, 1), 1, 0, [])]
        wps = [Waypoint("wp", (100, 0, 0), (0, 0, 1), False, []),
               Waypoint("B", (100, 0, 100), (0, 0, 1), False, []),
               Waypoint("X", (300, 0, 0), (0, 0, 1), False, []),
               Waypoint("Y", (400, 0, 0), (0, 0, 1), False, [])]
        adj = {"A": {"wp"}, "wp": {"A", "E", "B"}, "E": {"wp"}, "B": {"wp"},
               "X": {"Y"}, "Y": {"X"}}
        return WorldData({}, [], [], None, starts, wps, 2, adj, None)

    def test_bias_falls_back_to_reachable_edge(self):
        # MAJOR-1: 最近蜜在不可达分量(孤岛 X-Y 上的 F1)时, 偏置须回退到
        # 可达分量最近蜜(F2 @ wp-B 支线)——否则偏置整体失效退化为盲巡逻
        w = self._world_branch()
        w.flowers = [WFlower("F1", (350, 0, 0), (0, 0, 1), 1),      # 孤岛, 距边 0
                     WFlower("F2", (100, 0, 60), (0, 0, 1), 1)]     # wp→B 边上(xz 平面)
        s = make_ready_sim(w)
        b = s.buy(0, "ant", 0)
        self.assertEqual(b.path_nodes, ("A", "wp", "B"))  # 定向 F2, 非盲巡逻到 E

    def test_far_flower_pickup_across_worlds(self):
        # MAJOR-2: 全数据面花-最近图边距离实测 max=74.5u(world_08)——
        # PICKUP_RADIUS 须 ≥75 才不产生永久不可采花; 合成: 花距边 60u
        s = make_ready_sim(world_with([("F", (50, 0, 60))]))  # 明确已有蜜，距边60u
        s.buy(0, "ant", 0)
        s.run(200)
        self.assertEqual(s.nectar[0], 13)                 # 60u 外仍可接触拾取
        self.assertGreaterEqual(simmod.consts.PICKUP_RADIUS, 75.0)

    def test_single_node_patrol_no_crash(self):
        # MAJOR-4: 敌方 start 缺失的退化世界 → 单节点巡逻路径 + 40u 内出现蜜
        # 不得 IndexError（拾取检查守卫）
        starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, [])]
        wps = [Waypoint("wp", (100, 0, 0), (0, 0, 1), False, [])]
        adj = {"A": {"wp"}, "wp": {"A"}}
        w = WorldData({}, [WFlower("F", (30, 0, 0), (0, 0, 1), 1)], [], None,
                      starts, wps, 1, adj, None)
        s = make_sim(w)
        b = s.buy(0, "ant", 0)
        s.run(100)                                        # 退化世界不崩溃
        self.assertIn(b.mode, ("patrol", "idle"))

    def test_enemy_deposit_noop(self):
        # MINOR-2: H11e 敌方无钱包——敌采集虫交付不入账(单人无 Player1 对象)
        s = make_sim(world_with([("F", (190, 0, 0))]))    # 花近敌方 E 端
        s.spawn_free(1, "ant", 0)
        s.run(200)
        self.assertEqual(simmod.consts.ENEMY_START_NECTAR, 0)
        self.assertEqual(s.nectar[1], 0)                  # 敌方存款 no-op
        self.assertFalse(any(e[1] == "deposit" and e[2][0] == 1
                             for e in s.events))


if __name__ == "__main__":
    unittest.main()
