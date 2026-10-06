"""T4.4b: sim 战斗——节拍/通道/死亡/H1/H2（静态值手算区间断言）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import sim as simmod  # noqa: E402
from bugbits import unitdb  # noqa: E402
from bugbits.level import LevelData  # noqa: E402
from bugbits.worlddb import Start, Waypoint, WorldData  # noqa: E402


def make_sim(units_names=("ant", "littlebeetle", "bee", "bigbangbug", "tick", "bomberbee", "beetlehero")):
    starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
              Start("E", (200, 0, 0), (0, 0, 1), 1, 0, [])]
    wps = [Waypoint("wp", (100, 0, 0), (0, 0, 1), False, [])]
    adj = {"A": {"wp"}, "wp": {"A", "E"}, "E": {"wp"}}
    world = WorldData({}, [], [], None, starts, wps, 2, adj, None)
    lv = LevelData({"InitialNectar": ["100"], "NectarOnPaths": ["0"],
                    "PlayerBaseSize": ["10"], "EnemyBaseSize": ["3"]}, [], [], [], None)
    units = {n: unitdb.load_unit(n) for n in units_names}
    s = simmod.Sim(lv, world, units, seed=42)
    s.nectar[1] = 100      # 测试装配: 敌方钱包补足（H11e 敌方开局 0 是运行时语义）
    return s


def place(sim, side, name, x, z=0):
    """买一只虫并摆到 (x, z)、idle（在其射程内有敌即接战）。

    OFR-02B：清泳道冷却（本助手只摆位装配，不验冷却门禁；单泳道合成世界连买会被拦）。
    """
    sim.lane_cd_until.clear()
    b = sim.buy(side, name, 0)
    b.mode = "idle"
    b.cur_pos = (x, 0, z)
    b.progress_sub = 0
    b.route_len_sub = 0
    return b


class TestCombatBasics(unittest.TestCase):
    def test_ant_kills_tick_in_window(self):
        # REVIEW DATA: ant hit=1.3 / AS=1.5 -> ceil(17.333)=18t，t1起播→t19。
        # ant_attack.van=2.9333334s，严格播完需40t；等待ceil(U(0,.5)+.1)*20。
        # 相邻命中间隔42..52t，6发击杀范围19+5*(42..52)=[229,279]。
        s = make_sim()
        place(s, 0, "ant", 0)
        place(s, 1, "tick", 2)
        s.run(300)
        deaths = [e for e in s.events if e[1] == "death"]
        self.assertEqual(len(deaths), 1)
        self.assertTrue(229 <= deaths[0][0] <= 279, deaths[0][0])
        dmgs = [e for e in s.events if e[1] == "damage"]
        self.assertEqual(len(dmgs), 6)
        self.assertEqual([d[2][2] for d in dmgs], [5] * 6)
        self.assertEqual(dmgs[0][0], 19)

    def test_ant_vs_littlebeetle_mutual(self):
        # DATA: LB 有1.0/1.4/2.6三段命中；与ant单段完整动画对战回归。
        s = make_sim()
        place(s, 0, "ant", 0)
        place(s, 1, "littlebeetle", 2)
        s.run(300)
        ant = next(b for b in s.bugs if b.unit_name == "ant")
        lb = next(b for b in s.bugs if b.unit_name == "littlebeetle")
        self.assertEqual(ant.dead, 1)
        self.assertEqual(lb.dead, 0)

    def test_dead_not_targeted_and_hash_stable(self):
        s = make_sim()
        t1 = place(s, 1, "tick", 2)
        place(s, 0, "ant", 0)
        s.run(300)
        self.assertEqual(t1.dead, 1)
        # 死者留在列表且 dead=1 入 hash
        self.assertIn(t1, s.bugs)
        # 再放一只活 tick: ant 转火新目标
        t2 = place(s, 1, "tick", 4)
        s.run(300)
        self.assertEqual(t2.dead, 1)

    def test_determinism_same_seed(self):
        hashes = []
        for _ in range(2):
            s = make_sim()
            place(s, 0, "ant", 0)
            place(s, 1, "tick", 2)
            out = []
            for _ in range(20):
                s.run(10)
                out.append(s.state_hash())
            hashes.append(out)
        self.assertEqual(hashes[0], hashes[1])


class TestH1H2(unittest.TestCase):
    def test_bee_suicide_sting(self):
        # H1: bee 特伤30 自杀蛰刺——命中飞行目标后按名自杀（REVIEW-SPECIAL 名字硬编码）。
        # 空地过滤(REVIEW-MOTION): bee air=0 → 只打飞行目标（bomberbee），打不到地面。
        s = make_sim()
        place(s, 0, "bee", 0)
        bmb = place(s, 1, "bomberbee", 2)
        s.run(50)
        bee = next(b for b in s.bugs if b.unit_name == "bee")
        self.assertEqual(bee.dead, 1)                   # 自杀
        self.assertEqual(bmb.dead, 0)                   # 30 伤未杀 70HP bomberbee
        dmgs = [e for e in s.events if e[1] == "damage" and e[2][0] == bee.bug_id]
        self.assertEqual(len(dmgs), 1)
        self.assertEqual(dmgs[0][2][2], 30)

    def test_bigbang_selfdestruct_aoe(self):
        # H2: bigbang special 75 对射程内全部敌人 → 2 tick 亡 + 自爆
        s = make_sim()
        place(s, 0, "bigbangbug", 0)
        place(s, 1, "tick", 2)
        place(s, 1, "tick", 3)
        s.run(50)
        b = next(x for x in s.bugs if x.unit_name == "bigbangbug")
        self.assertEqual(b.dead, 1)
        self.assertEqual(sum(1 for x in s.bugs if x.unit_name == "tick" and x.dead), 2)


class TestDistanceTargeting(unittest.TestCase):
    """H8b 校准: 目标选择=纯距离制(Priority 证伪=UI 排序键); 空袭不打采集虫。"""

    def test_nearest_wins_regardless_of_priority(self):
        # tick(Priority 100) 距 3.5 与 littlebeetle(Priority 10) 距 2 同在射程
        # → 打近者（3.5 在旧 4u 射程内——双候选均入围才能区分优先级/距离制;
        # 计划原值 6 在旧射程外, 旧实现下弱判别, 按测试意图语义适配）
        s = make_sim()
        lb = place(s, 0, "littlebeetle", 0)
        place(s, 1, "tick", 3.5)
        near = place(s, 1, "littlebeetle", 2)
        from bugbits.sim import combat
        t = combat.pick_target(s, lb)
        self.assertIs(t[1], near)                          # 距离制, 非优先级

    def test_touch_radius_formula(self):
        # R = self.Radius + MeleeDistance + target.Radius (H8b: littlebeetle
        # 6.5 + 4 + tick 半径; tick 半径由 unitdb 读) —— 恰在 R-0.5 内可击, R+2 外不可
        s = make_sim()
        lb = place(s, 0, "littlebeetle", 0)
        from bugbits.sim import combat
        tk = unitdb.load_unit("tick")
        R = 6.5 + 4.0 + float(tk.radius)
        t1 = place(s, 1, "tick", R - 0.5)
        self.assertIsNotNone(combat.pick_target(s, lb))
        t1.dead = 1
        place(s, 1, "tick", R + 2.0)
        self.assertIsNone(combat.pick_target(s, lb))       # 超触及半径无目标

    def test_air_raid_excludes_gatherers(self):
        # 空袭排除(0x4AB601): 飞行攻击者跳过 CanGather 目标。空地过滤(REVIEW-MOTION):
        # wasp air=0 → 只打飞行目标（bomberbee），打不到地面（littlebeetle）。
        s = make_sim(("wasp", "bee", "bomberbee", "littlebeetle"))
        wasp = place(s, 0, "wasp", 0)
        place(s, 1, "bee", 2)                          # 更近但飞行采集虫 → 跳过
        place(s, 1, "littlebeetle", 3)                 # 地面 → air=0 打不到
        bmb = place(s, 1, "bomberbee", 5)              # 飞行非采集 → 唯一合法目标
        from bugbits.sim import combat
        t = combat.pick_target(s, wasp)
        self.assertIs(t[1], bmb)

    def test_special_channel_range_not_ranged_distance(self):
        # 评审 MAJOR-3 回归: 特殊通道单位(bee: melee=0/ranged_damage=0/
        # special=30) 射程=SPECIAL_RANGE(4), 非 RangedDistance(80)。
        # 空地过滤: bee air=0 → 只打飞行目标(bomberbee)。
        s = make_sim()
        bee = place(s, 0, "bee", 0)
        place(s, 1, "bomberbee", 50)                    # >4 但 <80: 证不按 RangedDistance
        from bugbits.sim import combat
        self.assertIsNone(combat.pick_target(s, bee))
        near = place(s, 1, "bomberbee", 3)              # ≤4 接战
        t = combat.pick_target(s, bee)
        self.assertIs(t[1], near)


class TestChannelResolution(unittest.TestCase):
    """REVIEW-SPECIAL: channel() 按名+状态定通道，非 melee>ranged>special 优先序。"""

    def test_special_units_not_melee(self):
        from bugbits.sim import combat
        sp = unitdb.load_unit("spider")
        self.assertEqual(combat.channel(sp)[0], "special")      # 状态6 霰弹, 非近战
        self.assertEqual(combat.effective_range(sp), sp.ranged_distance)   # 触及=80 非 melee 3
        for name in ("caterpillar", "poisonpillar", "wasphero", "bomberbee"):
            u = unitdb.load_unit(name)
            self.assertEqual(combat.channel(u)[0], "special", name)   # 状态7 弹体
            self.assertEqual(combat.effective_range(u), u.air_distance, name)  # AIR 路径
        # toxichero 双通道取远程优先（状态6 ranged12；special15 状态7 为次通道不建模）
        tx = unitdb.load_unit("toxichero")
        self.assertEqual(combat.channel(tx)[0], "ranged")
        # rhinobeetle melee+special30：special 走死亡 AOE，主通道近战
        rb = unitdb.load_unit("rhinobeetle")
        self.assertEqual(combat.channel(rb)[0], "melee")


class TestHiveAndReload(unittest.TestCase):
    def test_hive_attack_is_suicide(self):
        # H15/W3: 攻巢=一击 HiveDamage 后攻击者自入死亡态(引擎 state4→9,
        # 0x4aac18 [esp+0x34]=9)。littlebeetle HiveDamage 1 → 敌巢 3→2,
        # 攻击者 dead=1, 未摧毁（非持续扣血）。
        s = make_sim()
        b = s.buy(0, "littlebeetle", 0)
        b.mode = "lane"
        b.cur_pos = (200, 0, 0)
        b.progress_sub = b.route_len_sub - 1      # 差 1 sub 抵达敌方 START
        s.run(80)
        self.assertEqual(b.dead, 1)               # 攻巢者自杀
        self.assertEqual(s.hives[1].hp, 2)        # 3 - 1 击
        hits = [e for e in s.events if e[1] == "hive_damage"]
        self.assertEqual(len(hits), 1)
        self.assertEqual([h[2][1] for h in hits], [1])
        destroyed = [e for e in s.events if e[1] == "hive_destroyed"]
        self.assertEqual(len(destroyed), 0)       # 一击未摧毁

    def test_hive_destroyed_by_three_attackers(self):
        # H15/W3: 攻巢=自杀 → 摧毁 3 HP 敌巢需 3 只 littlebeetle 各一击。
        s = make_sim()
        for _ in range(3):
            s.lane_cd_until.clear()       # 清冷却（装配 3 攻巢者，不验冷却门禁）
            b = s.buy(0, "littlebeetle", 0)
            b.mode = "lane"
            b.cur_pos = (200, 0, 0)
            b.progress_sub = b.route_len_sub - 1
        s.run(80)
        destroyed = [e for e in s.events if e[1] == "hive_destroyed"]
        self.assertEqual(len(destroyed), 1)
        self.assertEqual(destroyed[0][2][0], 1)   # 被摧毁的是敌方(侧1)巢
        self.assertEqual(s.hives[1].hp, 0)
        hits = [e for e in s.events if e[1] == "hive_damage"]
        self.assertEqual(len(hits), 3)
        self.assertEqual([h[2][1] for h in hits], [1, 1, 1])

    def test_h3_reload_is_seconds_cooldown(self):
        # H3 修正(W1): Reload(+0x42c)=10 秒 ReloadTimer 冷却(非发数); 每次发射后
        # reload_until = tick + 10s=200t; ReloadTime(buginfos id0x0E) 不参与战斗。
        # bomberbee special 25×2 击杀 tick(HP 30)。
        s = make_sim()
        b = place(s, 0, "bomberbee", 0)
        place(s, 1, "tick", 2)
        s.run(60)                                  # 首击约 t47
        dmgs = [e for e in s.events if e[1] == "damage" and e[2][0] == b.bug_id]
        self.assertEqual(len(dmgs), 1)
        first_t = dmgs[0][0]
        self.assertEqual(b.reload_until, first_t + 200)   # Reload=10s=200t（秒，非发数）
        self.assertFalse(hasattr(b, "ammo"))              # ammo 字段已移除
        s.run(150)                                 # 仍在 Reload 冷却内
        self.assertEqual(len([e for e in s.events
                              if e[1] == "damage" and e[2][0] == b.bug_id]), 1)
        s.run(150)                                 # 冷却过 + 发射帧 → 第 2 击
        dmgs = [e for e in s.events if e[1] == "damage" and e[2][0] == b.bug_id]
        self.assertEqual(len(dmgs), 2)
        self.assertEqual(next(x for x in s.bugs if x.unit_name == "tick").dead, 1)


class TestDeathAOE(unittest.TestCase):
    """REVIEW-SPECIAL: 死亡 AOE（0x4a71c0）——特攻单位死亡对邻域结算 SpecialDamage，
    半径由 AirDistance(+0x408) 派生（wasphero 族 ×2）。"""

    def test_death_aoe_range_derivation(self):
        from bugbits.sim import combat
        w = unitdb.load_unit("wasphero")
        self.assertEqual(combat.death_aoe_range(w), 2 * w.air_distance)   # 400
        tx = unitdb.load_unit("toxichero")
        self.assertEqual(combat.death_aoe_range(tx), tx.air_distance)     # 200（50+ 未采用）
        pp = unitdb.load_unit("poisonpillar")
        self.assertEqual(combat.death_aoe_range(pp), pp.air_distance)     # 175
        bb = unitdb.load_unit("bigbangbug")
        self.assertEqual(combat.death_aoe_range(bb), bb.air_distance)     # 100
        ant = unitdb.load_unit("ant")
        self.assertEqual(combat.death_aoe_range(ant), 0)                  # 无 AirDistance

    def test_bigbang_death_aoe_radius_is_air_distance(self):
        # bigbangbug SpecialDamage=75, AirDistance=100: 接战自毁（触及 SPECIAL_RANGE=4）
        # 后死亡 AOE 半径=AirDistance=100（非旧 effective_range=4 只伤触及内）。
        s = make_sim(("bigbangbug", "tick"))
        place(s, 0, "bigbangbug", 0)
        near = place(s, 1, "tick", 3)      # 触及内 → 触发自毁
        mid = place(s, 1, "tick", 50)      # 触及外(>4)但 AOE 半径(100)内 → 受 75 伤亡
        far = place(s, 1, "tick", 150)     # AOE 半径(100)外 → 不受
        s.run(50)
        b = next(x for x in s.bugs if x.unit_name == "bigbangbug")
        self.assertEqual(b.dead, 1)
        self.assertEqual(near.dead, 1)
        self.assertEqual(mid.dead, 1)      # 半径 100 > 50
        self.assertEqual(far.dead, 0)      # 半径 100 < 150

    def test_wasphero_death_aoe_x2_radius(self):
        # wasphero SpecialDamage=30, AirDistance=200 → 死亡 AOE 半径 400（名字串 ×2）。
        s = make_sim(("wasphero", "tick"))
        w = place(s, 1, "wasphero", 0)
        inside = place(s, 0, "tick", 300)   # 300 < 400
        outside = place(s, 0, "tick", 500)  # 500 > 400
        from bugbits.sim import combat
        combat._kill(s, w)
        self.assertEqual(w.dead, 1)
        self.assertEqual(inside.dead, 1)    # 30 伤击杀 HP30 tick
        self.assertEqual(outside.dead, 0)

    def test_non_special_no_death_aoe(self):
        # ant SpecialDamage=0 → 死亡无 AOE（0x4a71c0 对 SpecialDamage=0 单位无伤）。
        s = make_sim()
        a = place(s, 0, "ant", 0)
        t = place(s, 1, "tick", 2)
        from bugbits.sim import combat
        combat._kill(s, a)
        self.assertEqual(a.dead, 1)
        self.assertEqual(t.dead, 0)

    def test_death_aoe_centered_at_lane_position(self):
        # 死亡 AOE 中心 = 插值位置（lane 行军中 cur_pos 恒为 spawn 不更新）——
        # bigbangbug(side1) 行军至 A(0,0,0), 死亡 AOE 半径 100 应命中 A 处 tick,
        # 而非 spawn E(200,0,0) 处的 tick。
        s = make_sim(("bigbangbug", "tick"))
        b = s.buy(1, "bigbangbug", 0)          # lane 模式, spawn=E=(200,0,0)
        b.progress_sub = b.route_len_sub        # 行军至路线终点 A=(0,0,0)
        t_at_a = place(s, 0, "tick", 0)        # 插值死亡位置
        t_at_e = place(s, 0, "tick", 200)      # spawn 位置
        from bugbits.sim import combat
        combat._kill(s, b)
        self.assertEqual(b.dead, 1)
        self.assertEqual(t_at_a.dead, 1)       # 距死亡位置 0 < 100
        self.assertEqual(t_at_e.dead, 0)       # 距死亡位置 200 > 100


if __name__ == "__main__":
    unittest.main()
