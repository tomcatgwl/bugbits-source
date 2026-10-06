"""Web 命令桥（W2，合同 §4/§5）：JS/宿主只经本接口改变游戏；CPython/Pyodide 共用。

调度相位（唯一合同，= cli.py:_cmd_play / test_e2e.run_game 既有顺序）：
每 tick N：sim.step() → vm.on_tick() → 控制相位（到期命令按提交序 →
multi 敌方 Bot）。胜局后冻结（advance 不再推进，对齐 cli.play while winner is None）。

纯度：零 IO / 零 PIL——数据经 init 参数注入（浏览器由宿主 fetch JSON 后传入；
A 层对照用 from_objects 直接注入原解析对象）。禁止越过本桥改 sim 内部状态；
玩家买兵仅受校验 buy（无 cost 覆盖、无 spawn_free 入口）。

事件：sim.events 追加桥序号 {seq,tick,type,data}；保留上限 EVENT_RETENTION，
超出丢弃最旧并按 afterSeq 与保留底界判定 gap（游标只前进，不重发已确认 seq）。
receipt 语义（合同 §4.2 细化）：submit 同步返回结构校验/排队回执；
执行结果（含 E_PRICE/E_ENDED）经事件 buy_ok/buy_reject + 命令日志交付。
"""
import json

from bugbits import bot as botmod
from bugbits import scriptvm, web_data
from bugbits.sim import sim as simmod
from bugbits.sim.camera import CameraClientInput

EVENT_RETENTION = 10000
EVENT_BATCH = 1000
MAX_ADVANCE = 5


