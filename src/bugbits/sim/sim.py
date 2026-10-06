"""模拟核心（T4.4a）: 20Hz 整数 tick 时钟 + 花蜜经济（买兵/采集）+ 状态 hash + 事件日志。

D3 纪律: tick 整数; declared normal ground 使用独立 f32 运动状态，
legacy 路线以 sub（1/20 u）整数推进。经济/路径 RNG（random.Random(seed)）由 Sim
持有。蜜redirect与花timer的LCG状态采用明确工程种子，不等于原GetTickCount流。
D4 纪律: 本模块不做 IO; level/world/units 由调用方装载后注入（鸭子类型:
level.initial_nectar/nectar_on_paths/player_base_size/enemy_base_size;
world.waypoints/starts/adjacency/props; units[name].speed/can_fly/can_gather/
initial_health/price）。

H11 常数在 consts.py; 假设登记 docs/hypotheses-runtime.md。
"""
import hashlib
import copy
import math
import random

from bugbits import nav
from bugbits.sim import combat, consts
from bugbits.sim.entities import Bug, Flower, Hive, NectarItem
from bugbits.sim.nectar import FlightWaypoint, NectarState, WorldClock, f32
from bugbits.sim.flower import FlowerCycle, FlowerRandom
from bugbits.sim.world_children import NamedChildren
from bugbits.assets.flower_pose import validate_rig, world_attachment
from bugbits.sim.route_policy import DirectedRoutePolicy
from bugbits.sim.motion import NormalMotion, length
from bugbits.sim.animation import WalkAnimation
from bugbits.sim.camera import CameraClientInput, NativeCamera


