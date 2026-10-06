"""战斗解析（T4.4b）: 目标选择(H8b 距离制)/攻击节拍(H17)/四通道/装填(H3)/H1/H2/死亡。

近战动画从 0 开始，命中按 prev < HitFrame <= current，圈末后才等待
uniform(WaitMin,WaitMax)+0.1s。SetAnim(2,0.5) 的 0.5 是混合时长非起播相位。
20Hz 调度是重实现选择；目标丢失取消当前攻击；特殊/远程仍为单击近似，未还原完整状态机。
[切片取舍: 依据 H17] attack-move 旁路（引擎 aggro/特攻态保留速度不清零）不
建模——切片接战即停走, 冷却生命周期连续。
距离使用三分量（REVIEW F3，FindTarget 0x4A3FBD–0x4A4009）。
"""
import math
from bugbits.sim import consts
from bugbits.sim.nectar import f32


def effective_range(spec):
    """单位有效射程（REVIEW-SPECIAL: 按名+状态定通道，非 melee>ranged>special 优先序）。

    spider → 状态6 霰弹触及=RangedDistance(80)；状态7 特攻单位 → AIR 路径=AirDistance。
    """
    if spec.name in consts.SPIDER_SHOTGUN_UNITS:
        return spec.ranged_distance or 0
    if spec.name in consts.SPECIAL_PROJECTILE_UNITS:
        return spec.air_distance or 0
    if (spec.melee_damage or 0) > 0:
        return spec.melee_distance or 0
    if (spec.ranged_damage or 0) > 0:
        return spec.ranged_distance or 0
    if (spec.special_damage or 0) > 0:
        return consts.SPECIAL_RANGE
    return 0


def channel(spec):
    """(通道名, 伤害值) 或 None。

    REVIEW-SPECIAL: spider/caterpillar/poisonpillar/wasphero/bomberbee 是
    特攻单位（状态6/7），非纯近战；toxichero 双通道取远程优先（ranged12 状态6）。
    """
    if (spec.name in consts.SPIDER_SHOTGUN_UNITS
            or spec.name in consts.SPECIAL_PROJECTILE_UNITS):
        return ("special", spec.special_damage)
    if (spec.melee_damage or 0) > 0:
        return ("melee", spec.melee_damage)
    if (spec.ranged_damage or 0) > 0:
        return ("ranged", spec.ranged_damage)
    if (spec.special_damage or 0) > 0:
        return ("special", spec.special_damage)
    return None


def first_hit_ticks(spec):
    """从动画零时刻到首个阈值的 tick 上取整；不含状态进入/接近时间。"""
    return max(0, math.ceil((spec.attack_hit_frame or 0)
                           / (spec.attack_speed or 1.0) * consts.TICK_HZ))


def _distance(a, b):
    return math.dist(a, b)


def pick_target(sim, bug):
    """H8b 校准: FindTarget 距离制（0x4A3F20）——Priority 证伪=UI 面板排序键。

    触及半径 R = self.Radius + MeleeDistance + target.Radius, dist² < R² 严格
    更近者先到先得（迭代序=bug_id 序, 并列不换）。飞行攻击者跳过 CanGather
    目标（空袭排除 0x4AB601/0x4AD878）。
    [REVIEW-MOTION] 空地几何过滤（0x4a4026-0x4a40d6）：候选 CanFly==self.CanFly
    → 正常通道；不匹配且 self∉{toxichero,toxichero_tick} → AIR 路径(AirDistance)；
    wasphero 族恒 AIR 路径。故 air=0 的单位只能打同空/地目标。
    [切片取舍] 远程锥形(瞄准锥 dot>RangedRange)与 AIR 路径的候选谓词(0x4a3e70)
    不建模——距离即射程；toxichero 族跨空/地攻击的 step7 再跳过细节未建模。
    无虫候选且已抵达 lane 终点 → 攻击敌方巢（HiveDamage 通道）。
    """
    spec = sim.units[bug.unit_name]
    melee_d = spec.melee_distance or 0
    ranged_d = spec.ranged_distance or 0
    air_d = spec.air_distance or 0
    if melee_d <= 0 and ranged_d <= 0 and not (spec.special_damage or 0):
        return None
    p = bug.pos(sim)
    best, best_d = None, None
    for other in sim.bugs:
        if other.dead or other.side == bug.side or other.trapped:
            continue
        ospec = sim.units[other.unit_name]
        if bug.can_fly and (ospec.can_gather or 0):       # 空袭不打采集虫
            continue
        d = _distance(p, other.pos(sim))
        if bug.unit_name in ("wasphero", "wasphero_tick"):
            r_ = air_d                              # wasphero 族恒 AIR 路径
        elif (bug.can_fly != (ospec.can_fly or 0)
                and bug.unit_name not in ("toxichero", "toxichero_tick")):
            r_ = air_d                              # 空地不匹配 → AIR 路径
        elif bug.unit_name in consts.SPIDER_SHOTGUN_UNITS:
            r_ = ranged_d                           # spider 霰弹触及=RangedDistance(80)
        elif bug.unit_name in consts.SPECIAL_PROJECTILE_UNITS:
            r_ = air_d                              # 状态7 特攻 AIR 路径=AirDistance
        elif (spec.melee_damage or 0) > 0:
            r_ = float(spec.radius or 0) + melee_d + float(ospec.radius or 0)
        elif (spec.ranged_damage or 0) > 0:
            r_ = ranged_d                          # 远程通道
        else:
            r_ = consts.SPECIAL_RANGE              # 特殊通道=4 (bee/bigbangbug)
        if d >= r_:
            continue
        if best_d is None or d < best_d:                  # 严格更近先到先得
            best, best_d = other, d
    if best is not None:
        return ("bug", best)
    if (bug.mode == "lane" and bug.route_len_sub > 0
            and bug.progress_sub >= bug.route_len_sub):
        hive = sim.hives[1 - bug.side]
        if hive.hp > 0:
            return ("hive", hive)
    return None