class WebBridge:
    def __init__(self):
        self._n_sessions = 0
        self.session = None            # _Session | None
        # Like cInterface, this survives world replacement, owned by this bridge.
        self.camera_client_input = CameraClientInput()

    # ── 会话 ────────────────────────────────────────────────────────
    def from_objects(self, level, world, units, seed, opts=None):
        """A 层：原解析对象直接构建（H2 A↔B 数据导出对照）。"""
        return self._open(level, world, units, seed, opts)

    def init(self, level_id, seed, level_data, world_data, units_data, opts=None):
        """B/C 层：导出 JSON dict → 恢复对象构建（禁止原文件装载）。"""
        level = web_data.restore_level(level_data)
        world = web_data.restore_world(world_data)
        units = web_data.restore_units(units_data)
        return self._open(level, world, units, seed, opts,
                          level_id=level_id)

    def _open(self, level, world, units, seed, opts, level_id=None):
        opts = dict(opts or {})
        self._n_sessions += 1
        sim = simmod.Sim(level, world, units, seed=seed,
                         camera_client_input=self.camera_client_input)
        vm = scriptvm.ScriptVM(sim, level)
        enemy = None
        if opts.get("enemyBot"):
            enemy = botmod.Bot(side=1, **opts["enemyBot"])
        buyable = list(opts.get("buyable") or [])
        retention = int(opts.get("eventRetention") or EVENT_RETENTION)
        self.session = _Session(
            sid=f"s{self._n_sessions}", level_id=level_id, sim=sim, vm=vm,
            enemy_bot=enemy, buyable=buyable, seed=seed, retention=retention)
        self._drain_events()
        return {"sessionId": self.session.sid, "tick": 0,
                "winner": None, "buyable": buyable,
                "levelType": level.type}

    def reset(self, level_id, seed, level_data, world_data, units_data,
              opts=None):
        self.dispose()
        return self.init(level_id, seed, level_data, world_data,
                         units_data, opts)

    def dispose(self):
        self.session = None

    # ── 命令 ────────────────────────────────────────────────────────
    def submit(self, cmd):
        s = self._live()
        if not isinstance(cmd, dict):
            return self._reject(cmd, "E_TYPE", "命令须为对象")
        cid = cmd.get("commandId")
        if not isinstance(cid, str) or not cid:
            return self._reject(cmd, "E_TYPE", "commandId 缺失")
        if cmd.get("sessionId") != s.sid:
            return self._reject(cmd, "E_SESSION",
                                f"sessionId 不符（当前 {s.sid}）")
        if cid in s.command_ids:
            return self._reject(cmd, "E_DUP", "commandId 重复（幂等拒绝）")
        if cmd.get("type") != "buy":
            return self._reject(cmd, "E_TYPE", f"未知命令类型 {cmd.get('type')!r}")
        unit, lane = cmd.get("unit"), cmd.get("lane")
        if not isinstance(unit, str) or unit not in s.buyable:
            return self._reject(cmd, "E_UNIT", f"单位 {unit!r} 不在本关可买栏")
        spec = s.sim.units.get(unit)
        if spec is None or spec.price is None:
            return self._reject(cmd, "E_UNIT", f"单位 {unit!r} 无价格定义")
        if not isinstance(lane, int) or isinstance(lane, bool) \
                or s.sim.world.start(0, lane) is None:
            return self._reject(cmd, "E_LANE", f"泳道 {lane!r} 无效")
        if s.sim.winner is not None:
            return self._reject(cmd, "E_ENDED", "对局已终局（冻结）")
        tick = cmd.get("targetTick")
        if tick is None:
            tick = s.sim.tick + 1          # UI 默认：下一控制相位
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            return self._reject(cmd, "E_TYPE", "targetTick 须为非负整数")
        s.command_ids.add(cid)
        entry = {"commandId": cid, "targetTick": tick, "unit": unit,
                 "lane": lane, "order": s.n_submitted}
        s.n_submitted += 1
        s.pending.append(entry)
        return {"commandId": cid, "queued": True, "targetTick": tick,
                "unit": unit, "lane": lane,
                "execTick": None, "reason": None}

    @staticmethod
    def _reject(cmd, reason, detail):
        return {"commandId": (cmd or {}).get("commandId") if isinstance(cmd, dict)
                else None,
                "queued": False, "targetTick": None, "execTick": None,
                "reason": reason, "detail": detail}

    def advance(self, ticks):
        s = self._live()
        if not isinstance(ticks, int) or isinstance(ticks, bool) \
                or not (1 <= ticks <= MAX_ADVANCE):
            return {"error": "E_BATCH", "detail": f"advance 1..{MAX_ADVANCE}"}
        advanced = 0
        for _ in range(ticks):
            if s.sim.winner is not None:            # 冻结（cli.play 语义）
                break
            if s.sim.native_camera is not None:
                s.sim.step(before_world=s.vm.on_tick)
            else:
                s.sim.step()
            self._drain_events()                    # step 相位事件先入流
            if s.sim.native_camera is None:
                s.vm.on_tick()
            self._drain_events()                    # vm 相位事件（spawn_free）
            self._controller_phase(s)               # 内部保证 sim buy 先于桥 buy_ok
            self._drain_events()
            advanced += 1
        return {"tick": s.sim.tick, "advanced": advanced,
                "winner": s.sim.winner}

    def camera_input(self, payload):
        s = self._live()
        if not isinstance(payload, dict):
            return {'error': 'E_TYPE', 'detail': 'client input must be an object'}
        if payload.get('sessionId') != s.sid:
            return {'error': 'E_SESSION', 'detail': 'client input belongs to another session'}
        try:
            accepted = self.camera_client_input.update(payload.get('positionClient'),
                payload.get('sizeClient'), payload.get('sequence'),
                payload.get('source', 'signed-client-input-v1'))
        except ValueError as error:
            return {'error': 'E_INPUT', 'detail': str(error)}
        if not accepted:
            return {'error': 'E_STALE', 'detail': 'client input sequence did not increase'}
        return {'accepted': True, 'sequence': self.camera_client_input.sequence,
                'tick': s.sim.tick, 'worldSamplePending': s.sim.native_camera is not None
                                                        and s.sim.winner is None}

    def _controller_phase(self, s):
        # 1) 到期命令：targetTick 是可执行门（最早 tick），非排序键；同执行相位
        #    按提交序（order）执行，迟到命令不重排（PBA-06 裁决，合同 §2.5/§4.2）。
        due = [c for c in s.pending if c["targetTick"] <= s.sim.tick]
        due.sort(key=lambda c: c["order"])
        for c in due:
            s.pending.remove(c)
            if s.sim.winner is not None:
                s.command_log.append((c["commandId"], c["targetTick"], None,
                                      False, "E_ENDED"))
                self._emit(s, s.sim.tick, "buy_reject",
                           {"commandId": c["commandId"], "reason": "E_ENDED"})
                continue
            spec = s.sim.units[c["unit"]]
            price = int(spec.price or 0)
            if s.sim.nectar[0] < price:
                s.command_log.append((c["commandId"], c["targetTick"],
                                      s.sim.tick, False, "E_PRICE"))
                self._emit(s, s.sim.tick, "buy_reject",
                           {"commandId": c["commandId"], "reason": "E_PRICE",
                            "unit": c["unit"], "price": price,
                            "nectar": s.sim.nectar[0]})
                continue
            bug = s.sim.buy(0, c["unit"], c["lane"])
            if bug is None:
                # OFR-02B：执行期冷却门禁（E_PRICE/E_UNIT/E_LANE/E_ENDED 已预检，
                # 此处 None 唯一剩因 = 泳道冷却未归零）。拒绝无副作用（不扣费/不生成/不变 ID/RNG）。
                s.command_log.append((c["commandId"], c["targetTick"], s.sim.tick,
                                      False, "E_CD"))
                self._emit(s, s.sim.tick, "buy_reject",
                           {"commandId": c["commandId"], "reason": "E_CD",
                            "unit": c["unit"], "lane": c["lane"]})
                continue
            self._drain_events()            # sim 的 buy 事件先入流，桥 buy_ok 后继
            s.command_log.append((c["commandId"], c["targetTick"], s.sim.tick,
                                  True, None))
            self._emit(s, s.sim.tick, "buy_ok",
                       {"commandId": c["commandId"], "bugId": bug.bug_id,
                        "unit": c["unit"], "lane": c["lane"], "price": price,
                        "nectar": s.sim.nectar[0]})
        # 2) multi 敌方 Bot（b0→b1 顺序与 test_e2e.run_game 一致）
        if s.enemy_bot is not None and s.sim.winner is None:
            s.enemy_bot.on_tick(s.sim)

    # ── 快照/事件 ───────────────────────────────────────────────────
    def snapshot(self):
        s = self._live()
        sim = s.sim
        bugs = [{"id": b.bug_id, "side": b.side, "unit": b.unit_name,
                 "pos": list(b.body_pos(sim)), "mode": b.mode, "hp": b.hp,
                 "direction": list(b.motion.direction) if b.motion is not None else None,
                 "carrying": b.carrying, "dead": b.dead, "trapped": b.trapped,
                 "carryingNectar": self._carrying_nectar(b),
                 "route": {"scope": ('normal-active-physics-f32-20hz-v1' if b.motion is not None
                                      else 'normal-directed-local-f32-20hz-motion-v1' if b.route_enabled
                                      else 'engineering-legacy-route-v1'),
                           "current": b.route_current, "target": b.route_target,
                           "returning": b.route_returning},
                 "attackTick": b.attack_tick,
                 "walkAnimation": b.walk_animation.snapshot() if b.walk_animation is not None else None,
                 "dialogue": self._active_dialogue(b)}
                for b in sorted(sim.bugs, key=lambda x: x.bug_id)]
        return {
            "schemaVersion": web_data.SCHEMA_VERSION,
            "sessionId": s.sid, "tick": sim.tick, "winner": sim.winner,
            "cameraClientInput": self.camera_client_input.snapshot(),
            "nativeCamera": sim.native_camera.snapshot() if sim.native_camera is not None else None,
            "nectar": [sim.nectar[0], sim.nectar[1]],
            "reload": {u: max(0, until - sim.tick)
                       for u, until in sim.reload_until.items()},
            "laneCd": {f"{side}:{lane}": max(0, until - sim.tick)
                       for (side, lane), until in sim.lane_cd_until.items()},
            "hives": [{"side": h.side, "hp": h.hp, "pos": list(h.pos)}
                      for _, h in sorted(sim.hives.items())],
            "starts": [{"name": start.name, "side": start.side_id,
                        "index": start.index, "pos": list(start.grid_pos)}
                       for start in sim.world.starts],
            "bugs": bugs,
            "presentation": {'lightRequest': s.vm.light_request(),
                             'lightState': s.vm.light_state()},
            "nectarEntities": [entity.snapshot() for entity in sim.nectar_entities.values()],
            "nectarLifecycle": {'scope': 'nectar-identity-substeps-v1',
                               'clock': sim.nectar_clock.snapshot(),
                               'birthScope': 'normal-flower-animation-edge-f32-v1',
                               'orderScope': 'engineering-flower-nectar-live-subset-v1',
                               'countScope': 'nectar-classification-members-v1',
                               'memberCount':sim.nectar_member_count(),
                               'scene':sim.nectar_scene_snapshot(),
                               'flowerSeedScope': 'engineering-world-flower-lcg-v1',
                               'flowerRandomState': sim.flower_random.state,
                               'flowerInhibited': sim.flower_inhibited,
                               'flightTargetScope': 'static-waypoints-connectto-name-order-v1',
                               'seedScope': 'deterministic-seed-plus-identity-v1',
                               'carryPositionScope': 'snapshot-cached-source-20hz-v1',
                               'attachmentScope':'cached-world-pose-20hz-v1',
                               'initialPoseScope':'engineering-phase-zero-cache-v1'},
            "flowers": [{"name": f.name, "pos": list(f.pos),
                         "type": f.flower_type, "nectar": f.nectar,
                         "nectarId": f.nectar_id, "cycle": f.cycle.snapshot(),
                         "pose":f.pose_snapshot()}
                        for f in sim.flowers],
            "pathNectar": [{"id": it.item_id, "pos": list(it.pos),
                            "taken": bool(it.taken), "nectarId": it.nectar_id}
                           for it in sim.path_nectar],
        }

    def _carrying_nectar(self, b):
        if b.dead or not b.carrying or b.carry_pickup_tick < 0:
            return None
        kind, index = b.target
        sim = self.session.sim
        return {"scope": "pickup-trajectory-20hz-v1", "tick": b.carry_pickup_tick,
                "nectarId": b.carried_nectar_id,
                "positions": [list(p) for p in b.carry_positions],
                "source": {"kind": kind, "index": index,
                           "name": sim.flowers[index].name if kind == "flower" else None,
                           "positionYup": list(b.carry_source_pos),
                           "positionScope": ('snapshot-cached-flower-position-v1'
                               if kind=='flower' and sim.flowers[index].rig is not None
                               else 'engineering-source-origin-v1' if kind=='flower'
                               else 'snapshot-item-position-v1')}}

    def _active_dialogue(self, b):
        """展示层：仅显示窗口内的对话文本（引擎显示延迟 H6 语义近似）。

        set_dialogue 写 text；显示窗口为elapsed=age/20−delay ∈ [0,duration)。
        audit_state 保留原始字段（对照不受展示推导影响）。
        """
        if not b.dialogue_text or b.dialogue_age < 0:
            return None
        elapsed = b.dialogue_age / self.session.sim.consts.TICK_HZ \
            - b.dialogue_delay
        return b.dialogue_text if 0 <= elapsed < b.dialogue_duration else None

    def audit_state(self):
        """完整对照快照（合同 §5.2；显示四舍五入不入本结构）。"""
        s = self._live()
        sim = s.sim
        st = sim.rng.getstate()
        bugs = []
        for b in sorted(sim.bugs, key=lambda x: x.bug_id):
            bugs.append({
                "id": b.bug_id, "side": b.side, "unit": b.unit_name,
                "speed": b.speed, "canFly": b.can_fly, "canGather": b.can_gather,
                "hp": b.hp, "spawnPos": list(b.spawn_pos), "lane": b.lane,
                "mode": b.mode, "progressSub": b.progress_sub,
                "carrying": b.carrying,
                "carriedNectarId": b.carried_nectar_id,
                "carryPickupTick": b.carry_pickup_tick,
                "carrySourcePos": list(b.carry_source_pos) if b.carry_source_pos is not None else None,
                "carryPositions": [list(p) for p in b.carry_positions],
                "target": list(b.target) if b.target else None,
                "routeLenSub": b.route_len_sub, "curPos": list(b.cur_pos),
                "pathNodes": list(b.path_nodes), "pathI": b.path_i,
                "linkLenSub": b.link_len_sub, "dead": b.dead,
                "routeEnabled": b.route_enabled, "routeCurrent": b.route_current,
                "routeTarget": b.route_target, "routeReturning": b.route_returning,
                "motion": b.motion.snapshot() if b.motion is not None else None,
                "walkAnimation": b.walk_animation.snapshot() if b.walk_animation is not None else None,
                "cooldownTicks": b.cooldown_ticks, "reloadUntil": b.reload_until,
                "trapped": b.trapped, "attackTick": b.attack_tick,
                "attackReadyAt": b.attack_ready_at,
                "dialogueText": b.dialogue_text, "dialogueDelay": b.dialogue_delay,
                "dialogueDuration": b.dialogue_duration, "dialogueWait": b.dialogue_wait,
                "dialogueAge": b.dialogue_age,
                "dialoguePending": b.dialogue_pending,
                "dialogueWaitUntil": b.dialogue_wait_until})
        return {
            "tick": sim.tick, "nectar": [sim.nectar[0], sim.nectar[1]],
            "cameraClientInput": self.camera_client_input.snapshot(),
            "nativeCamera": sim.native_camera.snapshot() if sim.native_camera is not None else None,
            "winner": sim.winner, "nextId": sim._next_id,
            "nextNectarId": sim._next_nectar_id, "nectarSeed": sim._nectar_seed,
            "nectarClock": sim.nectar_clock.snapshot(),
            "nectarScene": sim.nectar_scene_snapshot(),
            "nectarMemberCount":sim.nectar_member_count(),
            "flowerRandomState": sim.flower_random.state,
            "flowerInhibited": sim.flower_inhibited,
            "nectarEntities": [entity.snapshot() for entity in sim.nectar_entities.values()],
            "defenseDeadline": sim.defense_deadline,
            "reloadUntil": {u: until for u, until in sorted(sim.reload_until.items())},
            "laneCdUntil": {f"{side}:{lane}": until
                            for (side, lane), until
                            in sorted(sim.lane_cd_until.items())},
            "rngState": [st[0], list(st[1]), st[2]],
            "hives": [{"side": h.side, "hp": h.hp}
                      for _, h in sorted(sim.hives.items())],
            "starts": [{"name": start.name, "side": start.side_id,
                        "index": start.index, "pos": list(start.grid_pos)}
                       for start in sim.world.starts],
            "flowers": [{"name": f.name, "nectar": f.nectar,
                         "cycle": f.cycle.snapshot(), "nectarId": f.nectar_id,
                         "pose":f.pose_snapshot()} for f in sim.flowers],
            "pathNectar": [{"id": it.item_id, "taken": bool(it.taken),
                            "pos": list(it.pos), "nectarId": it.nectar_id} for it in sim.path_nectar],
            "bugs": bugs,
            "vm": {"cursor": s.vm.cursor, "waitUntil": s.vm.wait_until,
                   "waitNectar": s.vm.wait_nectar,
                   "flows": {str(l): [f["A"], f["B"], f["C"], f["acc1"],
                                      f["acc2"], int(f["rest"])]
                             for l, f in sorted(s.vm.flows.items())},
                   "logLen": len(s.vm.log),
                   "lightRequest": s.vm.light_request()},
            "cmds": {"pending": [dict(c) for c in s.pending],
                     "log": [list(e) for e in s.command_log],
                     "nSubmitted": s.n_submitted},
            "bots": ([{"name": "enemy", "stateRepr": s.enemy_bot.state_repr()}]
                     if s.enemy_bot else []),
            "events": {"nextSeq": s.next_seq, "retained": len(s.events)},
        }

    def read_events(self, after_seq=0):
        s = self._live()
        if not isinstance(after_seq, int) or isinstance(after_seq, bool) \
                or after_seq < 0:
            return {"error": "E_TYPE", "detail": "afterSeq 须为非负整数"}
        out = [e for e in s.events if e["seq"] > after_seq][:EVENT_BATCH]
        gap = False
        if s.events and s.events[0]["seq"] > after_seq + 1:
            gap = True                    # afterSeq 与保留底界间有被丢弃事件
        return {"events": out,
                "nextSeq": (out[-1]["seq"] if out else min(after_seq,
                                                           s.next_seq - 1)),
                "gap": gap, "totalNext": s.next_seq}

    # ── 内部 ────────────────────────────────────────────────────────
    def _live(self):
        if self.session is None:
            raise BridgeError("E_SESSION", "无活动会话（未 init 或已 dispose）")
        return self.session

    def _drain_events(self):
        """sim.events 增量 → 序号化事件流（受控保留）。"""
        s = self.session
        while s.consumed < len(s.sim.events):
            tick, kind, data = s.sim.events[s.consumed]
            s.consumed += 1
            self._emit(s, tick, kind, _jsonable(data))

    def _emit(self, s, tick, kind, data):
        """唯一事件追加位置：分配 seq 并执行保留窗裁窗（data 须已 JSON 安全）。

        sim 原生事件（_drain_events 经 _jsonable）与桥 buy_ok/buy_reject 共用本路径，
        保证所有事件都遵守 eventRetention 裁窗（PBA-04）。
        """
        s.events.append({"seq": s.next_seq, "tick": tick, "type": kind,
                         "data": data})
        s.next_seq += 1
        if len(s.events) > s.retention:
            del s.events[:len(s.events) - s.retention]


