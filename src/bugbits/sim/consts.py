"""模拟常数。H11 经济常数的唯一居所——改动即假设变更（D2, 照 ree.md §5 写快照）。

分层表述（D1/D2, T5.6 校准）:
- 引擎 rng = 每虫独立 LCG s·69069+1, GetTickCount 种子（H17b ✅ 0x4B6A90）;
  本模拟的 random.Random(seed) 共享流 = D3 确定性手段, 非引擎复刻。
- 引擎敌方无钱包（H11e ✅: 敌兵全部脚本免费出生）; 敌方收入维度不存在
  （setflow=免费相位出兵, H5 ✅）。
- TICK_HZ=20 固定整数 tick 为 D3 确定性手段（引擎=变步长 dt, H14 证伪 20Hz）。
"""

TICK_HZ = 20            # D3 确定性手段（引擎=变步长 dt 秒 float, H14 证伪固定频率）
SUB = 20                # 1 sub = 1/20 游戏单位; 速度(整数 u/s) → 每 tick 恰 speed 个 sub

# ── 每泳道冷却计时器（ceStart +0x228/+0x22c；证据 research/of02_ce_start.py + PBA-11 勘误）──
# +0x228=2.0 arm 于 SpawnUnit 成功路径（0x49a750，调用点 0x4863b6）；
# +0x22c=10.0 arm 于 0x49a4c0（4 处 = cGameWorld::Update 0x486e70 GameGizmos 遍历 3 处
#   0x487392/0x48751f/0x487678 + 虫发射 0x4aabc7；旧标「脚本 sendenemy/sendplayer/第三命令」
#   错误——脚本四分支全经 SpawnUnit 0x4862a0。证据 research/nc02_dual_timer.py v3，2026-09-20）。
# 两计时器并行每帧递减 clamp0（ceStart::Update 0x49a390），买兵门禁取 OR（任一非零拒）。
# PBA-11 勘误：脚本 sendenemy/sendplayer 四分支（0x48062f/0x480673/0x4807b1/0x4807f2）
#   都 CALL SpawnUnit 0x4862a0，其成功路径同样 arm +0x228=2.0——「脚本不经 SpawnUnit、不 arm 2s」
#   有反证；两计时器触发时刻不同，「固定 10s 单计时器等价」仍未证（不得擅改 12s）。
# [主动简化→静态已证近似] 当前建模为单 10.0s 计时器、出生即发射。v3.2 证据
#   （research/nc02_dual_timer.py）：ceBug ctor 与出生初始化 0x4a64b0 双处设
#   Wait[+0x448]=0.0（对话 setter 0x4a4930 无 +0x448 访问——对话不延迟发射）→
#   state1(待命) 仅 1 个 Update 即转 state4；发射 arm +0x22c=10 在 state4
#   （0x4aabc7），发射后 Wait=2.0 属 state9 出场相位（非发射前延迟，12s 排除）。
#   ⇒ 总泳道封锁≈10.0s（+0x228 的 2s 被 10s 覆盖）——单 200-tick 模型 = 静态
#   已证 ±1-2 tick 等价（对话/非对话出生同结论）。
#   发射块全局门 0x47beb0 读 [[0x54398c]+0x208]+0x114=cLevel+0x114（关卡公告/脚本
#   计时器），**严格 ==0 才放行**（fldz;fcomp;fnstsw;test ah,0x44;jnp，非「≤0」——
#   任何非零都拦，虽该字段为 +=dt 非负故观察等价）。生命周期（research/nc02_gate_reset.py
#   2026-09-20）：空闲期守卫 0x481132 jnp 跳过累加→+0x114 恒 0（门开，正常发射）；
#   cLevel+0x114 写点均在 cLevel 代码区：init 0x4801d5=0.0、reset 0x47c66c=0.0、
#   累加 0x481721/0x481990/0x481a19/0x481a35（仅当非零 +=dt）、setter 0x47bed6=0.01
#   （唯一非零 x87 写）。偏移 0x114 跨类复用（全镜像另有 x87 写 16+非x87 整型写 15，
#   均不在 cLevel 代码区，目标为其他类）。⇒ 静态可及性上 +0x114 恒 0.0、门恒放行——
#   10s 模型无门例外，**条件化**：唯一非零源 setter 0x47bed0 无 rel32/dword 静态引用，
#   但运行时计算地址间接调用未排除（[UNVERIFIED: 运行时激活]）。
LANE_COOLDOWN_SECS = 10.0
LANE_COOLDOWN_TICKS = int(round(LANE_COOLDOWN_SECS * TICK_HZ))   # 200

