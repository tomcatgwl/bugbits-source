"""关卡装载层: scripts/levels/*.vsc → LevelData（T4.2）。

语义定调（research/t42_semantics.py, 63 关数据 pass）:
  BugSetup <泳道 0-3> <单位> <花蜜 1-100>   敌方经济泳道可上场单位与预算
  SetLanes  <泳道 a> <路线 b>               泳道 a 沿路线 b (=START Index) 进军;
                                            a ∈ 该关 BugSetup 泳道集 (63/63);
                                            b < 世界每侧 START Index 数 (44/44);
                                            空集 ⟺ menu/multibattle/multirandom
  Script "子命令 参数..."                    时间轴（保序, T4.5 解释器消费）
胜负属性: gather→GoalNectar(5/5), rescue→RescueBug(14/14),
          battle/defense/multibattle/multirandom→摧毁敌方蜂巢 (T4.5 判定)。
"""
from dataclasses import dataclass, field

from bugbits.assets import vsc


@dataclass
class LevelData:
    props: dict
    bug_setups: list = field(default_factory=list)   # [(lane, unit, nectar)]
    set_lanes: list = field(default_factory=list)    # [(lane, route)]
    scripts: list = field(default_factory=list)      # [(sub, [args])] 保序
    unlock: str = None
    light_requests: list = field(default_factory=list)  # raw nine-token requests, file order

    def _num(self, key):
        return float(self.props[key][0]) if key in self.props else None

    def _int(self, key):
        v = self._num(key)
        return int(v) if v is not None else None

    def _str(self, key):
        return self.props[key][0] if key in self.props else None

    @property
    def world_name(self):
        return self._str("World")

    @property
    def type(self):
        return self._str("Type")

    @property
    def player_base_size(self):
        return self._int("PlayerBaseSize")

    @property
    def enemy_base_size(self):
        return self._int("EnemyBaseSize")

    @property
    def initial_nectar(self):
        return self._int("InitialNectar")

    @property
    def nectar_on_paths(self):
        return self._int("NectarOnPaths")

    @property
    def is_reversed(self):
        return self._num("IsReversed") not in (None, 0.0)

    @property
    def goal_nectar(self):
        return self._int("GoalNectar")

    @property
    def rescue_bug(self):
        return self._str("RescueBug")

    @property
    def defense_time(self):
        return self._int("DefenseTime")

    @property
    def music(self):
        return self._str("Music")

    @property
    def name_text(self):
        return self._str("NameText")


def light_tokens(args):
    """Preserve raw setlight tokens; downstream parameter semantics are separate."""
    if (not isinstance(args, (list, tuple)) or len(args) != 9
            or any(not isinstance(arg, str) or not arg or arg.split() != [arg] for arg in args)):
        raise ValueError('setlight requires nine raw tokens')
    return tuple(args)


def parse_level(path):
    """关卡 .vsc → LevelData。"""
    props, bug_setups, set_lanes, scripts, unlock = {}, [], [], [], None
    lights = []
    for _, cmd, args in vsc.parse_vsc(path):
        if cmd == "sp" and args:
            props.setdefault(args[0], args[1:])
        elif cmd == "BugSetup" and len(args) == 3:
            bug_setups.append((int(args[0]), args[1], int(args[2])))
        elif cmd == "SetLanes" and len(args) == 2:
            set_lanes.append((int(args[0]), int(args[1])))
        elif cmd == "Script" and args:
            parts = args[0].split()
            scripts.append((parts[0], parts[1:]))
        elif cmd == "UnlockLevel" and args:
            unlock = args[0]
        elif cmd == "setlight":
            lights.append(light_tokens(args))
    return LevelData(props, bug_setups, set_lanes, scripts, unlock, lights)
