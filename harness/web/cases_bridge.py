"""H2 bridge 用例实现（W2；loop-web.md §H2 A↔B + 协议，计划 W2-browser-loop.md）。

独立预期来源：sim/scriptvm 源码语义（相位/对话计时/经济）手算推导 +
test_e2e 既有驱动序——不从被测输出反抄。
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cases import BlockedError, CaseResult  # noqa: E402

from bugbits import level as levelmod  # noqa: E402
from bugbits import unitdb, web_bridge, worlddb  # noqa: E402
from bugbits.assets import data_dir  # noqa: E402

WEB_OUT = ROOT / "out" / "web"
LB_PRICE = 3          # buginfos/littlebeetle Price（独立数据锚点）
SEED = 2026


def _load_build(ctx):
    if not (ctx.web_out / "manifest.json").is_file():
        raise BlockedError("无构建产物——先运行 tools/web_build.py --profile slice")
    return {
        "level": json.loads((ctx.web_out / "levels" / "level_02.json")
                            .read_text(encoding="utf-8")),
        "world": json.loads((ctx.web_out / "worlds" / "world_02.json")
                            .read_text(encoding="utf-8")),
        "units": json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8")),
    }


def _fixture(data, nectar=None, scripts=None, type_=None, goal=None):
    d = json.loads(json.dumps(data["level"]))      # 深拷贝
    if nectar is not None:
        d["props"]["InitialNectar"] = [str(nectar)]
    if scripts is not None:
        d["scripts"] = scripts
    if type_ is not None:
        d["props"]["Type"] = [type_]
    if goal is not None:
        d["props"]["GoalNectar"] = [str(goal)]
    out = dict(data)
    out["level"] = d
    return out


def _open(data, seed=SEED, opts=None):
    b = web_bridge.WebBridge()
    info = b.init("level_02", seed, data["level"], data["world"], data["units"],
                  opts=opts or {"buyable": ["ant", "littlebeetle", "bee"]})
    return b, info


def _cmd(info, cid, tick, unit, lane):
    return {"sessionId": info["sessionId"], "commandId": cid,
            "targetTick": tick, "type": "buy", "unit": unit, "lane": lane}


def _events_of(b, kind):
    r = b.read_events(0)
    return [e for e in r["events"] if e["type"] == kind]


def _advance_to(b, tick):
    """分块推进至 tick（advance 单批 ≤5）。"""
    while b.session.sim.tick < tick and b.session.sim.winner is None:
        r = b.advance(min(5, tick - b.session.sim.tick))
        assert not r.get("error"), f"advance 被拒: {r}"


# ── B01 相位合同 ─────────────────────────────────────────────────────
def b01(ctx):
    data = _load_build(ctx)
    b, info = _open(data)
    # 每 tick 恰消费一条（NC-02 STATIC A3）：level_02 脚本第 3 条才是 sendenemy
    # （前 setlight/addhint 各占 1 tick）→ spawn_free 在 tick3。玩家 buy 用
    # targetTick=3 对齐同 tick，验 vm 相位（脚本 spawn_free）先于控制相位（buy_ok）。
    r = b.submit(_cmd(info, "c1", 3, "ant", 0))
    assert r["queued"], f"合法命令被拒: {r}"
    b.advance(3)
    evs = [e for e in b.read_events(0)["events"] if e["tick"] == 3]
    kinds = [e["type"] for e in evs]
    # 脚本 sendenemy（vm 相位）先于玩家 buy（控制相位）→ 同 tick 事件序
    assert "spawn_free" in kinds and "buy_ok" in kinds, f"tick3 事件缺失: {kinds}"
    assert kinds.index("spawn_free") < kinds.index("buy_ok"), \
        f"相位错：控制输入先于 ScriptVM（{kinds}）"
    snap = b.snapshot()
    ids = {x["id"]: x for x in snap["bugs"]}
    assert ids[1]["side"] == 1 and ids[1]["unit"] == "littlebeetle", \
        "敌方脚本虫应先分得 id=1"
    assert ids[2]["side"] == 0 and ids[2]["unit"] == "ant", \
        "玩家买兵在控制相位分得后续 id"
    # tick4 买 littlebeetle（换泳道 1 避开 tick3 ant 的泳道 0 冷却）→ 同 tick 扣款
    b.submit(_cmd(info, "c2", 4, "littlebeetle", 1))
    b.advance(1)
    snap = b.snapshot()
    assert snap["nectar"][0] == 10 - LB_PRICE, \
        f"扣款错: {snap['nectar'][0]} != {10 - LB_PRICE}"
    ok = _events_of(b, "buy_ok")
    assert ok[-1]["tick"] == 4 and ok[-1]["data"]["price"] == LB_PRICE
    return CaseResult("PASS", "tick3: spawn_free→buy_ok 序 + id 分配序 + tick4 扣款")


# ── B02 经济夹具（价格 P=3 独立断言） ────────────────────────────────
def b02(ctx):
    data = _load_build(ctx)
    # 余额 P−1=2：拒绝、无实体、无扣款
    b, info = _open(_fixture(data, nectar=2))
    b.submit(_cmd(info, "p1", 1, "littlebeetle", 0))
    b.advance(2)
    rej = _events_of(b, "buy_reject")
    assert rej and rej[0]["data"]["reason"] == "E_PRICE", f"无 E_PRICE: {rej}"
    assert rej[0]["data"]["price"] == LB_PRICE and rej[0]["data"]["nectar"] == 2
    snap = b.snapshot()
    mine = [x for x in snap["bugs"] if x["side"] == 0]
    assert not mine, f"拒绝后不应有实体: {mine}"
    assert snap["nectar"][0] == 2, "拒绝不得扣款"
    # 余额 P=3：恰成功一次、余 0、实体 +1；重复 commandId 幂等
    b2, info2 = _open(_fixture(data, nectar=3))
    assert b2.submit(_cmd(info2, "d1", 1, "littlebeetle", 0))["queued"]
    dup = b2.submit(_cmd(info2, "d1", 1, "littlebeetle", 0))
    assert dup["queued"] is False and dup["reason"] == "E_DUP", f"非幂等: {dup}"
    b2.advance(2)
    snap = b2.snapshot()
    mine = [x for x in snap["bugs"] if x["side"] == 0]
    assert len(mine) == 1 and snap["nectar"][0] == 0, \
        f"应恰 1 实体余 0: {len(mine)} 只, 蜜 {snap['nectar'][0]}"
    assert len(_events_of(b2, "buy_ok")) == 1, "重复 commandId 重复购买"
    return CaseResult("PASS", "P−1 拒绝无痕；P 恰一次余 0；重复幂等")


# ── B03 对话计时（源码 _dialogue_step 推导） ─────────────────────────
def b03(ctx):
    data = _load_build(ctx)
    key = "D_02_WHY"                     # 有效非 null 文本键（texts.json 有值）
    assert key in json.loads((ctx.web_out / "texts.json").read_text(encoding="utf-8"))
    for n, expect_tick in ((0, 21), (0.25, 26), (2, 61)):
        # 触发 tick = T0 + ceil(20·(1+N))，T0=1（首个 vm.on_tick 执行 sendenemy）
        fx = _fixture(data, scripts=[["sendenemy",
                                      ["littlebeetle", "0", key, str(n)]]])
        b, info = _open(fx)
        _advance_to(b, expect_tick + 5)
        waits = _events_of(b, "dialogue_wait")
        assert waits, f"N={n}: 无 dialogue_wait 事件"
        got = waits[0]["tick"]
        assert got == expect_tick, \
            f"N={n}: dialogue_wait tick {got} != 推导值 {expect_tick}"
        spawns = _events_of(b, "spawn_free")
        assert spawns and spawns[0]["tick"] == 1, "sendenemy 应在 tick1 的 vm 相位"
    # null 负例：不触发等待
    fx = _fixture(data, scripts=[["sendenemy", ["littlebeetle", "0", "null", "5"]]])
    b, info = _open(fx)
    _advance_to(b, 70)
    assert not _events_of(b, "dialogue_wait"), "null 对话不得触发等待"
    return CaseResult("PASS", "N=0/0.25/2 → tick 21/26/61；null 负例无事件")


# ── B04 非法输入与错误码 ─────────────────────────────────────────────
def b04(ctx):
    data = _load_build(ctx)
    b, info = _open(data)
    sid = info["sessionId"]
    checks = [
        ({"sessionId": sid, "commandId": "x1", "targetTick": 1,
          "type": "spawn_free", "unit": "ant", "lane": 0}, "E_TYPE"),
        ({"sessionId": sid, "commandId": "x2", "targetTick": 1,
          "type": "buy", "unit": "wasp", "lane": 0}, "E_UNIT"),      # 不在可买栏
        ({"sessionId": sid, "commandId": "x3", "targetTick": 1,
          "type": "buy", "unit": "nope", "lane": 0}, "E_UNIT"),
        ({"sessionId": sid, "commandId": "x4", "targetTick": 1,
          "type": "buy", "unit": "ant", "lane": 99}, "E_LANE"),
        ({"sessionId": "s0", "commandId": "x5", "targetTick": 1,
          "type": "buy", "unit": "ant", "lane": 0}, "E_SESSION"),
        ({"sessionId": sid, "commandId": "x6", "targetTick": -1,
          "type": "buy", "unit": "ant", "lane": 0}, "E_TYPE"),
    ]
    for cmd, want in checks:
        r = b.submit(cmd)
        assert r["queued"] is False and r["reason"] == want, \
            f"{cmd['commandId']}: 期望 {want} 得 {r['reason']}"
    for bad in (0, 6, -1):
        r = b.advance(bad)
        assert r.get("error") == "E_BATCH", f"advance({bad}) 未拒: {r}"
    # 终局冻结：GoalNectar=0 的 gather 关第 1 tick 即胜
    b2, info2 = _open(_fixture(data, type_="gather", goal=0, nectar=0))
    r = b2.advance(5)
    assert r["advanced"] == 1 and r["winner"] == 0, f"即时终局异常: {r}"
    r2 = b2.advance(5)
    assert r2["advanced"] == 0, f"冻结后仍推进: {r2}"
    r3 = b2.submit(_cmd(info2, "z1", 2, "ant", 0))
    assert r3["reason"] == "E_ENDED", f"终局后命令未拒: {r3}"
    # dispose 后一切操作 E_SESSION
    b2.dispose()
    try:
        b2.snapshot()
        raised = "none"
    except web_bridge.BridgeError as e:
        raised = e.code
    assert raised == "E_SESSION", f"dispose 后应 E_SESSION: {raised}"
    return CaseResult("PASS", "E_TYPE/E_UNIT/E_LANE/E_SESSION/E_BATCH/"
                      "E_ENDED/E_SESSION(dispose) 全命中")


# ── B05 A↔B 对照（数据导出不改模拟语义） ────────────────────────────
def _drive(b, info, plan, checkpoints):
    """plan: [(tick, unit, lane)]; checkpoints: 采样 tick 集。返回 {tick: audit}。"""
    audits = {}
    by_tick = {}
    for i, (tick, unit, lane) in enumerate(plan):
        r = b.submit(_cmd(info, f"c{i}", tick, unit, lane))
        assert r["queued"] or r["reason"] in ("E_UNIT", "E_PRICE"), \
            f"计划命令意外被拒: {r}"
    batches = [1, 2, 3, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
               5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
    for n in batches:
        r = b.advance(n)
        if r.get("error"):
            break
        if r["tick"] in checkpoints:
            audits[r["tick"]] = b.audit_state()
        if r["winner"] is not None:
            break
    while b.session.sim.tick < max(checkpoints) and b.session.sim.winner is None:
        b.advance(5)
        if b.session.sim.tick in checkpoints:
            audits[b.session.sim.tick] = b.audit_state()
    return audits


def b05(ctx):
    data = _load_build(ctx)
    lv = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
    w = worlddb.parse_world(data_dir("worlds", lv.world_name + ".vsc"))
    units = {u: unitdb.load_unit(u) for u in ("ant", "littlebeetle", "bee")}
    plan = [(1, "ant", 0), (1, "littlebeetle", 0), (3, "bee", 1),
            (5, "littlebeetle", 2), (6, "ant", 1), (8, "bee", 0),
            (10, "littlebeetle", 0), (15, "ant", 2), (20, "bee", 2),
            (30, "littlebeetle", 1), (40, "ant", 0), (50, "bee", 1)]
    checkpoints = {1, 3, 10, 30, 60, 120}
    opts = {"buyable": ["ant", "littlebeetle", "bee"]}
    ba = web_bridge.WebBridge()
    ia = ba.from_objects(lv, w, units, SEED, opts)
    audits_a = _drive(ba, ia, plan, checkpoints)
    bb, ib = _open(data, opts=opts)
    audits_b = _drive(bb, ib, plan, checkpoints)
    assert set(audits_a) == set(audits_b) and audits_a, \
        f"采样集不一致: {sorted(audits_a)} vs {sorted(audits_b)}"
    for tick in sorted(audits_a):
        if audits_a[tick] != audits_b[tick]:
            _first_diff(audits_a[tick], audits_b[tick], f"A↔B@t{tick}")
            raise AssertionError(f"A↔B 分歧 @tick {tick}")
    ev_a = ba.read_events(0)["events"]
    ev_b = bb.read_events(0)["events"]
    assert ev_a == ev_b, f"事件流分歧: {len(ev_a)} vs {len(ev_b)} 条"
    return CaseResult("PASS",
                      f"A(原解析)↔B(恢复) {len(checkpoints)} 采样点逐字段全等"
                      f"（含 RNG/VM/命令日志）+ 事件流全等")


def _first_diff(a, b, path="$"):
    """首个分歧定位（tick/字段路径/两值）。"""
    if type(a) is not type(b) and not (isinstance(a, (int, float))
                                       and isinstance(b, (int, float))):
        print(f"  分歧 {path}: {a!r} vs {b!r}")
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b or a[k] != b[k]:
                _first_diff(a.get(k), b.get(k), f"{path}.{k}")
                return
    elif isinstance(a, list):
        if len(a) != len(b):
            print(f"  分歧 {path}: len {len(a)} vs {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                _first_diff(x, y, f"{path}[{i}]")
                return
    elif a != b:
        print(f"  分歧 {path}: {a!r} vs {b!r}")


# ── B06 批次不变性 ───────────────────────────────────────────────────
def b06(ctx):
    data = _load_build(ctx)
    plan = [(1, "ant", 0), (2, "littlebeetle", 0), (4, "bee", 0),
            (7, "littlebeetle", 1), (11, "ant", 1), (13, "bee", 2)]
    audits = []
    for pattern in ([1] * 60, [5] * 12, [3, 1, 5, 2, 5, 1, 4] + [5] * 8):
        b, info = _open(data)
        for i, (tick, unit, lane) in enumerate(plan):
            b.submit(_cmd(info, f"c{i}", tick, unit, lane))
        # 批次尺寸按 pattern 取，但一律驱动到 tick=60（模式和不必恰好 60）
        it = iter(pattern)
        while b.session.sim.tick < 60 and b.session.sim.winner is None:
            n = next(it, 5)
            b.advance(min(n, 60 - b.session.sim.tick))
        audits.append(b.audit_state())
    assert audits[0] == audits[1] == audits[2], \
        "推进批次划分影响最终状态/RNG 消耗"
    rngs = [a["rngState"] for a in audits]
    assert rngs[0] == rngs[1] == rngs[2], "RNG 消费随批次划分漂移"
    return CaseResult("PASS", "1×60 / 5×12 / 混合批次 → 同状态同 RNG")


# ── B07 reset 隔离 ───────────────────────────────────────────────────
def b07(ctx):
    data = _load_build(ctx)
    b, info = _open(data)
    r = b.submit(_cmd(info, "r1", 1, "littlebeetle", 0))
    assert r["queued"], f"命令被拒: {r}"
    # 合法分块推进至 tick 3（_advance_to 逐块检查回执）；PBA-05：不得用会被拒的
    # advance(40) 跳过执行，reset 前必须证明购买确已执行、tick 已推进、旧局状态非默认。
    _advance_to(b, 3)
    snap = b.snapshot()
    assert snap["tick"] == 3, f"未推进到目标 tick: {snap['tick']}"
    mine = [x for x in snap["bugs"] if x["side"] == 0]
    assert any(x["unit"] == "littlebeetle" for x in mine), \
        f"购买未生成实体: {mine}"
    assert snap["nectar"][0] == 10 - LB_PRICE, \
        f"购买未扣款: {snap['nectar'][0]} != {10 - LB_PRICE}"
    assert _events_of(b, "buy_ok"), "无 buy_ok 事件"
    assert b.audit_state()["laneCdUntil"], "旧局应已 arm 冷却（非默认状态）"
    old_sid = info["sessionId"]
    info2 = b.reset("level_02", SEED, data["level"], data["world"],
                    data["units"], opts={"buyable": ["ant", "littlebeetle",
                                                     "bee"]})
    assert info2["sessionId"] != old_sid, "reset 未换 sessionId"
    # reset 后 tick=0；推进 1 tick 应与全新 init+1 tick 状态全等（同种子）
    b.advance(1)
    b2, _ = _open(data)
    b2.advance(1)
    assert b.audit_state() == b2.audit_state(), "reset 状态泄漏（不等于全新局）"
    # 旧 session 命令拒绝；事件流从 seq=1 重新开始且无旧局事件
    r = b.submit({"sessionId": old_sid, "commandId": "r2", "targetTick": 2,
                  "type": "buy", "unit": "ant", "lane": 0})
    assert r["reason"] == "E_SESSION", f"旧 session 未拒: {r}"
    # 每 tick 恰消费一条（NC-02）：脚本 sendenemy 在 tick3 → 首个事件 spawn_free
    # 落在 tick3 且 seq=1（tick1 仅 setlight、tick2 仅 addhint，均无 sim 事件）。
    _advance_to(b, 3)
    evs = b.read_events(0)["events"]
    assert evs and evs[0]["seq"] == 1, "事件序号未随 reset 重置"
    assert not any(e["type"] == "buy_ok" for e in evs), "旧局事件泄漏进新局"
    return CaseResult("PASS",
                      "合法推进至购买执行（实体+扣款+冷却+buy_ok）→ reset 全等"
                      "全新同种子局；旧 sid E_SESSION；事件重置")


# ── B08 事件游标与保留 ───────────────────────────────────────────────
def b08(ctx):
    data = _load_build(ctx)
    b, info = _open(data, opts={"buyable": ["ant", "littlebeetle", "bee"],
                                "eventRetention": 30})
    b.submit(_cmd(info, "e1", 1, "littlebeetle", 0))
    b.submit(_cmd(info, "e2", 2, "ant", 1))         # 采集蚁（换泳道 1 避开冷却）→ 存款事件流
    total = 0
    for _ in range(600):                    # 最多 3000 tick 攒事件量
        r = b.advance(5)
        total = b.read_events(0)["totalNext"] - 1
        if total > 60 or r["winner"] is not None:
            break
    assert total > 60, f"事件量不足以测保留（{total}）——放宽推进数"
    r = b.read_events(0)
    assert r["gap"] is True, "保留窗溢出后 afterSeq=0 应报 gap"
    assert len(r["events"]) <= 30, f"保留窗失效: {len(r['events'])}"
    assert r["events"][0]["seq"] > 1, "保留窗应丢弃最旧"
    # 从保留底界起增量读：连续、无重复、无 gap
    cursor = r["events"][0]["seq"] - 1
    seen = []
    while True:
        r = b.read_events(cursor)
        assert r["gap"] is False, "保留窗内增量读不应 gap"
        if not r["events"]:
            break
        seqs = [e["seq"] for e in r["events"]]
        assert seqs == list(range(cursor + 1, cursor + 1 + len(seqs))), \
            "seq 必须连续"
        seen += seqs
        cursor = r["nextSeq"]
        if len(seen) > 200:
            break
    assert seen == sorted(set(seen)), "重复事件"
    return CaseResult("PASS",
                      f"保留窗 30 溢出 gap+截断；底界起游标连续无重复"
                      f"（{len(seen)} 条）")


# ── U01 multi 对抗（FIX-03 §5.1）────────────────────────────────────
# 版本化显式演示配置（与 web_build.MULTI_DEMO_* 一致；multi/multir 无 BugSetup，
# 原虫栏选择机制未建模 H28）。独立预期=test_e2e 双 bot 同构对局（wasp 同款参数）。
MULTI_DEMO_BUYABLE = ["ant", "wasp", "bee"]
MULTI_DEMO_ENEMY = {"gather_ants": 10, "attack_unit": "wasp",
                    "attack_lanes": [0], "garrison": 12, "attack_every": 10}


def _all_events(b):
    """分页读完事件流（read_events 单批 EVENT_BATCH=1000, 须游标前进）。"""
    out, cursor = [], 0
    while True:
        r = b.read_events(cursor)
        out += r["events"]
        if not r["events"]:
            break
        cursor = r["nextSeq"]
        if len(out) > 50000:
            break
    return out


def u01(ctx):
    lv = levelmod.parse_level(data_dir("scripts", "levels", "multi_01.vsc"))
    w = worlddb.parse_world(data_dir("worlds", lv.world_name + ".vsc"))
    units = unitdb.load_all()
    b = web_bridge.WebBridge()
    info = b.from_objects(lv, w, units, seed=SEED,
                          opts={"buyable": MULTI_DEMO_BUYABLE,
                                "enemyBot": MULTI_DEMO_ENEMY})
    assert b.session.enemy_bot is not None, "multi 无敌方 Bot"
    deadline = b.session.sim.defense_deadline or 999999
    # 驱动：玩家买 ant(采集)+wasp(进攻)，敌方 Bot 同构自动（bridge 相位）。
    # OFR-02B：泳道冷却下跨可用泳道分散买（与 bot 同款），避免单泳道瞬间铺满被门禁。
    lanes = sorted({s.index for s in b.session.sim.world.starts
                    if s.side_id == 0})
    li = 0
    cid = 0
    while b.session.sim.winner is None and b.session.sim.tick < deadline:
        snap = b.snapshot()
        ants = sum(1 for x in snap["bugs"]
                   if x["side"] == 0 and x["unit"] == "ant" and not x["dead"])
        cid += 1
        if ants < 10:
            unit = "ant"
        elif snap["nectar"][0] >= 4:        # wasp 价格 4
            unit = "wasp"
        else:
            unit = None
        if unit is not None:
            lane = lanes[li % len(lanes)]
            li += 1
            b.submit({"sessionId": info["sessionId"], "commandId": f"c{cid}",
                      "targetTick": None, "type": "buy", "unit": unit,
                      "lane": lane})
        b.advance(5)
    evs = _all_events(b)
    kinds = [e["type"] for e in evs]
    buy_side1_att = any(e["type"] == "buy" and e["data"][0] == 1
                        and e["data"][1] == "wasp" for e in evs)
    buy_side0_att = any(e["type"] == "buy" and e["data"][0] == 0
                        and e["data"][1] == "wasp" for e in evs)
    dep1 = any(e["type"] == "deposit" and e["data"][0] == 1 for e in evs)
    assert buy_side1_att, "敌方未生产进攻单位"
    assert buy_side0_att, "玩家未生产进攻单位"
    assert dep1, "敌方未采集入账"
    assert any(e["type"] in ("damage", "hive_damage") for e in evs), \
        "双方未发生交战/伤害"
    assert b.session.sim.winner is not None, \
        f"未终局（t={b.session.sim.tick}）"
    assert any(e["type"] == "hive_destroyed" for e in evs), \
        "未通过拆巢取胜（可能空转超时）"
    return CaseResult(
        "PASS",
        f"双方生产进攻单位；交战/伤害 + 拆巢取胜 @t{b.session.sim.tick}"
        f"（damage={kinds.count('damage')}, hive_damage={kinds.count('hive_damage')}）")