# ── H11 花蜜经济（T5.6 校准; 依据 docs/exe-econ.md §2） ────────────────
# H11a: 每蜜 3 点——文案锚点(lang4 LEVELOBJ_GATHER60) + 引擎硬编码
# (0x4AA875 `mov ecx,3; add [player+0x180],ecx`)
NECTAR_VALUE = 3
# H11b 证伪(原容量3/再生400t): 引擎容量=1(单蜜槽 flower+0x18c 指针);
# 再生阈值按型 type1=30s / type2,3=15s (fld 0x4E2D98/0x4E2E50→+0x188),
# R368: flower.py implements stopped initial track, independent timer LCG,
# animation edge, rescue and multiplayer gates. Count40 is only an occupied
# non-type2 restart gate; pickup does not schedule a new regeneration deadline.
FLOWER_CAPACITY = 1
FLOWER_REGEN_SECS = {1: 30.0, 2: 15.0, 3: 15.0}

ENEMY_START_NECTAR = 0  # 我方侧建模起点。引擎真身: 敌方无钱包对象（H11e ✅,
                        # 敌兵全部脚本免费出生, 收入维度不存在——setflow 即免费出兵）


def flower_regen_ticks(flower_type):
    """该型花再生阈值 tick 数（未知型按 type1, 引擎无效型永不产蜜的分支不进切片）。"""
    secs = FLOWER_REGEN_SECS.get(int(flower_type) or 1, FLOWER_REGEN_SECS[1])
    return int(round(secs * TICK_HZ))


# H11c: 拾取=物理接触表成员(0x49BFA0 扫描, 无距离判定)。接触域半径未读出
# [UNVERIFIED: 物理域] → 切片取 75u: 全 9 世界花-最近图边距离实测 max=74.5
# (world_08), 40u 会致 4 世界 9 朵花永久不可采(评审 MAJOR-2 实测)。
PICKUP_RADIUS = 75.0

# H10 证伪: 引擎无通用水域减速(WATER_SLOWDOWN=0.5 删除); 水段=游泳动画+特效,
# 速度特例: giantwaterbeetle ×1.5 (0x4AAD1A 族)。waterbeetle 值未读出
# [UNVERIFIED: waterbeetle 水段倍率]。
WATER_AFFINE = {"giantwaterbeetle": 1.5}

# T6.3: rescue 接触半径（引擎 0x4ab9a2 fadd 5.0 / 0x4ab9b6 fmul 1.5, double 常数
# 0x4e2e18/0x4e2d10; 触发 = 距离 < 1.5×(5+两虫半径和), W1 抽查 3/3。
# 切片取舍: 引擎为 3D 距离, 本模拟取 xz 平面距离（与 combat H16 口径一致;
# 高度差未建模——飞行救援判定与非引擎行为的区分见 docs 若需逐位一致再核 y 项）
RESCUE_REACH_BASE = 5.0
RESCUE_REACH_FACTOR = 1.5

# 段倍率整数推进: 速度×倍率四舍五入到整数 sub（确定性优先; 基准倍率 1.0,
# 特例仅 WATER_AFFINE 的 ×1.5）
def mult_advance(speed, mult):
    return int(speed * mult + 0.5)

# ── 战斗常数（T4.4b, 假设登记 hypotheses-runtime.md） ──────────────────
SPECIAL_RANGE = 4          # H16b: 特殊通道射程（bee/bigbangbug 名字特例自毁; spider 触及=80, 状态7 触及=AirDistance）
# H1: 自杀蛰刺单位（近战命中后按名自杀, 死亡 AOE 用 SpecialDamage 结算邻域——REVIEW-SPECIAL）
SUICIDE_UNITS = {"bee"}
# H2: 自爆单位（接战按名清血自爆, 死亡 AOE 用 SpecialDamage——REVIEW-SPECIAL）
AOE_SELFDESTRUCT_UNITS = {"bigbangbug"}
# REVIEW-SPECIAL: 状态6 spider 名字特例——SpecialDamage÷20 霰弹, 触及=RangedDistance(80)
SPIDER_SHOTGUN_UNITS = {"spider"}
# REVIEW-SPECIAL: 状态7 特攻发射单位——SpecialDamage 弹体, AIR 路径=AirDistance
SPECIAL_PROJECTILE_UNITS = {"caterpillar", "poisonpillar", "wasphero",
                            "wasphero_tick", "bomberbee"}
# REVIEW-SPECIAL: 死亡 AOE（0x4a71c0）半径 ×2 单位——名字串硬编码分支（fadd st,st @0x4a7594）;
# 余特攻单位（含 toxichero/poisonpillar/bigbangbug）半径 = AirDistance（精确 per-unit 公式 [UNVERIFIED]）
DEATH_AOE_X2_UNITS = {"wasphero", "wasphero_tick"}
