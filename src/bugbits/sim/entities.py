"""模拟实体：normal motion保存独立f32状态，legacy路线按整数进度推导。"""
from dataclasses import dataclass


@dataclass
class Hive:
    """每侧一个 HP 池（BaseSize）；pos 取 start(side,0) 代表点（T4.4b 战斗锚）。

    [UNVERIFIED: 巢实体粒度] 引擎 START 每路线一个锚点；本切片取侧级单一 HP 池,
    存款/出生在各 lane 的 START（Bug.spawn_pos）。
    """
    side: int
    pos: tuple             # (x,y,z) 网格 Y-up
    hp: int                # BaseSize（巢 HP; 战斗判定在 T4.4b）


@dataclass
class Flower:
    name: str
    pos: tuple
    flower_type: int
    nectar: int = 0        # 单蜜槽初始空；由动画边沿生成，不按拾取排期限。
    nectar_id: int = None
    cycle: object = None   # FlowerCycle；独立timer/track/cache进入未来状态。
    rig: object = None     # Validated static normal-flower configuration.
    direction: tuple = (0.,0.,1.)
    pose_observed: bool = False
    cached_phase: float = 0.
    cached_point: tuple = None
    pose_generation: int = 0

    def pose_snapshot(self):
        return {'scope':'cached-world-pose-20hz-v1' if self.rig else 'engineering-source-origin-v1',
                'phase':self.cached_phase,'cachedPositionYup':list(self.cached_point),
                'generation':self.pose_generation,
                'rigSHA256':self.rig['rigSHA256'] if self.rig else None,
                'ownerScope':'static-ceFlower-direction-c-f-minus-u-v1' if self.pose_observed
                             else 'engineering-orthonormal-raw-x-forward-v1',
                'initialScope':'engineering-phase-zero-cache-v1'}


@dataclass
class NectarItem:
    """路径蜜（NectarOnPaths 布点）。taken 后不从列表移除（索引/hash 稳定）。"""
    item_id: int
    pos: tuple
    taken: bool = False
    nectar_id: int = None


@dataclass
class Bug:
    bug_id: int
    side: int
    unit_name: str
    speed: float           # normal f32 u/s; legacy retains integer sub-step adapter.
    can_fly: bool
    can_gather: bool
    hp: int
    spawn_pos: tuple       # 出生 START 位置（采集往返的家/存款点）
    lane: int = 0
    mode: str = "idle"     # idle|patrol|home|lane（H11c 巡逻三态 + lane 行军）
    progress_sub: int = 0  # 当前段已推进 sub 数（整数）
    carrying: int = 0      # 0/1
    target: tuple = None   # ("flower", i) | ("item", i) | None（拾取来源, hash/掉蜜用）
    carry_pickup_tick: int = -1
    carry_source_pos: tuple = None
    carry_positions: tuple = ()  # 首10个拾取后20Hz位置；包含静止tick，不按RAF计时
    carried_nectar_id: int = None
    route_len_sub: int = 0  # lane 模式路线总长 sub（整数, 起段时确定）
    cur_pos: tuple = None  # 段边界锚点（到节点时更新; idle 即停在此, 不入 hash）
    path_nodes: tuple = ()  # 巡逻节点序列(名); patrol/home 共用（H11c）
    path_i: int = 0         # 当前段索引([path_i] → [path_i+1]）
    link_len_sub: int = 0   # 当前段长 sub
    route_enabled: bool = False
    route_current: str = None  # Normal logical4CC, separate from physical point.
    route_target: str = None   # Normal4D0 target; reselected at each boundary.
    route_returning: bool = False  # Independent43E, including empty-handed return.
    motion: object = None    # NormalMotion; physical/body state separate from CC/D0.
    walk_animation: object = None  # Finite normal-ground instance track, not render time.
    # ── 战斗字段（T4.4b）──
    dead: int = 0            # 0/1（死亡留在列表保 hash 稳定, 退出一切交互）
    cooldown_ticks: int = -1  # -1=未接战; >0=距下次命中; 0=就绪即击
    reload_until: int = 0    # 远程/特攻发射后 Reload 秒冷却的下一可发射 tick（H3 修正）
    trapped: int = 0         # 1=被困虫（T6.3: 无敌+静态, 引擎 state 11）
    attack_tick: int = -1     # 近战动画已推进 tick；-1=未播/圈末等待
    attack_ready_at: int = 0  # 圈末等待到期 tick
    dialogue_text: str = ""
    dialogue_delay: float = 0.0
    dialogue_duration: float = 10.0
    dialogue_wait: float = 3.0
    dialogue_age: int = -1     # -1=无文本计时；否则设置后经过的20Hz更新数
    dialogue_pending: bool = False  # 原+0x48c待消费的3秒Wait
    dialogue_wait_until: int = 0

    def __post_init__(self):
        if self.cur_pos is None:
            self.cur_pos = self.spawn_pos

    def target_pos(self, sim):
        """拾取来源位置（H11c 后仅兼容保留; pos 不再依赖）。"""
        if self.target is None:
            return self.spawn_pos
        kind, i = self.target
        if kind == "flower":
            return sim.flowers[i].pos
        return sim.path_nectar[i].pos

    def pos(self, sim):
        """物理位置：normal motion 存储并入hash，legacy 按路线进度推导。"""
        if self.motion is not None:
            return self.motion.position
        if self.mode == "idle":
            return self.cur_pos
        if self.route_enabled:
            if self.route_target is None or self.link_len_sub <= 0:
                return self.cur_pos
            target = sim.node_pos[self.route_target]
            f = min(1., self.progress_sub / self.link_len_sub)
            return tuple(a + (b-a)*f for a,b in zip(self.cur_pos,target))
        if self.mode == "lane":
            route = sim.lane_routes.get((self.side, self.lane))
            if route is None:
                return self.cur_pos
            s = self.progress_sub / sim.consts.SUB
            if self.can_fly:
                fh = float(sim.world_props.get("FlyHeight", ["80"])[0])
                return route.position_at(s, fly_height=fh)
            return route.position_at(s)
        b = self._link_endpoints(sim)
        if b is None:
            return self.cur_pos
        (ax, ay, az), (bx, by, bz) = b
        if self.link_len_sub <= 0:
            return (ax, ay, az)
        f = min(1.0, self.progress_sub / self.link_len_sub)
        return (ax + (bx - ax) * f, ay + (by - ay) * f, az + (bz - az) * f)

    def body_pos(self, sim):
        """Display sample before the conditional post-physics route-height write."""
        return self.motion.body_position if self.motion is not None else self.pos(sim)

    def _link_endpoints(self, sim):
        """当前段两端点坐标（H11c 巡逻/回巢的节点插值）。"""
        if not self.path_nodes or self.path_i + 1 >= len(self.path_nodes):
            return None
        pos = sim.node_pos[self.path_nodes[self.path_i]]
        nxt = sim.node_pos[self.path_nodes[self.path_i + 1]]
        return pos, nxt