def death_aoe_range(spec):
    """死亡 AOE 半径（0x4a71c0）: 由 AirDistance(+0x408) 派生。

    STATIC (t66/t67 + 反汇编 0x4a739f/0x4a74a4/0x4a7594): 死亡函数按名分派半径——
    poisonpillar/默认 = AirDistance；wasphero/_tick = 2×AirDistance
    (`fadd st(0),st(0)`)；toxichero/_tick = 50+AirDistance（常量 0x4e2e20=50.0
    与函数返回值同栈位, 是否半径基数 [UNVERIFIED], 未采用）。切片取 AirDistance,
    wasphero 族 ×2。精确 per-unit 半径公式未还原 [UNVERIFIED]。
    """
    if spec.name in consts.DEATH_AOE_X2_UNITS:
        return (spec.air_distance or 0) * 2
    return spec.air_distance or 0


def _apply_damage(sim, attacker_id, other, dmg):
    """对单位结算伤害 + 事件 + 死亡级联（受击 0x4a69e0 → 死亡 0x4a71c0）。"""
    other.hp -= dmg
    sim.events.append((sim.tick, "damage", (attacker_id, other.bug_id, dmg)))
    if other.hp <= 0 and not other.dead:
        _kill(sim, other)


def _kill(sim, bug):
    death_pos = bug.pos(sim)            # 死亡位置（模式未改, 含 lane 插值; W2 掉蜜位）
    drop_at = death_pos if (bug.carrying and bug.target) else None
    spec = sim.units[bug.unit_name]
    bug.dead = 1
    bug.mode = "idle"
    sim.events.append((sim.tick, "death", (bug.bug_id,)))
    # 死亡 AOE（0x4a71c0）: 特攻单位死亡对邻域结算 SpecialDamage(+0x3f8),
    # 半径 = AirDistance(+0x408) 派生（wasphero 族 ×2）。非特攻 SpecialDamage=0 → 无伤。
    sdmg = spec.special_damage or 0
    if sdmg > 0:
        r = death_aoe_range(spec)
        for other in list(sim.bugs):
            if (not other.dead and not other.trapped      # CR MINOR-4: 无敌
                    and other.side != bug.side
                    and _distance(death_pos, other.pos(sim)) <= r):
                _apply_damage(sim, bug.bug_id, other, sdmg)
    if drop_at is not None:
        # R367: 4A87DF loads existing bug+4C8 nectar; identity/visual age survive.
        sim._drop_nectar(bug)
        bug.carrying = 0

    if getattr(bug, 'carry_pickup_tick', -1) >= 0:
        sim._end_nectar_carry(bug, 'death')


def _fire(sim, bug, target, schedule=True):
    """结算一次攻击（伤害/特效/节拍/冷却）。返回 True 若实际开火。"""
    spec = sim.units[bug.unit_name]
    ch, dmg = channel(spec)
    if ch is None:
        return False

    if target[0] == "hive":
        hive = target[1]
        hive.hp -= (spec.hive_damage or 0)
        sim.events.append((sim.tick, "hive_damage", (bug.side, spec.hive_damage or 0)))
        if hive.hp <= 0:
            sim.events.append((sim.tick, "hive_destroyed", (1 - bug.side,)))
        # H15/W3: 攻巢=自杀——引擎 state4 攻巢路径 call 0x49adb0 后攻击者置死亡态
        # state9（0x4aac18 [esp+0x34]=9 → 0x4aeccf 写回 [edi+0x444]），一击即亡非持续。
        _kill(sim, bug)
        return True
    elif bug.unit_name in consts.AOE_SELFDESTRUCT_UNITS:
        # H2 自爆: bigbangbug 按名清血自毁（0x4ab1d7 → 0x4a6ac6 → 状态8）;
        # 死亡 AOE 由 _kill 用 SpecialDamage 结算（半径 AirDistance, 非旧 effective_range=4）。
        _kill(sim, bug)
    else:
        _apply_damage(sim, bug.bug_id, target[1], dmg)
        if bug.unit_name in consts.SUICIDE_UNITS:             # H1 自杀蛰刺
            _kill(sim, bug)

    if schedule:  # 远程/特攻: 发射后 Reload 秒冷却门控（reload=0 仅剩圈末等待）
        if (spec.reload or 0) > 0:
            # H3 修正(W1): Reload(+0x42c)=ReloadTimer 秒级冷却，每次发射后装载，
            # 非发数/打空；ReloadTime(buginfos id 0x0E) 是 UI 展示字段不参与战斗。
            bug.reload_until = sim.tick + int((spec.reload or 0) * consts.TICK_HZ)
        wait = sim.rng.uniform(spec.attack_wait_min or 0, spec.attack_wait_max or 0)
        bug.cooldown_ticks = first_hit_ticks(spec) + math.ceil((wait + 0.1) * consts.TICK_HZ)
    return True