class Sim:
    def __init__(self, level, world, units, seed, *, camera_client_input=None):
        self.consts = consts
        self.level = level
        # Normal gameplay loads cLevel with +112=0 before START properties.
        # Use one instance view for hives, home nodes and every spawn consumer.
        world = world.normal_level_view(level.is_reversed)
        self.world = world
        self.units = units
        self.rng = random.Random(seed)          # Legacy economy/path/combat stream.
        self.world_props = dict(world.props)
        camera_keys={'MinCamDistance','MaxCamDistance','MinAngle','MaxYaw','Width','Height','Offset'}
        self.camera_client_input = (camera_client_input if camera_client_input is not None
                                    else CameraClientInput())
        self.native_camera=(NativeCamera(world.props, client_input=self.camera_client_input)
            if world.basis_version=='loaded-yup-v1' and camera_keys.issubset(world.props)
            and level.type in ('gather','battle','defense') and not level.is_reversed
            and not {'Position','Direction'}.intersection(world.props) else None)
        self.tick = 0
        self.nectar_entities = {}
        self._next_nectar_id = 1
        self._nectar_seed = int(seed) & 0xffffffff
        self.nectar_clock = WorldClock()
        self.nectar_scene=NamedChildren()
        # Composite +1D8/+1E9 sweep gate. Enabled is an engineering running-
        # world assumption; original business/paused mappings remain unverified.
        self.nectar_sweep_enabled=True
        self.flower_random = FlowerRandom(int(seed) & 0xffffffff)
        self.flower_inhibited = False  # Original level+110 gate; business writers pending.
        self.events = []                         # [(tick, 类型, 数据)]
        # T6.4/W1: multi 关 Player1 经济同构——敌侧同享 InitialNectar
        # （单人型关敌侧=无钱包的脚本经济, ENEMY_START_NECTAR 仅建模起点）
        self._enemy_has_wallet = level.type in ("multibattle", "multirandom")
        enemy_start = (level.initial_nectar if self._enemy_has_wallet
                       else consts.ENEMY_START_NECTAR)
        self.nectar = {0: int(level.initial_nectar or 0),
                       1: int(enemy_start or 0)}
        # 蜂巢: 每侧 HP 池; pos = start(side,0)（entities.Hive docstring 的粒度假设）
        self.hives = {}
        for side in (0, 1):
            s0 = world.start(side, 0)
            hp = (level.player_base_size if side == 0 else level.enemy_base_size) or 0
            self.hives[side] = Hive(side, s0.grid_pos if s0 else (0, 0, 0), int(hp))
        # lane 路线: start(side,lane) → start(1-side,lane)
        n_lanes = len({s.index for s in world.starts if s.side_id == 0})
        # 图节点坐标/家节点/邻接图（H11c 巡逻用; 确定性排序）
        self.node_pos = {}
        for x in list(world.waypoints) + list(world.starts):
            self.node_pos[x.name] = x.grid_pos
        self.home_node = {}                    # (side, lane) -> start 节点名
        for side in (0, 1):
            for lane in range(n_lanes):
                st = world.start(side, lane)
                if st is not None:
                    self.home_node[(side, lane)] = st.name
        self.graph = {n: sorted(ms) for n, ms in world.adjacency.items()
                      if n in self.node_pos}
        self.route_policy = DirectedRoutePolicy(world)
        self.lane_routes = {}
        for side in (0, 1):
            for lane in range(n_lanes):
                a, b = world.start(side, lane), world.start(1 - side, lane)
                self.lane_routes[(side, lane)] = (nav.route_between(world, a.name, b.name)
                                                  if a and b else None)
        # 实体
        self.flowers = [Flower(f.name, f.grid_pos, f.flower_type,
                               cycle=FlowerCycle.initial(f.flower_type, self.flower_random,
                                   multiplayer=self._enemy_has_wallet, rescue=level.type == 'rescue'))
                        for f in world.flowers]
        rigs = getattr(world,'flower_rigs',{})
        if not isinstance(rigs,dict):raise ValueError('flower rig mapping required')
        names={1:'flower_a',2:'flower_b',3:'cactus_a'}
        for source,flower in zip(world.flowers,self.flowers):
            flower.direction=tuple(source.direction)
            asset=names.get(flower.flower_type)
            if (rigs or getattr(world,'world_id',None) is not None) and asset and self.level.type!='rescue':
                if asset not in rigs:raise ValueError('normal flower rig missing')
                flower.rig=copy.deepcopy(validate_rig(rigs[asset]))
                if flower.rig['assetId']!=asset:raise ValueError('normal flower asset identity differs')
                flower.pose_observed=(asset=='flower_a' and getattr(world,'world_id',None)=='world_01'
                                      and world.basis_version=='loaded-yup-v1')
                flower.cached_point=self._flower_point(flower,0.)
            else:
                # Explicit historical/injected unrigged data, never an animated
                # normal-world fallback in a freshly exported resource packet.
                flower.cached_point=tuple(flower.pos)
        for index,flower in enumerate(self.flowers):
            self.nectar_scene.add('flower',index,flower.name)
        for index,source in enumerate(list(world.starts)+list(world.waypoints)+list(world.lights)):
            self.nectar_scene.add('static',index,source.name)
        self.path_nectar = self._place_path_nectar(int(level.nectar_on_paths or 0))
        self.bugs = []
        self._next_id = 1
        self.winner = None       # None=未分胜负; 0/1=胜方（T4.5 判定）
        # OF-02: 每兵种 ReloadTime 倒计时「CD」展示（原作 ceBugInfo+0x184，纯展示非门禁，
        # docs/exe-props.md §5.1）。unit_name -> 恢复可显示 tick；买兵后 arm，随 tick 自然递减。
        self.reload_until = {}
        # OFR-02B: 每泳道冷却计时器（ceStart +0x228/+0x22c，买兵/脚本出生后 arm，冷却归零前
        # 该泳道拒再出生）。key=(side, lane) -> 冷却归零 tick。买兵门禁（买兵与脚本出生
        # 均 arm；发送门禁范围见 docs/exe-props.md §5.1 OFR-02A 条）。
        self.lane_cd_until = {}
        # T6.3: defense 倒计时死线（引擎导入 +0.5s 宽限, docs/exe-econ.md §6）
        dtime = level.defense_time
        self.defense_deadline = (int(round((dtime + 0.5) * consts.TICK_HZ))
                                 if dtime is not None else None)
        self.trapped_bug = None
        if level.type == "rescue":
            self._spawn_rescue_field(level)
        self._sync_nectar_entities()

    def _new_nectar(self, pos, *, flower_index=None):
        entity_id = self._next_nectar_id
        self._next_nectar_id += 1
        entity = NectarState(entity_id, tuple(pos), born_tick=self.tick,
                             flower_index=flower_index,
                             rng_state=(self._nectar_seed + entity_id) & 0xffffffff)
        entity.instance_name=self.nectar_scene.add('nectar',entity_id,'nectar')
        self.nectar_entities[entity_id] = entity
        return entity

    def _sync_nectar_entities(self):
        """Attach identity to existing economy views, including injected path fixtures.

        Normal flower births are driven by FlowerCycle. Explicitly injected
        already-available economy fixtures can also obtain a stable identity.
        """
        for index, flower in enumerate(self.flowers):
            if flower.nectar <= 0 and flower.nectar_id is not None:
                old = self.nectar_entities[flower.nectar_id]
                if old.carrier_id is None:
                    old.request_delete()
                    old.flower_index=None
                flower.nectar_id = None
            if flower.nectar > 0 and flower.nectar_id is None:
                flower.nectar_id = self._new_nectar(flower.cached_point, flower_index=index).entity_id
        for item in self.path_nectar:
            if not item.taken and item.nectar_id is None:
                item.nectar_id = self._new_nectar(item.pos).entity_id

    def nectar_member_count(self):
        return sum(e.classification_member for e in self.nectar_entities.values())

    def nectar_scene_snapshot(self):
        container=self.nectar_scene.snapshot()
        return {**container,'containerScope':container['scope'],
                'scope':'engineering-flower-nectar-live-subset-v1',
                'sweepScope':'engineering-enabled-outer20hz-composite-gates-v1',
                'sweepEnabled':self.nectar_sweep_enabled,
                'traversalScope':'engineering-flower-nectar-live-subset-v1'}

    def _destroy_nectar(self,child):
        entity=self.nectar_entities[child.key]
        entity.destroy()
        for flower in self.flowers:
            if flower.nectar_id==entity.entity_id:
                flower.nectar_id=None;flower.nectar=0
        for item in self.path_nectar:
            if item.nectar_id==entity.entity_id:item.taken=True

    def _nectar_step(self):
        """Original live names for the modeled flower/nectar subset.

        Bugs and unmodeled scene children retain their explicit engineering
        outer order. Pending nectar self fields update before generic +12C.
        Diagnostic tombstones keep identity, but no membership or updates.
        """
        if self.nectar_sweep_enabled:
            self.nectar_scene.sweep(
                lambda c:c.kind=='nectar' and self.nectar_entities[c.key].delete_ready,
                self._destroy_nectar)
        for dt, arg2 in self.nectar_clock.advance(1 / consts.TICK_HZ, 1 / consts.TICK_HZ):
            def update(child):
                if child.kind=='nectar':
                    entity=self.nectar_entities[child.key]
                    entity.update(dt)
                    entity.finish_update(arg2)
                    return
                if child.kind!='flower':return
                index=child.key;flower=self.flowers[index]
                if flower.cycle.update(arg2, occupied=flower.nectar_id is not None,
                                       nectar_count=self.nectar_member_count(),
                                       rng=self.flower_random, inhibited=self.flower_inhibited,
                                       rescue=self.level.type == 'rescue'):
                    self._spawn_flower_nectar(index)
                if flower.nectar_id is not None:
                    attached=self.nectar_entities[flower.nectar_id]
                    if attached.alive and attached.carrier_id is None:
                        attached.set_position(flower.cached_point)
            self.nectar_scene.walk(update)
        for item in self.path_nectar:
            if item.nectar_id is not None:
                item.pos = self.nectar_entities[item.nectar_id].pos

    def _spawn_flower_nectar(self, index):
        flower = self.flowers[index]
        entity = self._new_nectar(flower.cached_point)
        if flower.nectar_id is None:
            flower.nectar_id, flower.nectar = entity.entity_id, 1
            entity.flower_index = index
        else:
            self._redirect_nectar(entity)
            self.path_nectar.append(NectarItem(len(self.path_nectar), entity.pos,
                                               nectar_id=entity.entity_id))
        self.events.append((self.tick, 'nectar_spawn', (entity.entity_id, index,
                                                       entity.flower_index is not None)))

    @staticmethod
    def _flower_point(flower,phase):
        scale=2.5 if flower.flower_type in (1,2) else 1.
        return tuple(f32(v) for v in world_attachment(flower.rig,phase,flower.pos,
                     flower.direction,scale,observed=flower.pose_observed))

    def _propagate_flower_poses(self):
        """Engineering once per outer 20Hz update, AFTER world entity work.

        Original49958D Update precedes4995A1 matrix propagation. Additional
        layer passes/initial propagation and original variable dt remain open.
        """
        for flower in self.flowers:
            if flower.rig is not None:
                if flower.cached_phase!=flower.cycle.phase:
                    flower.cached_point=self._flower_point(flower,flower.cycle.phase)
                flower.cached_phase=flower.cycle.phase
                flower.pose_generation+=1

    def _redirect_nectar(self, entity):
        outgoing, incoming = self.world.directed_links()
        nodes = {x.name: FlightWaypoint(x.name, x.grid_pos, getattr(x, 'water', False))
                 for x in list(self.world.waypoints) + list(self.world.starts)}
        for name, node in nodes.items():
            node.links130 = outgoing[name]
            node.links154 = incoming[name]
        # START init delegates to ceWayPoint init and also joins WayPoints.
        candidates = tuple(nodes[name] for name in sorted(nodes, key=lambda value:value.encode('utf-8')))
        return entity.redirect(candidates, nodes)

    def _drop_nectar(self, bug):
        """Release SAME nectar and redirect it; do not reset visual fields.

        Static candidate membership and directional links use the original
        WayPoints/ConnectTo categories; native clock and dynamic roster remain open.
        """
        entity = self.nectar_entities.get(bug.carried_nectar_id)
        if entity is None:
            return
        self._redirect_nectar(entity)
        entity.carrier_id = None
        existing = next((it for it in self.path_nectar if it.nectar_id == entity.entity_id), None)
        if existing is None:
            self.path_nectar.append(NectarItem(len(self.path_nectar), entity.pos,
                                               nectar_id=entity.entity_id))
        else:
            existing.pos, existing.taken = entity.pos, False

    # ── T6.3: rescue 开局铺场（引擎 0x482730 第一阶段, docs/exe-econ.md §3）──
    def _spawn_rescue_field(self, level):
        """BugSetup 每项 ceil(count) 份: 'trapped'→被困虫（RescueBug 兵种,
        side=0, 无敌, 被动, 静态）; 'nectarbonus'→NectarItem; 其他→敌方守军
        （side=1, idle 守点）。出生点=该泳道 SetLanes 路线池 rng.choice 1 条
        （引擎=LCG 均匀抽 1, CR MINOR-5: 每泳道可有多条路线）的敌方 START+
        抖动(±10,±3)（引擎 LCG→sim.rng, D3 分层; 引擎 z-2.5 下沉为视觉不建模）。
        切片取舍: 守军近似守点（引擎=闲置 2s 后低速巡逻 state 3, W1 已证,
        巡逻路径未建模）; TravelDistance 行进档不建模。
        """
        routes_of = {}
        for lane, r in level.set_lanes:
            routes_of.setdefault(lane, []).append(r)
        for lane, unit, count in level.bug_setups:
            pool = routes_of.get(lane)
            st = self.world.start(1, self.rng.choice(pool)) if pool else None
            if st is None:
                continue
            for _ in range(int(math.ceil(float(count)))):
                pos = (st.grid_pos[0] + self.rng.uniform(-10, 10),
                       st.grid_pos[1],
                       st.grid_pos[2] + self.rng.uniform(-3, 3))
                if unit == "trapped":
                    name = level.rescue_bug
                    spec = self.units.get(name)
                    if spec is None:
                        continue
                    bug = self._field_bug(0, name, lane, spec, pos)
                    bug.trapped = 1
                    self.trapped_bug = bug
                elif unit == "nectarbonus":
                    self.path_nectar.append(NectarItem(len(self.path_nectar), pos))
                else:
                    spec = self.units.get(unit)
                    if spec is not None:
                        self._field_bug(1, unit, lane, spec, pos)

    def _field_bug(self, side, name, lane, spec, pos):
        """铺场出生（idle 守点; 无扣费）。"""
        bug = Bug(self._next_id, side, name, int(spec.speed), bool(spec.can_fly),
                  bool(spec.can_gather), int(spec.initial_health), pos, lane)
        self._next_id += 1
        self.bugs.append(bug)
        self.events.append((self.tick, "spawn_free", (side, name, lane, bug.bug_id)))
        return bug

    # ── 装载辅助 ────────────────────────────────────────────────────────
    def _place_path_nectar(self, count):
        """H11d 校准: 全场路点随机选点→随机邻居→段 lerp 落点; 避水; 开局一次。

        依据 H11d asm (cLevel::SpawnEntities 0x482730): 全场 'WayPoints' 容器
        LCG 随机选点(非 lane0 路线) → 50/50 链随机邻居 → 线段 lerp; W/T 双重
        非水。随机走 sim.rng (D3; 引擎=GetTickCount 种子不可复现→分层表述)。
        [切片取舍: 依据 H11d] z−1.5 下沉与引擎双链(Nulls/WayPoints)结构不建模
        (合并邻接图); 引擎重试条件 [W+0x154]==0∨[W+0x130]==0 近似为度≥1。
        """
        if count <= 0:
            return []
        # pos 覆盖 waypoints+starts（邻接图含 START 节点, 与 nav.route_between 同口径）
        pos = {x.name: x.grid_pos
               for x in list(self.world.waypoints) + list(self.world.starts)}
        water = {w.name: w.water for w in self.world.waypoints}
        adj = {n: sorted(ms) for n, ms in self.world.adjacency.items()
               if not water.get(n, False)}
        cands = [n for n in sorted(adj) if adj[n]]
        items = []
        for i in range(count):
            if not cands:
                break
            w1 = self.rng.choice(cands)
            w2 = self.rng.choice(adj[w1])
            if water.get(w2, False):                      # 邻居水 → 退回 W 本体
                p = pos[w1]
            else:
                t = self.rng.random()
                a, b = pos[w1], pos[w2]
                p = (a[0] + (b[0] - a[0]) * t,
                     a[1] + (b[1] - a[1]) * t,
                     a[2] + (b[2] - a[2]) * t)
            items.append(NectarItem(i, p))
        return items

    def _sub_len(self, a, b):
        """xz 距离 → 整数 sub（确定性四舍五入）。"""
        return int(round(math.hypot(a[0] - b[0], a[2] - b[2]) * consts.SUB))

    # ── 买兵（经济支出） ────────────────────────────────────────────────
    def _lane_cd_active(self, side, lane):
        """OFR-02B：泳道冷却是否未归零（ceStart +0x22c 门禁；tick < 归零 tick = 拒绝）。"""
        return self.tick < self.lane_cd_until.get((side, lane), 0)

    def _arm_lane_cd(self, side, lane):
        """OFR-02B：出生成功即 arm 该泳道冷却（ceStart +0x22c=10.0；sendenemy 同款）。"""
        self.lane_cd_until[(side, lane)] = self.tick + consts.LANE_COOLDOWN_TICKS

    def buy(self, side, unit_name, lane, cost=None):
        """买兵: 价 ≤ 钱包才成功 → 扣价并在 start(side,lane) 出生。

        cost 给定时覆盖商店价（T4.5: 敌方 AI 上场成本 = BugSetup 预算值,
        与玩家商店价独立）。失败返回 None。OFR-02B：泳道冷却未归零 → 拒绝（无副作用）。
        """
        spec = self.units.get(unit_name)
        if spec is None:
            return None
        price = int(cost) if cost is not None else int(spec.price or 0)
        if self.nectar[side] < price:
            return None
        start = self.world.start(side, lane)
        if start is None:
            return None
        if self._lane_cd_active(side, lane):
            return None                # 冷却门禁：不扣费、不生成实体、不变 ID/RNG/计时器
        speed = self._birth_speed(spec)
        self.nectar[side] -= price
        bug = Bug(self._next_id, side, unit_name, speed, bool(spec.can_fly),
                  bool(spec.can_gather), int(spec.initial_health), start.grid_pos, lane,
                  route_current=start.name)
        self._next_id += 1
        self.bugs.append(bug)
        self._arm_lane_cd(side, lane)
        self._init_normal_motion(bug, spec, start)
        if bug.can_gather or bug.motion is not None:
            self._start_patrol(bug)
        else:
            bug.mode = "lane"
            route = self.lane_routes.get((side, lane))
            bug.route_len_sub = (int(round(route.length * consts.SUB))
                                 if route else 0)
        self.events.append((self.tick, "buy", (side, unit_name, lane, bug.bug_id, price)))
        # OF-02: arm 每兵种 ReloadTime 倒计时（原作 0x4a3710 在 Spawn 后 arm，纯展示非门禁）。
        # 只对买兵 arm，脚本 spawn_free 不 arm（原作 setflow/sendenemy 不经买兵命令）。
        rt = spec.reload_time
        if rt:
            self.reload_until[unit_name] = self.tick + int(round(rt * consts.TICK_HZ))
        return bug

    def spawn_free(self, side, unit_name, lane):
        """脚本出兵（sendenemy/sendplayer）: 不扣费, 出生于 start(side,lane)。

        H19: send* 的 lane 参数 = 路线号（START Index）。
        OFR-02B/PBA-12: 脚本也经 SpawnUnit（0x4862a0），其在创建实体前检查该泳道
        +0x22c==0（发射冷却），非零返回空 → 冷却期间脚本出生同样被拒（无副作用）。
        """
        spec = self.units.get(unit_name)
        if spec is None:
            return None
        start = self.world.start(side, lane)
        if start is None:
            return None
        if self._lane_cd_active(side, lane):
            return None          # PBA-12：+0x22c 发射冷却门禁（SpawnUnit 0x4862e9-0x4862f6）
        speed = self._birth_speed(spec)
        bug = Bug(self._next_id, side, unit_name, speed, bool(spec.can_fly),
                  bool(spec.can_gather), int(spec.initial_health), start.grid_pos, lane,
                  route_current=start.name)
        self._next_id += 1
        self.bugs.append(bug)
        self._arm_lane_cd(side, lane)
        self._init_normal_motion(bug, spec, start)
        if bug.can_gather or bug.motion is not None:
            self._start_patrol(bug)
        else:
            bug.mode = "lane"
            route = self.lane_routes.get((side, lane))
            bug.route_len_sub = (int(round(route.length * consts.SUB))
                                 if route else 0)
        self.events.append((self.tick, "spawn_free", (side, unit_name, lane, bug.bug_id)))
        return bug

    def _birth_speed(self, spec):
        # Normal Speed+3E8 is f32, with ctor default10 when absent. Resolve
        # before construction/debit; legacy actors retain integer sub-steps.
        if self.route_policy.declared and not spec.can_fly:
            return f32(10. if spec.speed is None else spec.speed)
        return int(spec.speed)

    def _init_normal_motion(self, bug, spec, start):
        if self.route_policy.declared and not bug.can_fly:
            def configured(name, default):
                value = getattr(spec, name, None)
                return default if value is None else value
            bug.motion = NormalMotion(start.grid_pos, start.direction,
                                      configured('mass',1.), configured('acceleration',500.),
                                      configured('direction_factor',20.))
            if (spec.walk_duration is not None and 'AnimBaseSpeed' in spec.props
                    and 'AnimRatio' in spec.props):
                bug.walk_animation = WalkAnimation(spec.walk_duration,
                    float(spec.props['AnimBaseSpeed'][0]), float(spec.props['AnimRatio'][0]))

    def set_dialogue(self, bug, text, delay, *, duration=10., wait=3.):
        """H6：对话延迟；不在 setter 中更改运动/攻击/既有等待。

        原0x4A4930：计时=-delay，脚本默认总长10/Wait3；BaseText为7/0，menu旁路。
        20Hz调度与等待的运动映射边界见 docs/dialogue-timing.md。
        """
        if self.level.type == "menu" or bug.dead:
            return
        if not all(math.isfinite(value) for value in (delay,duration,wait)):
            raise ValueError("dialogue timing must be finite")
        bug.dialogue_text = text
        bug.dialogue_delay = delay
        bug.dialogue_duration = duration
        bug.dialogue_wait = wait
        bug.dialogue_age = 0
        bug.dialogue_pending = wait != 0.

    def focus_camera(self,bug):
        if self.native_camera is not None:
            self.native_camera.focus(bug.bug_id)

    def _dialogue_step(self):
        for bug in self.bugs:
            if bug.dead or bug.dialogue_age < 0:
                continue
            bug.dialogue_age += 1
            elapsed = bug.dialogue_age / consts.TICK_HZ - bug.dialogue_delay
            if 1 <= elapsed < bug.dialogue_duration-2 and bug.dialogue_pending:
                bug.dialogue_pending = False
                bug.dialogue_wait_until = self.tick + int(round(bug.dialogue_wait*consts.TICK_HZ))
                # state3替换攻击态；恢复后重新起播。路径/运动采用显式近似。
                bug.attack_tick = -1
                bug.attack_ready_at = self.tick
                bug.cooldown_ticks = -1
                self.events.append((self.tick, "dialogue_wait", (bug.bug_id,)))
            if elapsed >= bug.dialogue_duration:
                bug.dialogue_age = -1
                bug.dialogue_text = ""

    # ── 采集（H11c: 图巡逻 + 接触拾取 + 反向回巢） ─────────────────────
    def _available_nectar(self):
        """[(pos, kind, index)]——花上蜜(容量1) + 未取路径蜜。"""
        out = []
        for i, f in enumerate(self.flowers):
            if f.nectar > 0:
                entity=self.nectar_entities.get(f.nectar_id)
                if entity is not None and (not entity.alive or entity.delete_requested):
                    continue
                out.append((entity.pos if entity is not None else f.cached_point, "flower", i))
        for i, it in enumerate(self.path_nectar):
            if not it.taken:
                entity=self.nectar_entities.get(it.nectar_id)
                if entity is not None and (not entity.alive or entity.delete_requested):
                    continue
                out.append((it.pos, "item", i))
        return out

    def _route_nodes(self, src, dst):
        """图上 src→dst 节点序列(Dijkstra); 同名 → (src,); 不可达 → None。"""
        if src == dst:
            return (src,)
        r = nav.route_between(self.world, src, dst)
        return tuple(r.nodes) if r else None

    @staticmethod
    def _edge_dist(p, a, b):
        """p 到图边段 (a,b) 的 xz 平面距离。"""
        ax, az, bx, bz = a[0], a[2], b[0], b[2]
        dx, dz = bx - ax, bz - az
        L2 = dx * dx + dz * dz
        if L2 == 0:
            return math.hypot(p[0] - ax, p[2] - az)
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[2] - az) * dz) / L2))
        return math.hypot(p[0] - (ax + t * dx), p[2] - (az + t * dz))

    def _nectar_route(self, cur):
        """蜜偏置路线（H11c 切片）: 候选=各未认领蜜的最近图边, 按距离排序取
        **首个近端点可达**者（图可含多个连通分量——world_02 实测 6 分量,
        最近边不可达须回退次近, 否则偏置整体失效=盲巡逻, 评审 MAJOR-1）;
        路线 = route(cur, 近端点) + (远端点,)。
        原蜜项=10/(0.20000000298023224*n+1)，本工程查询并未使用原评分。
        [切片取舍: 依据 H11c——硬梯度替代软梯度, Dijkstra 定向替代逐段评分]。"""
        curp = self.node_pos.get(cur)
        if curp is None:
            return None
        cands = []
        for p, _kind, _i in self._available_nectar():
            ebest = None
            for a, ms in self.graph.items():
                pa = self.node_pos[a]
                for b in ms:
                    k = (self._edge_dist(p, pa, self.node_pos[b]), a, b)
                    if ebest is None or k < ebest:
                        ebest = k
            if ebest is None:
                continue
            d, a, b = ebest
            da = math.hypot(curp[0] - self.node_pos[a][0],
                            curp[2] - self.node_pos[a][2])
            db = math.hypot(curp[0] - self.node_pos[b][0],
                            curp[2] - self.node_pos[b][2])
            near, far = (a, b) if da <= db else (b, a)
            cands.append((d, min(da, db), a, b, near, far))
        for _d, _dn, _a, _b, near, far in sorted(cands):
            if cur == near:
                return (near, far)
            if cur == far:
                return (far, near)
            r = self._route_nodes(cur, near)
            if r is not None:
                return r + (far,)
        return None
    def _start_patrol(self, bug, *, first_only=False):
        """出场/再出发: 图巡逻（H11c）。目的地 = 最近未认领蜜所在边（途经保证
        接触）; 无蜜 → 巡逻至敌方端点, 端点折返（引擎 Returning/远端掉头）。
        从**当前节点**续段（折返/重定向自 path 尾节点, 不瞬移）。"""
        if self.route_policy.declared and not bug.can_fly:
            bug.route_enabled = True
            if bug.motion is not None and bug.motion.controller_state == 1:
                bug.mode = 'patrol' if bug.can_gather else 'lane'
                bug.path_nodes = (bug.route_current,)
                return
            self._select_route_leg(bug, first_only=first_only)
            return
        home = self.home_node.get((bug.side, bug.lane))
        if home is None or not self.graph:
            bug.mode = "idle"
            bug.cur_pos = bug.pos(self)
            return
        cur = home
        if bug.path_nodes and 0 <= bug.path_i < len(bug.path_nodes):
            cur = bug.path_nodes[bug.path_i]   # 折返/重定向自当前节点
        nodes = self._nectar_route(cur)
        if nodes is None:                      # 无蜜 → 敌方端点巡逻
            far = self.home_node.get((1 - bug.side, bug.lane)) or home
            dest = far if cur != far else home  # 已在端点 → 折返回家
            nodes = self._route_nodes(cur, dest) or (cur,)
        bug.mode = "patrol"
        bug.path_nodes = nodes
        bug.path_i = 0
        bug.progress_sub = 0
        bug.cur_pos = self.node_pos.get(nodes[0], bug.cur_pos)
        bug.link_len_sub = (self._sub_len(self.node_pos[nodes[0]],
                                          self.node_pos[nodes[1]])
                            if len(nodes) > 1 and nodes[1] in self.node_pos else 0)

    def _select_route_leg(self, bug, *, first_only=False):
        """Normal ground CC/D0/43E, independent from physical motion.

        Live-Bugs adapter excludes immediate Sim tombstones; original generic
        removal/name ordering is still a separate scene-lifetime requirement.
        """
        position = bug.pos(self)
        peers = [peer for peer in self.bugs if not peer.dead]
        target = self.route_policy.choose(bug, peers, self.nectar_entities.values(),
                                          self.level.is_reversed, first_only=first_only)
        if (not bug.can_gather and not bug.route_returning and target is not None
                and not first_only and not self.route_policy.links(bug,self.level.is_reversed)[target]):
            # Original BaseText ABI is duration7, delay0, pendingWait0.
            text=self.units[bug.unit_name].props.get('BaseText',[None])[0]
            if text is not None:
                self.set_dialogue(bug,text,0.,duration=7.,wait=0.)
                self.focus_camera(bug)
        if bug.route_returning and target is None:
            if bug.carrying:
                self._deposit(bug)
                return
            bug.route_returning = False
            target = self.route_policy.choose(bug, peers, self.nectar_entities.values(),
                                              self.level.is_reversed, first_only=True)
        elif (bug.can_gather and not bug.route_returning
              and target is not None and not first_only):
            if not self.route_policy.links(bug, self.level.is_reversed)[target]:
                # stack2C: selected target has no successor, while CC stays put.
                bug.route_returning = True
                target = self.route_policy.choose(bug, peers, self.nectar_entities.values(),
                                                  self.level.is_reversed, first_only=True)
        # Forward current-zero-neighbor is stack68, not stack2C. Its additional
        # native command/delete business branches remain unported; no fake flip.
        bug.route_target = target
        bug.cur_pos = position
        bug.path_nodes = (bug.route_current,) + ((target,) if target is not None else ())
        bug.path_i = 0
        bug.progress_sub = 0
        bug.link_len_sub = self._sub_len(position, self.node_pos[target]) if target is not None else 0
        bug.mode = (('home' if bug.carrying else 'patrol') if bug.can_gather
                    else 'lane') if target is not None else 'idle'

    def _normal_motion_step(self, bug, *, halted=False):
        motion = bug.motion
        walk = bug.walk_animation
        if walk is not None:
            if halted:
                walk.leave_walk()
            elif motion.controller_state == 4:
                walk.select_walk(motion.velocity)
        if halted:
            # Conditional ground mode0/cap0 stages; final velocity need not0.
            motion.control_direction = motion.direction
            motion.max_speed = 0.
        elif motion.controller_state == 1:
            motion.control_direction = motion.direction
            motion.controller_state = 4
        else:
            if bug.route_target is None:
                self._select_route_leg(bug)
                # Target selection skips this call's target-present steer/cap.
            else:
                target = self.node_pos[bug.route_target]
                motion.point_at(target)
                motion.max_speed = f32(bug.speed)
                distance = length(tuple(f32(b-a) for a,b in zip(motion.position,target)))
                if distance < 20:
                    bug.route_current = bug.route_target
                    bug.route_target = None
                    bug.path_nodes = (bug.route_current,)
                    bug.path_i = 0
                    bug.progress_sub = 0
            if bug.mode == 'patrol':
                self._pickup_check(bug)
        dt = 1 / consts.TICK_HZ
        motion.advance(dt)
        if walk is not None:
            walk.advance(dt)
        if bug.route_current is not None and bug.route_target is not None:
            motion.follow_route_height(self.node_pos[bug.route_current],
                                       self.node_pos[bug.route_target],dt)

    def _walk_step(self, bug, speed):
        """当前段推进 speed sub; 到节点则续段/到达终点。返回 'moved'|'arrived'。"""
        bug.progress_sub += speed
        if bug.route_enabled:
            if bug.route_target is None or bug.progress_sub < bug.link_len_sub:
                return 'moved'
            bug.route_current = bug.route_target
            bug.route_target = None
            bug.cur_pos = self.node_pos[bug.route_current]
            bug.path_nodes = (bug.route_current,)
            bug.path_i = 0
            bug.progress_sub = 0
            return 'arrived'
        if bug.link_len_sub <= 0 or bug.progress_sub < bug.link_len_sub:
            return "moved"
        bug.path_i += 1
        bug.cur_pos = self.node_pos[bug.path_nodes[bug.path_i]]
        bug.route_current = bug.path_nodes[bug.path_i]
        bug.progress_sub = 0
        if bug.path_i + 1 >= len(bug.path_nodes):
            return "arrived"
        bug.link_len_sub = self._sub_len(
            bug.cur_pos, self.node_pos[bug.path_nodes[bug.path_i + 1]])
        return "moved"

    def _pickup_check(self, bug):
        """接触拾取（H11c 物理接触近似）: PICKUP_RADIUS 内最近未认领蜜 →
        携带+取走+反向回巢。返回是否拾取。"""
        if bug.path_i + 1 >= len(bug.path_nodes):
            return False            # 单节点退化路径无段可反向(评审 MAJOR-4 守卫)
        p = bug.pos(self)
        best, best_key, source_pos = None, None, None
        for np_, kind, i in self._available_nectar():
            d = math.hypot(p[0] - np_[0], p[2] - np_[2])
            if d <= consts.PICKUP_RADIUS and (best_key is None or (d, kind, i) < best_key):
                best, best_key = (kind, i), (d, kind, i)
                source_pos = tuple(np_)
        if best is None:
            return False
        kind, i = best
        if kind == "flower":
            f = self.flowers[i]
            entity_id = f.nectar_id
            f.nectar_id = None
            f.nectar -= 1
        else:
            entity_id = self.path_nectar[i].nectar_id
            self.path_nectar[i].taken = True
        entity = self.nectar_entities[entity_id]
        entity.flower_index = None
        entity.carrier_id = bug.bug_id
        entity.waypoint = None  # Pickup clears +3EC/+3F4, not flight clocks.
        bug.carried_nectar_id = entity_id
        bug.carrying = 1
        bug.target = (kind, i)                 # 记录来源(hash/死亡掉蜜用)
        bug.carry_pickup_tick = self.tick
        bug.carry_source_pos = tuple(entity.pos)
        bug.carry_positions = ()
        self.events.append((self.tick, "nectar_pickup", (bug.bug_id, kind, i)))
        if bug.route_enabled:
            if not bug.route_returning:
                position = bug.pos(self)
                if bug.route_target is not None:
                    bug.route_current = bug.route_target
                bug.route_target = None
                bug.route_returning = True
                bug.cur_pos = position
                bug.path_nodes = (bug.route_current,)
                bug.progress_sub = 0
                self._start_patrol(bug)
            else:
                # Original already-returning pickup exits before the CC/D0 turn.
                bug.mode = 'home'
            return True
        # 反向回巢（引擎 Returning 即时反向）: 首段 = 当前段反向(n1→n0),
        # progress 置「剩余到段起点」; 到 n0 后沿 Dijkstra 回家。
        home = self.home_node.get((bug.side, bug.lane), bug.path_nodes[0])
        n0 = bug.path_nodes[bug.path_i]
        n1 = bug.path_nodes[bug.path_i + 1]
        rest = self._route_nodes(n0, home) or (n0,)
        bug.mode = "home"
        bug.path_nodes = (n1,) + rest
        bug.path_i = 0
        bug.progress_sub = bug.link_len_sub - bug.progress_sub
        return True

    def _end_nectar_carry(self, bug, reason):
        if bug.carry_pickup_tick >= 0:
            self.events.append((self.tick, "nectar_release", (bug.bug_id, reason)))
        bug.carry_pickup_tick = -1
        bug.carry_source_pos = None
        bug.carry_positions = ()
        entity = self.nectar_entities.get(bug.carried_nectar_id)
        if entity is not None and reason != 'death':
            entity.request_delete()
            entity.carrier_id = None
        bug.carried_nectar_id = None

    def _deposit(self, bug):
        home = self.home_node.get((bug.side, bug.lane))
        if not bug.route_enabled:
            bug.cur_pos = self.node_pos.get(home, bug.cur_pos)
        bug.route_returning = False
        if bug.side == 1 and not self._enemy_has_wallet:
            # H11e: 敌方无钱包——敌采集虫交付不入账(引擎单人侧无 Player1 对象,
            # 评审 MINOR-2; 蜜消失, 与旧「nectar[1]+=3」的表述矛盾修平)。
            # T6.4 CR 严重-1: multi 关 Player1 经济同构(W1)——采集交付完整入账
            bug.carrying = 0
            self._end_nectar_carry(bug, "deposit-no-wallet")
            bug.target = None
            self._start_patrol(bug, first_only=bug.route_enabled)
            return
        self.nectar[bug.side] += consts.NECTAR_VALUE
        self.events.append((self.tick, "deposit", (bug.side, consts.NECTAR_VALUE)))
        bug.carrying = 0
        self._end_nectar_carry(bug, "deposit")
        bug.target = None
        self._start_patrol(bug, first_only=bug.route_enabled)

    # ── lane 行军（含水域段倍率） ────────────────────────────────────────
    def _lane_mult(self, bug):
        """lane 行军段倍率: 基准 1.0 (H10 证伪: 无通用减速);
        水段单位特例查 WATER_AFFINE (giantwaterbeetle ×1.5)。"""
        route = self.lane_routes.get((bug.side, bug.lane))
        if route is None or bug.can_fly:
            return 1.0
        base = 1.0
        mult = consts.WATER_AFFINE.get(bug.unit_name, 1.0)
        cum = bug.progress_sub
        for i, l in enumerate(route.seg_len):
            seg_sub = int(round(l * consts.SUB))
            if cum < seg_sub or i == len(route.seg_len) - 1:
                # H10: ×1.5 要求段**两端点**均 water(0x4AA58C/0x4AAD40,
                # exe-props §3)——water_seg[i]=段终点, water_seg[i-1]=段起点
                if route.water_seg[i] and i > 0 and route.water_seg[i - 1]:
                    return mult
                return base
            cum -= seg_sub
        return base

    # ── 时钟 ────────────────────────────────────────────────────────────
    def step(self, *, before_world=None):
        """推进1 tick：花动画/蜜派发 → 对话计时/等待 → 战斗 → 移动。"""
        self.tick += 1
        if before_world is not None:
            before_world()
        if self.native_camera is not None:
            tracked=next((b for b in self.bugs if b.bug_id==self.native_camera.tracked_id
                          and not b.dead),None)
            sample=None
            if tracked is not None:
                x,y,z=tracked.pos(self)
                sample={'id':tracked.bug_id,'positionRaw':(z,-x,-y),
                        'dialogueDuration':tracked.dialogue_duration,
                        'dialogueElapsed':tracked.dialogue_age/consts.TICK_HZ-tracked.dialogue_delay}
            self.native_camera.advance(1/consts.TICK_HZ,sample)
        self._sync_nectar_entities()
        self._nectar_step()
        self._dialogue_step()
        # 战斗（接战者本 tick 不移动）
        engaged = combat.combat_tick(self)
        # 虫（按 id 序 = 创建序, 确定性）
        for bug in sorted(self.bugs, key=lambda b: b.bug_id):
            if bug.motion is not None:
                # Preserve the public engineering idle/defender contract;
                # native controller state1 still advances for marching bugs.
                if not bug.dead and bug.mode != 'idle':
                    self._normal_motion_step(bug, halted=(bug.bug_id in engaged
                                             or self.tick < bug.dialogue_wait_until))
                elif bug.mode == 'idle' and bug.walk_animation is not None:
                    bug.walk_animation.leave_walk()
                continue
            if (bug.dead or bug.bug_id in engaged
                    or self.tick < bug.dialogue_wait_until):
                continue
            if bug.mode == "patrol":
                st = self._walk_step(bug, bug.speed)
                if st == "arrived":
                    self._start_patrol(bug)          # 端点折返/重定向
                else:
                    self._pickup_check(bug)
            elif bug.mode == "home":
                st = self._walk_step(bug, bug.speed)
                if st == "arrived":
                    if bug.route_enabled:
                        self._start_patrol(bug)
                    else:
                        self._deposit(bug)
            elif bug.mode == "lane":
                bug.progress_sub += consts.mult_advance(bug.speed, self._lane_mult(bug))
            # idle: 静态待命（引擎 state1; place() 类测试锚定用, 不自动巡逻）
        # 每个工程tick采样，包括接战/对话等待的静止虫。拾取当tick不推进过渡。
        for bug in self.bugs:
            if (not bug.dead and bug.carrying and 0 <= bug.carry_pickup_tick < self.tick
                    and len(bug.carry_positions) < 10):
                bug.carry_positions += (tuple(bug.pos(self)),)
            if not bug.dead and bug.carrying and bug.carried_nectar_id is not None:
                # Same bounded carry recurrence as R364, with explicitly retained
                # engineering outer clock; source is the actual cached entity point.
                entity = self.nectar_entities[bug.carried_nectar_id]
                if self.tick > bug.carry_pickup_tick:
                    target = tuple(f32(v + (self.units[bug.unit_name].radius if i == 1 else 0))
                                   for i, v in enumerate(bug.pos(self)))
                    age = self.tick - bug.carry_pickup_tick
                    elapsed = 0.0
                    for _ in range(min(age, 10)):
                        elapsed = f32(elapsed + f32(1 / consts.TICK_HZ))
                    weight = 1.0 if elapsed > .5 or age > 10 else f32(elapsed / .5)
                    entity.set_position(tuple(f32(f32(v * (1 - weight)) + f32(t * weight))
                                              for v, t in zip(entity.pos, target)))
        if self.native_camera is not None:
            self.native_camera.finish_frame()
        self._propagate_flower_poses()
        # 胜负判定（T4.5）
        self._check_victory()

    def run(self, n):
        for _ in range(n):
            self.step()

    # ── 胜负判定（T4.5） ────────────────────────────────────────────────
    def _check_victory(self):
        """battle: 巢破定胜负（敌巢先判=同 tick 双破取玩家胜, 切片自选未证）;
        defense: 倒计时≤0 存活胜 ∨ 敌巢破胜, 我巢破负;
        gather: 花蜜达标; rescue: 接触被困虫胜, 超时/巢破负（T6.3/W1）;
        multi: 我巢破先判（与 battle 相反, W1 证据序）, 超时 HP 高者胜/
        等值 TIMEUP 双败（T6.4/W1）;
        challenge: 生存模式（Objective=SURVIVELONG, "四 Type" 0x48E830 不含 challenge）
        无胜出分支——仅公共负路径（0x49261a 我巢破→负）适用;
        menu 切片不判定（winner 保持 None）。
        """
        if self.winner is not None:
            return
        t = self.level.type
        if t == "defense":
            # 引擎 0x4924DC/0x49252C 序: 倒计时(胜) → 敌巢(胜) → 我巢(负)
            if (self.defense_deadline is not None
                    and self.tick >= self.defense_deadline):
                self.winner = 0
                self.events.append((self.tick, "survived", (0,)))
                self.events.append((self.tick, "victory", (0,)))
            elif self.hives[1].hp <= 0:
                self.winner = 0
                self.events.append((self.tick, "victory", (0,)))
            elif self.hives[0].hp <= 0:
                self.winner = 1
                self.events.append((self.tick, "victory", (1,)))
        elif t in ("multibattle", "multirandom"):
            # T6.4/W1 证据序: 我巢破(负)先于敌巢破(胜, 与单人 battle 相反);
            # 超时 HP 高者胜/严格相等 TIMEUP 双败(本地视角=负)。落后方扣 10.0
            # 为引擎表现一拍, 切片省略; multirandom 虫栏随机化不建模(无栏概念)
            if self.hives[0].hp <= 0:
                self.winner = 1
                self.events.append((self.tick, "victory", (1,)))
            elif self.hives[1].hp <= 0:
                self.winner = 0
                self.events.append((self.tick, "victory", (0,)))
            elif (self.defense_deadline is not None
                    and self.tick >= self.defense_deadline):
                if self.hives[1].hp > self.hives[0].hp:
                    self.winner = 1
                elif self.hives[0].hp > self.hives[1].hp:
                    self.winner = 0
                else:
                    self.winner = 1
                # 超时无论 HP 领先与否都发 timeup（终局原因），host 据此显示「时间到」
                self.events.append((self.tick, "timeup", (self.winner,)))
                self.events.append((self.tick, "victory", (self.winner,)))
        elif t == "battle":
            if self.hives[1].hp <= 0:
                self.winner = 0
                self.events.append((self.tick, "victory", (0,)))
            elif self.hives[0].hp <= 0:
                self.winner = 1
                self.events.append((self.tick, "victory", (1,)))
        elif t == "rescue":
            # W1 证据序: 接触胜(优先) → 超时负 → 巢破负
            # 距离用 pos() 推导位置（CR MAJOR-1: lane 行军虫 cur_pos 停出生点）
            tb = self.trapped_bug
            if tb is not None and not tb.dead:
                tp = tb.pos(self)
                reach = consts.RESCUE_REACH_FACTOR * (
                    consts.RESCUE_REACH_BASE
                    + self.units[tb.unit_name].radius)
                for b in self.bugs:
                    if (b.side == 0 and not b.dead and not b.trapped):
                        d = ((b.pos(self)[0] - tp[0]) ** 2
                             + (b.pos(self)[2] - tp[2]) ** 2) ** 0.5
                        if d < reach + consts.RESCUE_REACH_FACTOR * self.units[b.unit_name].radius:
                            self.winner = 0
                            self.events.append((self.tick, "rescued", (0,)))
                            self.events.append((self.tick, "victory", (0,)))
                            return
            if (self.defense_deadline is not None
                    and self.tick >= self.defense_deadline):
                self.winner = 1
                self.events.append((self.tick, "timeup", (1,)))
                self.events.append((self.tick, "victory", (1,)))
            elif self.hives[0].hp <= 0:
                self.winner = 1
                self.events.append((self.tick, "victory", (1,)))
        elif t == "gather":
            goal = self.level.goal_nectar
            if goal is not None and self.nectar[0] >= goal:
                self.winner = 0
                self.events.append((self.tick, "victory", (0,)))
            elif self.hives[0].hp <= 0:
                # 引擎 0x49261a 公共负: 全 Type 我巢破→负（胜分支优先显示）
                self.winner = 1
                self.events.append((self.tick, "victory", (1,)))
        elif t == "challenge":
            # T6.6: challenge=生存模式（Objective=SURVIVELONG, 胜负总函数 0x48E830
            # "四 Type" 不含 challenge → 无胜出分支）。仅公共负路径 0x49261a
            # 我巢破→负适用; 否则 winner 保持 None（无终局胜）。
            if self.hives[0].hp <= 0:
                self.winner = 1
                self.events.append((self.tick, "victory", (1,)))

    # ── 状态 hash（D3: 断言状态而非像素） ────────────────────────────────
    def state_hash(self):
        """可变状态摘要（REVIEW-02 补齐 winner/ID 分配器/RNG 内部状态）。

        RNG 用 getstate()（不消耗随机流）——同种子且同调用序列 → 同 state；
        不同调用次数 → 不同 state，可检出漏测的随机消耗。ScriptVM/Bot 状态
        在对象各自的 state_repr()，由确定性测试合并比对（不在本方法内）。
        血量/位置不截断到显示精度（全 repr）；静态配置（关卡/世界/单位）由装载方
        指纹识别，胜负期限 defense_deadline 并入本摘要以覆盖胜负死线敏感。
        """
        parts = [f"t{self.tick}", f"n{self.nectar[0]},{self.nectar[1]}",
                 f"w{self.winner}", f"id{self._next_id}",
                 f"dl{self.defense_deadline}",
                 f"rl{self.reload_until!r}",
                 f"lc{sorted(self.lane_cd_until.items())!r}",
                 f"ni{self._next_nectar_id}:{self._nectar_seed}",
                 f"nc{self.nectar_clock.snapshot()!r}",
                 f"ns{self.nectar_scene_snapshot()!r}",
                 f"rng{self.rng.getstate()!r}"]
        if self.native_camera is not None:
            parts.append(f"camera{self.native_camera.snapshot()!r}")
        for side in (0, 1):
            h = self.hives[side]
            parts.append(f"h{h.side}:{h.hp!r}")
        for f in self.flowers:
            parts.append(f"f{f.name}:{f.nectar}:{f.nectar_id!r}:{f.cycle.snapshot()!r}:"
                         f"{f.pose_snapshot()!r}:{f.direction!r}")
        parts.append(f"flowerRng={self.flower_random.state}:inhibited={self.flower_inhibited}")
        for entity in self.nectar_entities.values():
            parts.append(f"ne{entity.snapshot()!r}")
        for it in self.path_nectar:
            parts.append(f"i{it.item_id}:{int(it.taken)}@"
                         f"{it.pos[0]!r},{it.pos[1]!r},{it.pos[2]!r}:{it.nectar_id!r}")
        for b in sorted(self.bugs, key=lambda x: x.bug_id):
            tgt = f"{b.target[0]}{b.target[1]}" if b.target else "-"
            motion_state = b.motion.snapshot() if b.motion is not None else None
            walk_state = b.walk_animation.snapshot() if b.walk_animation is not None else None
            parts.append(f"b{b.bug_id}:{b.side},{b.unit_name},{b.hp!r},{b.lane},"
                         f"{b.mode},{b.progress_sub},{b.carrying},{tgt},"
                         f"{b.carry_pickup_tick},{b.carry_source_pos!r},{b.carry_positions!r},"
                         f"{b.carried_nectar_id!r},"
                         f"{b.dead},{b.cooldown_ticks},{b.reload_until},"
                         f"{b.speed!r},"
                         f"{b.path_i},{b.link_len_sub},{b.route_len_sub},"
                         f"{b.trapped},{b.path_nodes!r},{b.cur_pos!r},"
                         f"{b.route_enabled},{b.route_current!r},{b.route_target!r},{b.route_returning},"
                         f"{motion_state!r},"
                         f"{walk_state!r},"
                         f"{b.attack_tick},{b.attack_ready_at},"
                         f"{b.dialogue_text!r},{b.dialogue_delay!r},{b.dialogue_age},"
                         f"{b.dialogue_pending},{b.dialogue_wait_until},"
                         f"{b.dialogue_duration!r},{b.dialogue_wait!r}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
