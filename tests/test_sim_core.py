"""T4.4a: sim 核心——整数 tick 时钟/买兵/状态 hash/事件日志（合成场景整数精确）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import unitdb  # noqa: E402
from bugbits import sim as simmod  # noqa: E402
from bugbits.level import LevelData  # noqa: E402
from bugbits.worlddb import Flower as WFlower  # noqa: E402
from bugbits.worlddb import Start, Waypoint, WorldData  # noqa: E402


def synth_world():
    """合成: 巢 A(0,0) 与花 F(110,0)（距 110 u = 2200 sub）; 敌巢 E(200,0) 经 wp 连通。"""
    starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
              Start("E", (200, 0, 0), (0, 0, 1), 1, 0, [])]
    wps = [Waypoint("wp", (100, 0, 0), (0, 0, 1), False, [])]
    adj = {"A": {"wp"}, "wp": {"A", "E"}, "E": {"wp"}}
    flowers = [WFlower("F", (110, 0, 0), (0, 0, 1), 1)]
    return WorldData({}, flowers, [], None, starts, wps, 2, adj, None)


def synth_world2():
    """合成双泳道: 我方 A0/A1、敌 E0/E1 各 2 泳道，每泳道独立路由（OFR-02B 跨泳道隔离）。"""
    starts = [Start("A0", (0, 0, 0), (0, 0, 1), 0, 0, []),
              Start("A1", (0, 20, 0), (0, 0, 1), 0, 1, []),
              Start("E0", (200, 0, 0), (0, 0, 1), 1, 0, []),
              Start("E1", (200, 20, 0), (0, 0, 1), 1, 1, [])]
    wps = [Waypoint("w0", (100, 0, 0), (0, 0, 1), False, []),
           Waypoint("w1", (100, 20, 0), (0, 0, 1), False, [])]
    adj = {"A0": {"w0"}, "w0": {"A0", "E0"}, "E0": {"w0"},
           "A1": {"w1"}, "w1": {"A1", "E1"}, "E1": {"w1"}}
    return WorldData({}, [], [], None, starts, wps, 4, adj, None)


def synth_level(initial=10, on_paths=0):
    return LevelData({"InitialNectar": [str(initial)], "NectarOnPaths": [str(on_paths)],
                      "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]}, [], [], [], None)


def make_sim(initial=10, on_paths=0, seed=42):
    units = {n: unitdb.load_unit(n) for n in ("ant", "littlebeetle", "bee")}
    return simmod.Sim(synth_level(initial, on_paths), synth_world(), units, seed)


class TestClockAndBuy(unittest.TestCase):
    def test_initial_state(self):
        s = make_sim()
        self.assertEqual(s.tick, 0)
        self.assertEqual(s.nectar[0], 10)   # InitialNectar
        self.assertEqual(s.nectar[1], 0)    # ENEMY_START_NECTAR
        self.assertEqual(s.hives[0].hp, 10)
        self.assertEqual(s.hives[1].hp, 3)
        self.assertEqual(s.bugs, [])

    def test_buy_free_ant(self):
        s = make_sim()
        b = s.buy(0, "ant", 0)
        self.assertIsNotNone(b)
        self.assertEqual(s.nectar[0], 10)   # Price 0 不扣
        self.assertEqual(b.mode, "patrol")    # CanGather → 图巡逻 (H11c)
        self.assertEqual(b.hp, 15)

    def test_buy_priced_and_refuse(self):
        # 价格/扣费路径（泳道冷却在单泳道合成世界会拦截连买 → 逐次清冷却隔离）
        s = make_sim(initial=10)
        self.assertIsNotNone(s.buy(0, "littlebeetle", 0))   # 3
        s.lane_cd_until.clear()                             # 只验价格，不验冷却
        self.assertIsNotNone(s.buy(0, "bee", 0))            # 3 → 余 4
        s.lane_cd_until.clear()
        self.assertIsNotNone(s.buy(0, "littlebeetle", 0))   # 3 → 余 1
        s.lane_cd_until.clear()
        self.assertIsNone(s.buy(0, "littlebeetle", 0))      # 余 1 < 3 拒绝
        self.assertEqual(s.nectar[0], 1)
        self.assertEqual(len(s.bugs), 3)

    def test_buy_lane_walker_non_gatherer(self):
        # bee CanGather=1 也是采集者 → 用合成非采集单位验证 lane 模式
        units = {"drone": unitdb.load_unit("wasp")}  # wasp CanGather=0
        units["drone"].can_gather = False
        s = simmod.Sim(synth_level(), synth_world(), units, 42)
        b = s.buy(0, "drone", 0)
        self.assertEqual(b.mode, "lane")     # 沿路线行军 (T4.4b 前无战斗)

    def test_buy_arms_reload_timer_display_only(self):
        # OF-02: ReloadTime 倒计时=纯展示非门禁（docs/exe-props.md §5.1）。
        # 真正门禁=泳道冷却（OFR-02B，见 TestLaneCooldown）；此处清冷却以隔离
        # ReloadTime 语义：冷却归零后同兵种立即可再买（ReloadTime 不 gate）。
        s = make_sim(initial=100)
        self.assertEqual(s.reload_until, {})
        self.assertIsNotNone(s.buy(0, "ant", 0))        # ant ReloadTime=15
        self.assertEqual(s.reload_until["ant"], 15 * 20)  # tick0 + 300
        s.lane_cd_until.clear()                          # 清冷却 → ReloadTime 仍倒计时但可再买
        self.assertIsNotNone(s.buy(0, "ant", 0))
        self.assertEqual(s.reload_until["ant"], 15 * 20)  # 重新 arm（重置）
        # 跨兵种各自独立计时
        s.lane_cd_until.clear()
        self.assertIsNotNone(s.buy(0, "littlebeetle", 0))  # littlebeetle ReloadTime=10
        self.assertEqual(s.reload_until["littlebeetle"], 10 * 20)
        self.assertEqual(s.reload_until["ant"], 15 * 20)

    def test_spawn_free_does_not_arm_reload(self):
        # OF-02: 脚本出兵（spawn_free）不经买兵命令 → 不 arm 倒计时。
        s = make_sim(initial=100)
        self.assertIsNotNone(s.spawn_free(1, "littlebeetle", 0))
        self.assertEqual(s.reload_until, {})

    def test_reload_timer_in_state_hash(self):
        # OF-02: reload_until 入 state_hash（确定性/审计）；OFR-02B: lane_cd_until 亦入。
        s1 = make_sim(initial=100)
        s2 = make_sim(initial=100)
        s1.buy(0, "ant", 0)
        s2.buy(0, "ant", 0)
        self.assertEqual(s1.state_hash(), s2.state_hash())
        s2.lane_cd_until.clear()          # 清冷却，隔离「额外买兵改变状态」语义
        s2.buy(0, "bee", 0)
        self.assertNotEqual(s1.state_hash(), s2.state_hash())


class TestLaneCooldown(unittest.TestCase):
    """OFR-02B: 每泳道冷却计时器（ceStart +0x228/+0x22c，买兵/脚本出生门禁）。"""

    def make(self):
        lv = synth_level(initial=100)
        units = {n: unitdb.load_unit(n) for n in ("ant", "littlebeetle")}
        return simmod.Sim(lv, synth_world2(), units, 42)

    def test_same_lane_rebuy_rejected(self):
        # 同泳道同 tick 连买：第二次被冷却拒绝（旧「同 tick 可连买」语义被推翻）
        s = self.make()
        self.assertIsNotNone(s.buy(0, "ant", 0))
        self.assertIsNone(s.buy(0, "ant", 0))
        self.assertEqual(len(s.bugs), 1)

    def test_cross_lane_isolated(self):
        # 不同泳道各自独立冷却：泳道 0 冷却不影响泳道 1
        s = self.make()
        self.assertIsNotNone(s.buy(0, "ant", 0))
        self.assertIsNotNone(s.buy(0, "ant", 1))
        self.assertEqual(len(s.bugs), 2)

    def test_sides_isolated(self):
        # 双方隔离：我方泳道 0 冷却不影响敌方泳道 0
        s = self.make()
        self.assertIsNotNone(s.buy(0, "ant", 0))
        self.assertIsNotNone(s.buy(1, "ant", 0))
        self.assertEqual(len(s.bugs), 2)

    def test_boundary_before_at_after(self):
        # 冷却 200 tick：199 仍拒，200 放行（tick < 归零 tick = 拒）
        s = self.make()
        self.assertIsNotNone(s.buy(0, "ant", 0))
        s.run(199)
        self.assertIsNone(s.buy(0, "ant", 0))     # t=199 < 200
        s.run(1)
        self.assertIsNotNone(s.buy(0, "ant", 0))  # t=200 放行
        self.assertEqual(len(s.bugs), 2)

    def test_reject_no_side_effect(self):
        # 拒绝不扣费/不生成/不变 ID/RNG/计时器
        s = self.make()
        s.buy(0, "ant", 0)
        nectar0, nid0, cd0 = s.nectar[0], s._next_id, dict(s.lane_cd_until)
        rng0 = s.rng.getstate()
        self.assertIsNone(s.buy(0, "littlebeetle", 0))
        self.assertEqual(s.nectar[0], nectar0)
        self.assertEqual(s._next_id, nid0)
        self.assertEqual(s.lane_cd_until, cd0)
        self.assertEqual(s.rng.getstate(), rng0)
        self.assertEqual(len(s.bugs), 1)

    def test_spawn_free_arms_cooldown(self):
        # 脚本出生（sendenemy/sendplayer）arm 该泳道冷却；PBA-12：冷却期间同泳道
        # 脚本出生同样被拒（原作 SpawnUnit 0x4862e9-0x4862f6 查 +0x22c==0）
        s = self.make()
        self.assertIsNotNone(s.spawn_free(1, "littlebeetle", 0))
        self.assertIsNone(s.spawn_free(1, "littlebeetle", 0))  # 同泳道冷却期间拒
        self.assertIsNone(s.buy(1, "ant", 0))      # 同泳道买兵也被冷却拦截
        self.assertIsNotNone(s.spawn_free(1, "littlebeetle", 1))  # 跨泳道不受影响
        self.assertEqual(len(s.bugs), 2)           # 仅 (1,0) 与 (1,1) 各一只

    def test_cooldown_in_state_hash(self):
        # 冷却状态入 state_hash（跨进程回放敏感）
        s1, s2 = self.make(), self.make()
        s1.buy(0, "ant", 0)
        s2.buy(0, "ant", 0)
        self.assertEqual(s1.state_hash(), s2.state_hash())
        s2.run(10)                                  # 冷却随 tick 递减 → hash 变
        self.assertNotEqual(s1.state_hash(), s2.state_hash())


class TestGatherMicro(unittest.TestCase):
    """微场景: 花距巢 110 u, ant Speed 22 → 单程 100 tick, 往返 200 tick。"""

    def test_round_trip_deposits(self):
        # H11c: 巡逻 A→wp→E 途经花边; t32 接触拾取(PICKUP_RADIUS=75, 距花
        # 74.8≤75), 原段折返+回家 32t → t64 存款。纯运动学定值(与种子无关)
        s = make_sim()
        # R368: motion precondition starts with an actual generated flower slot.
        for flower in s.flowers:
            flower.cycle.timer = flower.cycle.threshold
        s.run(68)
        start_tick = s.tick
        b = s.buy(0, "ant", 0)
        s.run(63)
        self.assertEqual(s.nectar[0], 10)     # 未到 64t 无存款
        self.assertEqual(s.bugs[0].carrying, 1)  # t32 已接触拾取在返程
        s.run(1)
        self.assertEqual(s.tick, start_tick + 64)
        self.assertEqual(s.nectar[0], 13)     # 10 + NECTAR_VALUE(3)
        deposits = [e for e in s.events if e[1] == "deposit"]
        self.assertEqual([d[0] for d in deposits], [start_tick + 64])


class TestStateHash(unittest.TestCase):
    def test_same_seed_same_hash_sequence(self):
        h1, h2 = [], []
        for s, out in ((make_sim(seed=7), h1), (make_sim(seed=7), h2)):
            s.buy(0, "ant", 0)
            for _ in range(5):
                s.run(100)
                out.append(s.state_hash())
        self.assertEqual(h1, h2)

    def test_path_nectar_deterministic_and_differs_by_seed(self):
        # level_02 真实世界: NectarOnPaths=4 布点由 sim.rng 决定
        from bugbits.assets import data_dir
        from bugbits import worlddb
        from bugbits.level import parse_level
        w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
        lv = parse_level(data_dir("scripts", "levels", "level_02.vsc"))
        units = unitdb.load_all()
        s1 = simmod.Sim(lv, w, units, seed=1)
        s2 = simmod.Sim(lv, w, units, seed=1)
        s3 = simmod.Sim(lv, w, units, seed=2)
        self.assertEqual([i.pos for i in s1.path_nectar], [i.pos for i in s2.path_nectar])
        self.assertEqual(len(s1.path_nectar), 4)
        self.assertNotEqual([i.pos for i in s1.path_nectar], [i.pos for i in s3.path_nectar])
        self.assertNotEqual(s1.state_hash(), s3.state_hash())


class TestPathNectarPlacement(unittest.TestCase):
    """H11d 校准: 全场路点随机+邻居 lerp+避水（原 lane0 路线采样证伪）。"""
    def test_items_on_graph_segments_and_deterministic(self):
        import math as _m
        from bugbits.assets import data_dir
        from bugbits import worlddb
        from bugbits.level import parse_level
        w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
        lv = parse_level(data_dir("scripts", "levels", "level_02.vsc"))
        s1 = simmod.Sim(lv, w, unitdb.load_all(), seed=1)
        s2 = simmod.Sim(lv, w, unitdb.load_all(), seed=1)
        self.assertEqual([i.pos for i in s1.path_nectar], [i.pos for i in s2.path_nectar])
        self.assertEqual(len(s1.path_nectar), 4)          # NectarOnPaths=4
        pos = {x.name: x.grid_pos for x in list(w.waypoints) + list(w.starts)}
        water = {x.name: x.water for x in w.waypoints}

        def seg_dist(p, a, b):
            ax, az, bx, bz = a[0], a[2], b[0], b[2]
            dx, dz = bx - ax, bz - az
            L2 = dx * dx + dz * dz
            t = 0 if L2 == 0 else max(0, min(1, ((p[0]-ax)*dx + (p[2]-az)*dz) / L2))
            return _m.hypot(p[0]-(ax+t*dx), p[2]-(az+t*dz))

        edges = [(n, m) for n, ns in w.adjacency.items() for m in ns]
        for it in s1.path_nectar:
            # 落点在某条图链接段上（lerp 落点, 距离≈0）
            d = min(seg_dist(it.pos, pos[a], pos[b]) for a, b in edges)
            self.assertLess(d, 1e-6, (it.item_id, d))
            # 避水: 不落在水路点本体（端点归属按引擎 0.5 阈值近似为距离近者）
            nearest_wp = min(pos, key=lambda n: _m.hypot(
                it.pos[0]-pos[n][0], it.pos[2]-pos[n][2]))
            self.assertFalse(water.get(nearest_wp, False), nearest_wp)
        # 区分性断言(旧 lane0 路点采样证伪): 布点应含段内 lerp 点,
        # 而非全部恰在路点/START 本体上
        node_positions = set(pos.values())
        interior = [it for it in s1.path_nectar if it.pos not in node_positions]
        self.assertTrue(interior, "布点应含段内 lerp 点而非全在路点本体")

    def test_no_water_only_world_places_none(self):
        # 全水路点世界: 候选空 → 0 布（引擎重试耗尽语义近似: 不布)
        from bugbits.worlddb import Start, Waypoint, WorldData
        starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
                  Start("E", (200, 0, 0), (0, 0, 1), 1, 0, [])]
        wps = [Waypoint("w1", (100, 0, 0), (0, 0, 1), True, []),
               Waypoint("w2", (120, 0, 0), (0, 0, 1), True, [])]
        adj = {"w1": {"w2"}, "w2": {"w1"}}
        w = WorldData({}, [], [], None, starts, wps, 2, adj, None)
        lv = LevelData({"InitialNectar": ["0"], "NectarOnPaths": ["3"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]},
                       [], [], [], None)
        s = simmod.Sim(lv, w, {"ant": unitdb.load_unit("ant")}, 42)
        self.assertEqual(s.path_nectar, [])


if __name__ == "__main__":
    unittest.main()


class TestWaterAffineGating(unittest.TestCase):
    """MINOR-1: giantwaterbeetle ×1.5 要求段两端点均 water(0x4AA58C/0x4AAD40)。"""

    def test_both_endpoints_required(self):
        # 图 A(0,0)-w1(100,water)-w2(200,water)-E(300): 段0 A→w1 终点水起点陆
        # → 1.0; 段1 w1→w2 双端水 → 1.5
        from bugbits.worlddb import Start, Waypoint, WorldData
        starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
                  Start("E", (300, 0, 0), (0, 0, 1), 1, 0, [])]
        wps = [Waypoint("w1", (100, 0, 0), (0, 0, 1), True, []),
               Waypoint("w2", (200, 0, 0), (0, 0, 1), True, [])]
        adj = {"A": {"w1"}, "w1": {"A", "w2"}, "w2": {"w1", "E"}, "E": {"w2"}}
        w = WorldData({}, [], [], None, starts, wps, 2, adj, None)
        lv = LevelData({"InitialNectar": ["10"], "NectarOnPaths": ["0"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]},
                       [], [], [], None)
        units = {"giantwaterbeetle": unitdb.load_unit("giantwaterbeetle")}
        s = simmod.Sim(lv, w, units, 42)
        b = s.buy(0, "giantwaterbeetle", 0)
        b.mode = "lane"
        b.progress_sub = 0                              # 段0 (A→w1, 起点陆)
        self.assertEqual(s._lane_mult(b), 1.0)
        b.progress_sub = 2000                           # 段1 (w1→w2, 双端水)
        self.assertEqual(s._lane_mult(b), 1.5)



class TestDefenseVictory(unittest.TestCase):
    """T6.1: defense 倒计时判定（合成关卡, 敌我隔离无脚本）。"""

    def make_defense(self, dtime):
        lv = LevelData({"Type": ["defense"], "DefenseTime": [str(dtime)],
                        "InitialNectar": ["10"], "PlayerBaseSize": ["10"],
                        "EnemyBaseSize": ["3"]}, [], [], [], None)
        units = {n: unitdb.load_unit(n) for n in ("ant", "littlebeetle")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def test_countdown_wins(self):
        # DefenseTime=1s → deadline=round(1.5*20)=30t; 29t 未胜 30t 胜
        s = self.make_defense(1)
        s.run(29)
        self.assertIsNone(s.winner)
        s.run(1)
        self.assertEqual(s.winner, 0)
        kinds = [e[1] for e in s.events]
        self.assertEqual(kinds[-2:], ["survived", "victory"])

    def test_grace_period_half_second(self):
        # 引擎导入 +0.5s 宽限: DefenseTime=0 → 10t 才胜（无边限会开局即胜）
        s = self.make_defense(0)
        self.assertEqual(s.defense_deadline, 10)
        s.run(9)
        self.assertIsNone(s.winner)
        s.run(1)
        self.assertEqual(s.winner, 0)

    def test_enemy_hive_destroyed_wins_before_deadline(self):
        # 倒计时未到但敌巢破 → 亦胜（引擎 0x49252C）; 无 survived 事件
        s = self.make_defense(300)
        s.hives[1].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 0)
        self.assertNotIn("survived", [e[1] for e in s.events])

    def test_player_hive_destroyed_loses(self):
        s = self.make_defense(300)
        s.hives[0].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 1)

    def test_countdown_priority_same_tick(self):
        # 同 tick 倒计时到+敌巢破: 倒计时先判（引擎 0x4924DC 序）→ survived 在前
        s = self.make_defense(0)
        s.run(9)
        s.hives[1].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 0)
        kinds = [e[1] for e in s.events]
        self.assertLess(kinds.index("survived"), kinds.index("victory"))

    def test_no_defense_time_no_deadline(self):
        # battle 关无 DefenseTime → deadline None, 判定走 battle 分支不变
        lv = LevelData({"Type": ["battle"], "InitialNectar": ["10"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]},
                       [], [], [], None)
        units = {"ant": unitdb.load_unit("ant")}
        s = simmod.Sim(lv, synth_world(), units, 42)
        self.assertIsNone(s.defense_deadline)
        s.hives[1].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 0)


class TestMultiTimeout(unittest.TestCase):
    """OFR-01 BUG-09: multi 超时无论 HP 领先与否都发 timeup（终局原因）。

    根因：_check_victory multi 超时分支曾在 tie 才追加 timeup，HP 领先分支只追加
    victory → host.js 凭 timeup 设 endKind，领先方超时误显「失败」而非「时间到」。
    """

    def make_multi(self):
        lv = LevelData({"Type": ["multibattle"], "DefenseTime": ["10"],
                        "InitialNectar": ["10"], "PlayerBaseSize": ["10"],
                        "EnemyBaseSize": ["10"]}, [], [], [], None)
        units = {n: unitdb.load_unit(n) for n in ("ant", "wasp")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def _timeup(self, s):
        return next((e for e in s.events if e[1] == "timeup"), None)

    def test_enemy_leads_timeout_emits_timeup(self):
        # BUG-09 复现原形: hives[1].hp=20 > hives[0].hp=10, 超时 → 须有 timeup
        s = self.make_multi()
        s.hives[0].hp = 10
        s.hives[1].hp = 20
        s.defense_deadline = s.tick
        s._check_victory()
        self.assertEqual(s.winner, 1)
        kinds = [e[1] for e in s.events]
        self.assertEqual(kinds[-2:], ["timeup", "victory"])
        self.assertEqual(self._timeup(s)[2], (1,))

    def test_player_leads_timeout_emits_timeup(self):
        s = self.make_multi()
        s.hives[0].hp = 20
        s.hives[1].hp = 10
        s.defense_deadline = s.tick
        s._check_victory()
        self.assertEqual(s.winner, 0)
        self.assertEqual(self._timeup(s)[2], (0,))
        self.assertEqual([e[1] for e in s.events][-2:], ["timeup", "victory"])

    def test_tie_timeout_emits_timeup(self):
        s = self.make_multi()
        s.hives[0].hp = 10
        s.hives[1].hp = 10
        s.defense_deadline = s.tick
        s._check_victory()
        self.assertEqual(s.winner, 1)          # 现行实现 tie → 本地视角负
        self.assertIsNotNone(self._timeup(s))

    def test_hive_destroyed_no_timeup(self):
        # 非超时路径（敌巢破胜）→ 无 timeup，避免误标超时
        s = self.make_multi()
        s.hives[1].hp = 0
        s.defense_deadline = s.tick
        s._check_victory()
        self.assertEqual(s.winner, 0)
        self.assertIsNone(self._timeup(s))
        self.assertEqual([e[1] for e in s.events], ["victory"])

    def test_player_hive_destroyed_no_timeup(self):
        s = self.make_multi()
        s.hives[0].hp = 0
        s.defense_deadline = s.tick
        s._check_victory()
        self.assertEqual(s.winner, 1)
        self.assertIsNone(self._timeup(s))


class TestGatherVictory(unittest.TestCase):
    """T6.2: gather 判定——蜜达标胜优先, 我巢破负（引擎 0x49261a 公共负路径）。"""

    def make_gather(self, goal=3):
        lv = LevelData({"Type": ["gather"], "GoalNectar": [str(goal)],
                        "InitialNectar": ["0"], "PlayerBaseSize": ["10"],
                        "EnemyBaseSize": ["3"]}, [], [], [], None)
        units = {"ant": unitdb.load_unit("ant")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def test_goal_reached_wins(self):
        s = self.make_gather(goal=3)
        s.nectar[0] = 3
        s.run(1)
        self.assertEqual(s.winner, 0)

    def test_hive_destroyed_loses(self):
        # 引擎公共负判定: gather 关我巢破 → 负（原缺口: 只判蜜达标）
        s = self.make_gather(goal=3)
        s.hives[0].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 1)

    def test_goal_beats_loss_same_tick(self):
        # 同 tick 蜜达标+我巢破: 胜优先（引擎胜消息先于公共负判定显示）
        s = self.make_gather(goal=3)
        s.nectar[0] = 3
        s.hives[0].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 0)


class TestRescueSetup(unittest.TestCase):
    """T6.3: rescue 开局铺场——守军/被困虫/蜜源/花门控（引擎 0x482730 第一阶段）。"""

    def make_rescue(self, bug_setup=None, rescue_bug="militant"):
        # 合成: 敌方路线 START(200,0)=synth_world 的 E, 玩家 A(0,0)
        setups = bug_setup if bug_setup is not None else [
            (0, "ant", 2), (1, "trapped", 1), (2, "nectarbonus", 3)]
        lv = LevelData({"Type": ["rescue"], "RescueBug": [rescue_bug],
                        "DefenseTime": ["30"], "InitialNectar": ["10"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["100"]},
                       setups, [(0, 0), (1, 0), (2, 0)], [], None)
        units = {"ant": unitdb.load_unit("ant"),
                 "militant": unitdb.load_unit("militant")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def test_field_setup(self):
        s = self.make_rescue()
        guards = [b for b in s.bugs if b.side == 1]
        self.assertEqual(len(guards), 2)          # ant×2 守军
        self.assertTrue(all(b.mode == "idle" and not b.trapped for b in guards))
        tb = s.trapped_bug                        # 被困虫: militant, side=0
        self.assertIsNotNone(tb)
        self.assertEqual(tb.unit_name, "militant")
        self.assertEqual(tb.side, 0)
        self.assertEqual(tb.trapped, 1)
        self.assertEqual(tb.mode, "idle")
        ex, ez = 200, 0
        self.assertTrue(abs(tb.cur_pos[0] - ex) <= 10 and abs(tb.cur_pos[2] - ez) <= 10,
                        f"被困虫位置 {tb.cur_pos} 不在敌方 START 附近")
        self.assertEqual(len(s.path_nectar), 3)   # nectarbonus×3 → 蜜源
        for it in s.path_nectar:
            self.assertTrue(abs(it.pos[0] - ex) <= 10, f"蜜源 {it.pos}")

    def test_flowers_do_not_regen_in_rescue(self):
        s = self.make_rescue()
        self.assertTrue(all(f.nectar == 0 and not f.cycle.playing for f in s.flowers))
        f = s.flowers[0]
        f.nectar = 0
        s.run(2000)                               # 100s > 30s 阈值仍不再生
        self.assertEqual(f.nectar, 0)

    def test_trapped_bug_invulnerable(self):
        s = self.make_rescue()
        tb = s.trapped_bug
        hp0 = tb.hp
        g = s.spawn_free(1, "militant", 0)        # 敌方 militant 免费出生
        g.cur_pos = (tb.cur_pos[0] + 5, 0, tb.cur_pos[2])
        s.run(600)                                # 30s 全程输出
        self.assertEqual(tb.hp, hp0)              # 无敌: 不被选为目标
        self.assertEqual(tb.dead, 0)

    def test_non_rescue_type_no_field(self):
        # battle 关同 BugSetup 不铺场 (引擎 Type=='rescue' 门)
        lv = LevelData({"Type": ["battle"], "InitialNectar": ["10"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]},
                       [(0, "ant", 2), (1, "trapped", 1)], [(0, 0)], [], None)
        units = {"ant": unitdb.load_unit("ant")}
        s = simmod.Sim(lv, synth_world(), units, 42)
        self.assertEqual(s.bugs, [])
        self.assertIsNone(s.trapped_bug)


class TestRescueVictory(unittest.TestCase):
    """T6.3: rescue 判定——接触胜→超时负→巢破负（引擎序: 胜优先, W1）。"""

    def make_rescue(self, dtime=30):
        setups = [(0, "ant", 1), (1, "trapped", 1)]
        lv = LevelData({"Type": ["rescue"], "RescueBug": ["militant"],
                        "DefenseTime": [str(dtime)], "InitialNectar": ["10"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["100"]},
                       setups, [(0, 0), (1, 0)], [], None)
        units = {"ant": unitdb.load_unit("ant"),
                 "militant": unitdb.load_unit("militant")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def test_touch_rescues(self):
        # 玩家虫贴近被困虫 (< 1.5*(5+5+5)=22.5) → 胜 (rescued→victory)
        s = self.make_rescue()
        b = s.buy(0, "ant", 0)
        tb = s.trapped_bug
        b.mode = "idle"
        b.cur_pos = (tb.cur_pos[0] + 5, 0, tb.cur_pos[2])
        s.run(1)
        self.assertEqual(s.winner, 0)
        kinds = [e[1] for e in s.events]
        self.assertEqual(kinds[-2:], ["rescued", "victory"])

    def test_far_no_rescue(self):
        s = self.make_rescue()
        b = s.buy(0, "ant", 0)
        b.mode = "idle"
        b.cur_pos = (s.trapped_bug.cur_pos[0] - 100, 0, 0)
        s.run(10)
        self.assertIsNone(s.winner)

    def test_timeup_loses(self):
        # DefenseTime=0 → +0.5s 宽限 10t 超时负 (引擎 0x49257d TIMEUP)
        s = self.make_rescue(dtime=0)
        s.run(9)
        self.assertIsNone(s.winner)
        s.run(1)
        self.assertEqual(s.winner, 1)
        kinds = [e[1] for e in s.events]
        self.assertEqual(kinds[-2:], ["timeup", "victory"])

    def test_hive_destroyed_loses(self):
        s = self.make_rescue()
        s.hives[0].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 1)

    def test_touch_beats_timeup_same_tick(self):
        # 同 tick 接触+超时: 胜优先 (引擎 ceAI 每帧先于胜负函数)
        s = self.make_rescue(dtime=0)
        b = s.buy(0, "ant", 0)
        b.mode = "idle"                        # 停在出生点 (远离被困虫)
        s.run(9)
        self.assertIsNone(s.winner)
        b.cur_pos = (s.trapped_bug.cur_pos[0] + 5, 0, s.trapped_bug.cur_pos[2])
        s.run(1)                               # tick=10: 接触+超时同 tick
        self.assertEqual(s.winner, 0)
        self.assertIn("rescued", [e[1] for e in s.events])


class TestRescueCRFixes(unittest.TestCase):
    """T6.3 code-review 回归: MAJOR-1 lane 虫位置/MAJOR-2 拾取绕过再生门/MAJOR-3 被困虫好战。"""

    def make_rescue(self):
        setups = [(0, "ant", 1), (1, "trapped", 1)]
        lv = LevelData({"Type": ["rescue"], "RescueBug": ["militant"],
                        "DefenseTime": ["30"], "InitialNectar": ["10"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["100"]},
                       setups, [(0, 0), (1, 0)], [], None)
        units = {"ant": unitdb.load_unit("ant"),
                 "militant": unitdb.load_unit("militant"),
                 "littlebeetle": unitdb.load_unit("littlebeetle")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def test_lane_walker_rescues(self):
        # MAJOR-1: lane 行军虫（非采集）按推导位置 pos() 判接触
        s = self.make_rescue()
        b = s.buy(0, "littlebeetle", 0)           # lane 模式 (CanGather=0)
        self.assertEqual(b.mode, "lane")
        b.progress_sub = b.route_len_sub - 40     # 距终点 ~2u (littlebeetle 14u/s)
        s.run(2)
        self.assertEqual(s.winner, 0, f"lane 虫到达未触发救援 (pos={b.pos(s)})")
        self.assertIn("rescued", [e[1] for e in s.events])

    def test_rescue_bonus_pickup_does_not_create_flower_nectar(self):
        # R368: rescue花开局没有蜜；已有nectarbonus走真实拾取/交付。
        s = self.make_rescue()
        s.level.bug_setups.append((0, 'nectarbonus', 1))
        s = simmod.Sim(s.level, s.world, s.units, 42)
        self.assertEqual(len(s.path_nectar), 1)
        s.buy(0, "ant", 0)                        # patrol 采集
        for _ in range(2000):
            s.step()
            if any(e[1] == "deposit" for e in s.events):
                break
        deposits = [e for e in s.events if e[1] == "deposit"]
        self.assertTrue(deposits, "合成场景 2000t 内应有存款")
        f = s.flowers[0]
        self.assertEqual(f.nectar, 0)             # 采空
        s.run(700)                                # 35s > type1 30s 阈值
        self.assertEqual(f.nectar, 0, "rescue 关拾取后花不应再生")
        self.assertFalse(f.cycle.playing)

    def test_trapped_bug_pacifist(self):
        # MAJOR-3: 被困虫不主动接战 (引擎 state 11 被动)
        s = self.make_rescue()
        guards = [b for b in s.bugs if b.side == 1]
        self.assertTrue(guards)
        hp0 = [g.hp for g in guards]
        s.run(600)                                # 30s 若好战早杀人了
        self.assertEqual([g.hp for g in guards], hp0, "被困虫不应攻击守军")


class TestMultiVictory(unittest.TestCase):
    """T6.4: multi 判定——我巢破先判/超时 HP 高者胜/等值双败（W1 证据序）。"""

    def make_multi(self, dtime=30, t="multibattle"):
        lv = LevelData({"Type": [t], "DefenseTime": [str(dtime)],
                        "InitialNectar": ["10"], "PlayerBaseSize": ["10"],
                        "EnemyBaseSize": ["10"]}, [], [], [], None)
        units = {"ant": unitdb.load_unit("ant")}
        return simmod.Sim(lv, synth_world(), units, 42)

    def test_own_hive_destroyed_loses_first(self):
        # 引擎多人块序: 我巢破先于敌巢破 (同 tick 双破→负, 与单人 battle 相反)
        s = self.make_multi()
        s.hives[0].hp = 0
        s.hives[1].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 1)

    def test_enemy_hive_destroyed_wins(self):
        s = self.make_multi()
        s.hives[1].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 0)

    def test_timeout_enemy_hp_leader_wins(self):
        # 超时: 敌 HP 高 → 敌胜 (本地负)
        s = self.make_multi(dtime=0)
        s.hives[1].hp = 20
        s.hives[0].hp = 10
        s.run(10)
        self.assertEqual(s.winner, 1)

    def test_timeout_own_hp_leader_wins(self):
        s = self.make_multi(dtime=0)
        s.hives[0].hp = 20
        s.hives[1].hp = 10
        s.run(10)
        self.assertEqual(s.winner, 0)

    def test_timeout_tie_timeup_loses(self):
        # HP 严格相等 → TIMEUP 双败 (本地视角 winner=1)
        s = self.make_multi(dtime=0)
        s.run(9)
        self.assertIsNone(s.winner)
        s.run(1)
        self.assertEqual(s.winner, 1)
        kinds = [e[1] for e in s.events]
        self.assertEqual(kinds[-2:], ["timeup", "victory"])

    def test_multirandom_same_semantics(self):
        s = self.make_multi(dtime=0, t="multirandom")
        s.hives[0].hp = 20
        s.hives[1].hp = 10
        s.run(10)
        self.assertEqual(s.winner, 0)

    def test_multi_nectar_symmetric(self):
        # W1: Player1 经济同构——multi 关敌侧也有 InitialNectar (敌 bot 可买兵)
        s = self.make_multi()
        self.assertEqual(s.nectar[0], 10)
        self.assertEqual(s.nectar[1], 10)

    def test_battle_dual_destroy_player_wins(self):
        # T6.4 CR 次要-2 对偶锚定: battle 分支同 tick 双破 → 玩家胜（与 multi 相反）
        lv = LevelData({"Type": ["battle"], "InitialNectar": ["10"],
                        "PlayerBaseSize": ["10"], "EnemyBaseSize": ["10"]},
                       [], [], [], None)
        s = simmod.Sim(lv, synth_world(), {"ant": unitdb.load_unit("ant")}, 42)
        s.hives[0].hp = 0
        s.hives[1].hp = 0
        s.run(1)
        self.assertEqual(s.winner, 0)

    def test_multi_enemy_deposit_counts(self):
        # T6.4 CR 严重-1: multi 关敌侧采集交付入账（Player1 经济同构）
        s = self.make_multi()
        s.spawn_free(1, "ant", 0)                 # 敌方采集蚁免费出生
        s.run(2000)
        self.assertGreater(s.nectar[1], 10, "敌侧采集收入应入账")
        self.assertTrue(any(e[1] == "deposit" and e[2][0] == 1
                            for e in s.events))