def _melee_tick(sim, bug, target, spec):
    """零起播→命中边沿(最多4段)→严格越过动画末尾→圈末等待。"""
    if spec.attack_duration is None or spec.attack_duration <= 0:
        raise ValueError(f"{spec.name}: 近战缺有效动画时长")
    if bug.attack_tick < 0:
        if sim.tick >= bug.attack_ready_at:
            bug.attack_tick = 0
        return
    speed = spec.attack_speed or 1.0
    previous = bug.attack_tick * speed / consts.TICK_HZ
    bug.attack_tick += 1
    current = bug.attack_tick * speed / consts.TICK_HZ
    for frame in spec.attack_hit_frames[:4]:
        if previous < frame <= min(current, spec.attack_duration):
            if (bug.dead or (target[0] == "bug" and target[1].dead)
                    or (target[0] == "hive" and target[1].hp <= 0)):
                break
            _fire(sim, bug, target, schedule=False)
    if current > spec.attack_duration:
        wait = sim.rng.uniform(spec.attack_wait_min or 0, spec.attack_wait_max or 0)
        bug.attack_ready_at = sim.tick + math.ceil((wait + 0.1) * consts.TICK_HZ)
        bug.attack_tick = -1


def _normal_terminal(sim, bug):
    """Forward CC has no next: running/idle-level engineering terminal domain.

    Native level+114/owner-state lifecycle and enemy-tail overrides remain
    unqualified. This consumer does not fabricate legacy route progress.
    """
    if sim.level.type != 'menu':
        hive=sim.hives[1-bug.side]
        prior=hive.hp
        damage=f32(sim.units[bug.unit_name].hive_damage or 0.)
        hive.hp=max(0.,f32(f32(hive.hp)-damage))
        sim.events.append((sim.tick,'hive_damage',(bug.side,damage)))
        if prior>0 and hive.hp==0:
            sim.events.append((sim.tick,'hive_destroyed',(1-bug.side,)))
    # Native4A7824 clears health in the terminal death path, including menu.
    bug.hp=0
    _kill(sim,bug)


def combat_tick(sim):
    """战斗阶段: 返回本 tick 接战（不移动）的 bug_id 集合。

    近战按动画状态推进；远程/特攻用 Reload 秒冷却 + 发射帧近似；攻巢=一击自杀
    （引擎 state4 直接结算，非近战命中帧）。
    """
    engaged = set()
    for bug in sorted(sim.bugs, key=lambda b: b.bug_id):
        if (bug.dead or bug.trapped
                or sim.tick < bug.dialogue_wait_until):
            continue
        if (bug.mode == 'lane' and bug.motion is not None and bug.route_enabled and not bug.can_gather
                and not bug.route_returning and bug.motion.controller_state==4
                and bug.route_target is None
                and not sim.route_policy.links(bug,sim.level.is_reversed).get(bug.route_current)):
            _normal_terminal(sim,bug)
            engaged.add(bug.bug_id)
            continue
        target = pick_target(sim, bug)
        if target is None:
            bug.attack_tick = -1  # 目标丢失时取消本圈；圈末等待仍保留
            continue
        engaged.add(bug.bug_id)
        spec = sim.units[bug.unit_name]
        if target[0] == "hive":
            _fire(sim, bug, target)            # 攻巢=一击 HiveDamage + 自杀（不受 Reload 门控）
            continue
        if channel(spec) and channel(spec)[0] == "melee":
            _melee_tick(sim, bug, target, spec)
            continue
        if (spec.reload or 0) > 0 and sim.tick < bug.reload_until:
            continue                           # 装填中（ReloadTimer 门控状态6/7 进入）
        if bug.cooldown_ticks > 0:
            bug.cooldown_ticks -= 1
            if bug.cooldown_ticks == 0:
                _fire(sim, bug, target)
        elif bug.cooldown_ticks == 0:
            _fire(sim, bug, target)           # 就绪即击（HitFrame≤0.5 类, H17 钳 0）
        else:
            bug.cooldown_ticks = first_hit_ticks(sim.units[bug.unit_name])
    return engaged