class _Session:
    def __init__(self, sid, level_id, sim, vm, enemy_bot, buyable, seed,
                 retention):
        self.sid = sid
        self.level_id = level_id
        self.sim = sim
        self.vm = vm
        self.enemy_bot = enemy_bot
        self.buyable = buyable
        self.seed = seed
        self.retention = retention
        self.pending = []
        self.command_ids = set()
        self.command_log = []
        self.n_submitted = 0
        self.events = []
        self.next_seq = 1
        self.consumed = 0          # sim.events 已序号化游标


class BridgeError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _jsonable(data):
    """sim 事件数据（含 tuple/对象引用）→ JSON 安全结构。"""
    if isinstance(data, tuple):
        return [_jsonable(x) for x in data]
    if isinstance(data, list):
        return [_jsonable(x) for x in data]
    if data is None or isinstance(data, (int, float, str, bool)):
        return data
    return repr(data)


# ── worker 单入口（JS 唯一调用面） ──────────────────────────────────
def bridge_call(bridge, op, payload_json):
    """op(json payload) → json result；不抛异常（错误结构化返回）。"""
    try:
        payload = json.loads(payload_json) if payload_json else {}
        if not isinstance(payload, dict):
            payload = {}
        if op == "init":
            r = bridge.init(payload.get("levelId"), payload.get("seed", 0),
                            payload.get("level"), payload.get("world"),
                            payload.get("units"), payload.get("opts"))
        elif op == "fromObjects":
            r = bridge.from_objects(payload.get("level"), payload.get("world"),
                                    payload.get("units"), payload.get("seed", 0),
                                    payload.get("opts"))
        elif op == "reset":
            r = bridge.reset(payload.get("levelId"), payload.get("seed", 0),
                             payload.get("level"), payload.get("world"),
                             payload.get("units"), payload.get("opts"))
        elif op == "submit":
            r = bridge.submit(payload.get("cmd"))
        elif op == "advance":
            r = bridge.advance(payload.get("ticks"))
        elif op == "camera_input":
            r = bridge.camera_input(payload)
        elif op == "snapshot":
            r = bridge.snapshot()
        elif op == "audit_state":
            r = bridge.audit_state()
        elif op == "read_events":
            r = bridge.read_events(payload.get("afterSeq", 0))
        elif op == "dispose":
            bridge.dispose()
            r = {"disposed": True}
        else:
            r = {"error": "E_TYPE", "detail": f"未知 op {op!r}"}
        return json.dumps({"ok": "error" not in r, "result": r},
                          ensure_ascii=False)
    except BridgeError as e:
        return json.dumps({"ok": False, "error": e.code, "detail": e.detail})
    except Exception as e:                                # noqa: BLE001
        return json.dumps({"ok": False, "error": "E_INTERNAL",
                           "detail": f"{type(e).__name__}: {e}"})
