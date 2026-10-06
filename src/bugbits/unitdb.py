"""单位数据库: bugs/*.vsc + buginfos/*.vsc 三源合并 → UnitSpec（T4.2）。

三源（docs/units.md）:
  bugs/{name}.vsc    物理 + 战斗数值 + 模型/动画/音效引用
  buginfos/{name}.vsc UI 文案键 + Price/Priority/ReloadTime
  levels BugSetup    经济投放（不在本模块, 由 level.py 承载）
两侧各 24 名单（20 本体 + 4 _tick 坐骑变体）; 引擎特例 nectarbonus/trapped
无 buginfos → load_unit 抛 KeyError（BugSetup 消费方用白名单豁免）。
"""
import os
from dataclasses import dataclass, field

from bugbits.assets import data_dir, vsc, van

# bugs/*.vsc 数值属性 → UnitSpec typed 字段（float 化; 缺省 None）
STAT_FIELDS = {
    "Speed": "speed",
    "Acceleration": "acceleration",
    "DirectionFactor": "direction_factor",
    "Radius": "radius",
    "Mass": "mass",
    "InitialHealth": "initial_health",
    "MeleeDamage": "melee_damage",
    "MeleeDistance": "melee_distance",
    "AirDistance": "air_distance",
    "RangedDamage": "ranged_damage",
    "RangedDistance": "ranged_distance",
    "RangedRange": "ranged_range",
    "SpecialDamage": "special_damage",
    "HiveDamage": "hive_damage",
    "AttackSpeed": "attack_speed",
    "AttackWaitMin": "attack_wait_min",
    "AttackWaitMax": "attack_wait_max",
    "AttackHitFrame": "attack_hit_frame",
    "Reload": "reload",
}

ANIM_FIELDS = {
    "AnimWalk": "walk",
    "AnimIdle": "idle",
    "AnimNormalAttack": "normal_attack",
    "AnimHurt": "hurt",
    "AnimSpecialAttack": "special_attack",
    "AnimSpecialMove": "special_move",
}


@dataclass
class UnitSpec:
    name: str
    price: int = None                 # buginfos Price
    priority: int = None              # buginfos Priority
    reload_time: int = None           # buginfos ReloadTime（UI 展示字段; 不参与战斗装填 H3/W1）
    can_fly: bool = False             # bugs CanFly
    can_gather: bool = False          # bugs CanGather
    model: str = None                 # bugs Model
    anims: dict = field(default_factory=dict)
    props: dict = field(default_factory=dict)        # bugs 原始属性
    info_props: dict = field(default_factory=dict)   # buginfos 原始属性
    attack_hit_frames: tuple = ()      # 全部近战命中阈值，不丢弃第 2-4 段
    attack_duration: float = None      # normal_attack 根动画时长，缺失不猜测
    walk_duration: float = None        # walk 当前首个有效节点的末键时间


def _props(path):
    out = {}
    for _, cmd, args in vsc.parse_vsc(path):
        if cmd == "sp" and args:
            out.setdefault(args[0], args[1:])
    return out


def apply_props(spec):
    """props/info_props → typed 字段（speed 等动态属性）。

    _load_spec（原解析）与 web_data.restore_unit（JSON 恢复）共用本推导，
    保证恢复对象与原解析对象的**全部实例属性**一致（dataclass __eq__ 只比
    声明字段，speed/melee_damage 等 setattr 动态属性不在其中——W2 B01 抓出
    的假绿，A05 已补动态属性比对）。
    """
    def num(d, key):
        return float(d[key][0]) if key in d else None

    for src, dst in STAT_FIELDS.items():
        setattr(spec, dst, num(spec.props, src))
    if "CanFly" in spec.props:
        spec.can_fly = float(spec.props["CanFly"][0]) != 0.0
    if "CanGather" in spec.props:
        spec.can_gather = float(spec.props["CanGather"][0]) != 0.0
    spec.model = spec.props.get("Model", [None])[0]
    for src, dst in ANIM_FIELDS.items():
        if src in spec.props:
            spec.anims[dst] = spec.props[src][0]
    spec.attack_hit_frames = tuple(float(x) for x in spec.props.get("AttackHitFrame", []))
    spec.price = int(float(spec.info_props["Price"][0])) if "Price" in spec.info_props else None
    spec.priority = int(float(spec.info_props["Priority"][0])) if "Priority" in spec.info_props else None
    spec.reload_time = (int(float(spec.info_props["ReloadTime"][0]))
                        if "ReloadTime" in spec.info_props else None)


def _load_spec(name):
    bugs_path = data_dir("scripts", "bugs", name + ".vsc")
    info_path = data_dir("scripts", "buginfos", name + ".vsc")
    if not (os.path.isfile(bugs_path) and os.path.isfile(info_path)):
        raise KeyError(f"未知单位 {name!r} (bugs/buginfos 任一缺失)")
    spec = UnitSpec(name, props=_props(bugs_path), info_props=_props(info_path))
    apply_props(spec)
    if "normal_attack" in spec.anims:
        path = spec.anims["normal_attack"].lower() + ".van"
        blocks = van.parse_van(data_dir("models", *path.split("/")))
        # GetCurAnimTime/GetLoopCount 优先当前节点，有效动画不存在时才向子节点找。
        keys = next((block for block in blocks if block), None)
        if keys:
            spec.attack_duration = keys[-1][0]
    if "walk" in spec.anims:
        path = spec.anims["walk"].lower() + ".van"
        blocks = van.parse_van(data_dir("models", *path.split("/")))
        keys = next((block for block in blocks if block), None)
        if keys:
            spec.walk_duration = keys[-1][0]
    return spec


def load_unit(name):
    """单位名 → UnitSpec（bugs+buginfos 合并）。未知单位抛 KeyError。"""
    return _load_spec(name)


def load_all():
    """全部单位（bugs ∩ buginfos 名单 = 24: 20 本体 + 4 _tick 坐骑变体）。"""
    bugs = {f[:-4] for f in os.listdir(data_dir("scripts", "bugs")) if f.endswith(".vsc")}
    infos = {f[:-4] for f in os.listdir(data_dir("scripts", "buginfos")) if f.endswith(".vsc")}
    return {n: _load_spec(n) for n in sorted(bugs & infos)}
