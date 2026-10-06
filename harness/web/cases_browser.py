"""H3/H2-C 浏览器用例实现（W2 最小准入；后续 W3–W5 扩充）。

C01：真实 Chromium 加载页面 → Pyodide Worker → init → UI 按钮买兵 →
     同命令日志 CPython 复放 → 逐 tick audit 全等（B↔C）。
C02：缺 py-bundle 的坏包 → 显式错误，非永久 loading（H4 初始化部分）。
"""
import json
import shutil
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cases import BlockedError, CaseResult  # noqa: E402

from bugbits import web_bridge  # noqa: E402

WEB_OUT = ROOT / "out" / "web"
SEED = 2026
PARITY_TICKS = (1, 5, 20, 60)


_STAGE_MEASURE = """() => {
  const rect = el => { const r=el.getBoundingClientRect();
    return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}; };
  const stage=document.getElementById('worldstage'), c=document.getElementById('scene');
  const style=getComputedStyle(stage), ci=window.__bb_test.cameraInfo();
  return {stage:rect(stage),canvas:rect(c),aspect:ci.activePresetKey?ci.projection.aspect:1,
    backing:[c.width,c.height],dpr:devicePixelRatio,camera:ci,
    stageStyle:{border:style.borderWidth,padding:style.padding,overflow:style.overflow},
    renderState:window.__bb_test.renderState(),generation:window.__bb_test.generation()};
}"""


def _save_backing_png(page, path):
    """Full square backing, without CSS crop, scrolling or DOM HUD pixels."""
    import base64
    data = page.evaluate("document.getElementById('scene').toDataURL('image/png')")
    path.write_bytes(base64.b64decode(data.split(',', 1)[1]))


def _stage_geometry_assert(m, aspect):
    """Independent 640/aspect formula; never use host's geometry as expected."""
    import math
    assert math.isfinite(aspect) and aspect >= 1
    s, c = m['stage'], m['canvas']
    scale = s['w'] / 640
    oy = (640 - 640 / aspect) / 2
    assert abs(s['h'] - s['w'] / aspect) <= .55, (s, aspect)
    assert abs(c['w'] - s['w']) <= .55 and abs(c['h'] - c['w']) <= .55, (s, c)
    assert abs(c['l'] - s['l']) <= .55 and abs(c['t'] - (s['t'] - oy*scale)) <= .55, (s, c, oy)
    assert m['backing'] == [640*min(m['dpr'], 2)] * 2, m['backing']
    assert m['stageStyle']['border'] == '0px' and m['stageStyle']['padding'] == '0px', m['stageStyle']
    assert m['stageStyle']['overflow'] == 'hidden', m['stageStyle']
    assert m['renderState']['presetKey'] == m['camera']['activePresetKey'], m
    assert m['renderState']['generation'] == m['generation'], 'stage/frame generation mismatch'
    return oy, scale


def _need_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError as e:
        raise BlockedError(f"playwright 未安装: {e}") from e


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):        # noqa: N802 - 静默日志
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True   # 页面关闭中止下载属正常


def _serve(directory):
    """临时 HTTP 服务（端口随机）→ (base_url, server)；用后 shutdown。"""
    import functools
    handler = functools.partial(_QuietHandler, directory=str(directory))
    # ThreadingHTTPServer：Chromium 推测性预连接会以空连接阻塞单线程
    # HTTPServer 的 readline（偶发饿死资产请求 → 随机用例 60s 超时）
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return f"http://127.0.0.1:{srv.server_port}/", srv


def _cpython_expected(cmd, web_out):
    """CPython B 层复放同一命令 → {tick: audit}（独立于浏览器）。"""
    data = {
        "level": json.loads((web_out / "levels" / "level_02.json")
                            .read_text(encoding="utf-8")),
        "world": json.loads((web_out / "worlds" / "world_02.json")
                            .read_text(encoding="utf-8")),
        "units": json.loads((web_out / "units.json").read_text(encoding="utf-8")),
    }
    mf = json.loads((web_out / "manifest.json").read_text(encoding="utf-8"))
    lv02 = next(lv for lv in mf["levels"] if lv["id"] == "level_02")
    b = web_bridge.WebBridge()
    info = b.init("level_02", SEED, data["level"], data["world"], data["units"],
                  opts={"buyable": lv02["buyable"]})
    if cmd is not None:
        c = dict(cmd)
        c["sessionId"] = info["sessionId"]
        r = b.submit(c)
        assert r["queued"], f"CPython 复放命令被拒: {r}"
    audits = {}
    for tick in PARITY_TICKS:
        while b.session.sim.tick < tick and b.session.sim.winner is None:
            b.advance(min(5, tick - b.session.sim.tick))
        audits[b.session.sim.tick] = b.audit_state()
    return audits, b


def _cpython_cd_trace(web_out):
    """CPython B 层复放冷却购买序列 → 权威迹（独立于浏览器）。

    与 n04 浏览器序列逐 tick 同构：首购 buy_ok → 同泳道二购 E_CD → 跨泳道
    buy_ok → 冷却归零后同泳道再购 buy_ok → **期限边界（前=E_CD/当=ok/后=ok）**。
    另返回：dup（同 commandId 二次提交 → E_DUP 幂等拒绝，桥层语义——Worker 内
    跑同一 bridge 代码）；fresh_audit（全新 init 的 tick0 审计，供浏览器 reset
    后对照）。script_gate 见 _cpython_script_gate。
    """
    data = {
        "level": json.loads((web_out / "levels" / "level_02.json")
                            .read_text(encoding="utf-8")),
        "world": json.loads((web_out / "worlds" / "world_02.json")
                            .read_text(encoding="utf-8")),
        "units": json.loads((web_out / "units.json").read_text(encoding="utf-8")),
    }
    mf = json.loads((web_out / "manifest.json").read_text(encoding="utf-8"))
    lv02 = next(lv for lv in mf["levels"] if lv["id"] == "level_02")
    b = web_bridge.WebBridge()
    info = b.init("level_02", SEED, data["level"], data["world"], data["units"],
                  opts={"buyable": lv02["buyable"]})
    sid = info["sessionId"]
    n = 0

    def submit(unit, lane, cid=None):
        nonlocal n
        n += 1
        r = b.submit({"sessionId": sid, "commandId": cid or f"n04-{n}",
                      "targetTick": None, "type": "buy",
                      "unit": unit, "lane": lane})
        assert r["queued"], f"CPython 复放被拒: {r}"

    def adv_to(t):
        while b.session.sim.tick < t and b.session.sim.winner is None:
            b.advance(min(5, t - b.session.sim.tick))

    adv_to(1)
    submit("littlebeetle", 0)
    adv_to(2)                       # buy_ok lane0（arm 冷却 until 202）
    submit("littlebeetle", 0)
    submit("littlebeetle", 1)
    adv_to(3)                       # lane0 E_CD；lane1 buy_ok
    adv_to(202)                     # lane0 冷却归零
    submit("littlebeetle", 0)
    adv_to(203)                     # lane0 buy_ok（until 403）
    # 期限边界（ant 价 0 → 无花蜜约束）：前=E_CD / 当=ok / 后=ok
    adv_to(401)
    submit("ant", 0)                # target 402 → E_CD（402 < 403 期限前）
    adv_to(402)
    submit("ant", 0)                # target 403 → ok（期限当，403 not<403）→ until 603
    adv_to(603)
    submit("ant", 0)                # target 604 → ok（期限后）→ until 804
    adv_to(604)
    evs = b.read_events(after_seq=0)["events"]
    buys = [(e["type"], e["data"].get("reason"), e["data"].get("lane"), e["tick"])
            for e in evs if e["type"] in ("buy_ok", "buy_reject")]
    audit = b.audit_state()
    # 幂等（桥层）：同 commandId 二次提交 → E_DUP（不下队、不重复执行）
    b.submit({"sessionId": sid, "commandId": "n04-dup",
              "targetTick": None, "type": "buy",
              "unit": "ant", "lane": 0})
    dup = b.submit({"sessionId": sid, "commandId": "n04-dup",
                    "targetTick": None, "type": "buy",
                    "unit": "ant", "lane": 0})
    # 全新 init 的 tick0 审计（浏览器 resetGame 对照面；字段范围见 n04 断言）
    b2 = web_bridge.WebBridge()
    b2.init("level_02", SEED, data["level"], data["world"], data["units"],
            opts={"buyable": lv02["buyable"]})
    fresh = b2.audit_state()
    return {"buys": buys, "laneCdUntil": audit["laneCdUntil"],
            "tick": audit["tick"], "dup": dup,
            "fresh_audit": {k: fresh[k] for k in
                            ("tick", "nectar", "nextId", "winner",
                             "laneCdUntil", "bugs", "vm")}}


def _cpython_script_gate(web_out):
    """CPython 复放脚本出生门禁夹具（PBA-12）——与 n04 浏览器夹具同构。

    夹具：level_02 第一条 sendenemy 后插入同泳道（lane 2）第二条 → 同 tick 执行。
    期望：第二条被 +0x22c 门禁拒绝——无实体、不刷新冷却（until 仍 203）、
    spawn_free 事件仅 1 条。（NC-02 每 tick 恰一条：send#1 在 tick3、send#2 在 tick4，
    故 advance 到 tick4。）
    """
    data = {
        "level": json.loads((web_out / "levels" / "level_02.json")
                            .read_text(encoding="utf-8")),
        "world": json.loads((web_out / "worlds" / "world_02.json")
                            .read_text(encoding="utf-8")),
        "units": json.loads((web_out / "units.json").read_text(encoding="utf-8")),
    }
    _patch_scripts_insert_sendenemy(data["level"])
    mf = json.loads((web_out / "manifest.json").read_text(encoding="utf-8"))
    lv02 = next(lv for lv in mf["levels"] if lv["id"] == "level_02")
    b = web_bridge.WebBridge()
    b.init("level_02", SEED, data["level"], data["world"], data["units"],
           opts={"buyable": lv02["buyable"]})
    while b.session.sim.tick < 4 and b.session.sim.winner is None:
        b.advance(min(5, 4 - b.session.sim.tick))
    evs = b.read_events(after_seq=0)["events"]
    spawns = [e for e in evs if e["type"] == "spawn_free"]
    audit = b.audit_state()
    return {"spawn_free_n": len(spawns),
            "lane12_cd": audit["laneCdUntil"].get("1:2"),
            "enemy_lb": sum(1 for x in audit["bugs"]
                            if x["side"] == 1 and x["unit"] == "littlebeetle")}


def _patch_scripts_insert_sendenemy(level_dict):
    """夹具：第一条 sendenemy 后插入同单位同泳道第二条（同 tick 执行）。"""
    scripts = level_dict["scripts"]
    idx = next(i for i, (sub, _a) in enumerate(scripts) if sub == "sendenemy")
    sub, args = scripts[idx]
    scripts.insert(idx + 1, [sub, [args[0], args[1], args[2], "0"]])


def _first_diff(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return _first_diff(a.get(k), b.get(k), f"{path}.{k}")
        return f"{path} (equal)"
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_diff(x, y, f"{path}[{i}]")
        return f"{path} (equal)"
    return f"{path}: {a!r} vs {b!r}"


def _sprite_probe_pixel(sprite_key, web_out, scale=1.0):
    """图集源精灵中心附近找一个 3×3 全不透明块 → 该处 5×5 色域 + 画布偏移。

    期望=5×5 窗口每通道 [min,max]（±8 容差吸收 drawImage 双线性缩放混合）；
    偏移按 host.js 精灵绘制缩放 k=CANVAS(640)/1024 × ScaleFactor 换算。
    """
    from PIL import Image
    atlas = json.loads((web_out / "atlas.json").read_text(encoding="utf-8"))
    s = atlas["sprites"][sprite_key]
    page = Image.open(web_out / atlas["pages"][s["page"]]["file"]).convert("RGBA")
    k = 640 / 1024 * scale            # host drawSprite 的绘制缩放（含 ScaleFactor）
    cx, cy = s["w"] // 2, s["h"] // 2
    for r in range(0, 40):
        for dx in range(-r, r + 1):
            for dy in (r, -r) if r else (0,):
                x, y = cx + dx, cy + dy
                core = [(x + i, y + j) for i in (-1, 0, 1) for j in (-1, 0, 1)]
                if not all(0 <= px < s["w"] and 0 <= py < s["h"]
                           and page.getpixel((s["x"] + px, s["y"] + py))[3] == 255
                           for px, py in core):
                    continue
                win = [(x + i, y + j) for i in (-2, -1, 0, 1, 2)
                       for j in (-2, -1, 0, 1, 2)
                       if 0 <= x + i < s["w"] and 0 <= y + j < s["h"]
                       and page.getpixel((s["x"] + x + i, s["y"] + y + j))[3] == 255]
                chans = list(zip(*(page.getpixel((s["x"] + wx, s["y"] + wy))[:3]
                                   for wx, wy in win)))
                return {"rgb": [min(c) for c in chans] + [max(c) for c in chans],
                        "dx": round((x - cx) * k), "dy": round((y - cy) * k)}
    raise AssertionError(f"精灵 {sprite_key} 中心 40px 内无 3×3 不透明块")


def _unit_scale(unit, web_out):
    """单位 ScaleFactor（draw 层缩放，与 host.js unitScale 同口径；缺省 1.0）。"""
    if not unit:
        return 1.0
    units = json.loads((web_out / "units.json").read_text(encoding="utf-8"))
    raw = ((units.get(unit) or {}).get("props") or {}).get("ScaleFactor")
    v = float(raw[0]) if raw else 0.0
    return v if v > 0 else 1.0


def _unit_billboard(web_out, unit, pos, world, canvas_px=640):
    """host.js unitBillboard 的 Python 权威复刻（NC-03 世界尺寸合同）。

    调 render/billboard.py（同一实现也供 scene.py 离线合成），读包内
    units.json（worldSize/atlasScale）与 manifest projection。返回
    (px, py, cam_z, lam)——与页面 render.draws 的 px/py/scale/camZ 对应。
    """
    from bugbits.render import billboard
    units = json.loads((web_out / "units.json").read_text(encoding="utf-8"))
    spec = units.get(unit) or {}
    ws = spec.get("worldSize") or {"w": 12, "h": 7, "d": 12}
    asc = spec.get("atlasScale") or (max(ws["w"], ws["h"], ws["d"]) / (0.8 * 128))
    mf = json.loads((web_out / "manifest.json").read_text(encoding="utf-8"))
    proj = mf["projection"][world]
    bb = billboard.unit_billboard(proj, pos, (ws["w"], ws["h"], ws["d"]),
                                  _unit_scale(unit, web_out), asc, canvas_px)
    return (bb["px"], bb["py"], bb["cam_z"], bb["lam"])


# ── C01 浏览器最小闭环 + B↔C 对照 ───────────────────────────────────
def c01(ctx):
    sync_playwright = _need_playwright()
    if not (ctx.web_out / "py-bundle.json").is_file():
        raise BlockedError("out/web 无 py-bundle.json——需含 vendor 的重建")
    url, srv = _serve(ctx.web_out)
    errors = []                       # pageerror/console.error 收集
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 900, "height": 600})
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            # 受控买兵：真实 UI 按钮（非测试 hook 路径）
            page.click("#buy-littlebeetle")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.receipt() !== null",
                timeout=10000)
            receipt = page.evaluate("window.__bb_test.receipt()")
            assert receipt["queued"] is True, f"UI 买兵被拒: {receipt}"
            assert receipt["unit"] == "littlebeetle"
            cmd = {"commandId": receipt["commandId"],
                   "targetTick": receipt["targetTick"], "type": "buy",
                   "unit": receipt["unit"], "lane": receipt["lane"]}
            # 浏览器推进到各采样 tick 取 audit
            audits_c = {}
            for tick in PARITY_TICKS:
                page.evaluate(f"window.__bb_test.advanceTo({tick})")
                audits_c[tick] = page.evaluate("window.__bb_test.audit()")
            shot = ctx.run_dir / "c01-page.png"
            page.screenshot(path=str(shot))
            events_c = page.evaluate("window.__bb_test.events()")
            browser.close()
    finally:
        srv.shutdown()

    assert not errors, f"页面/控制台错误: {errors[:5]}"
    # CPython 复放同一命令日志
    audits_b, _ = _cpython_expected(cmd, ctx.web_out)
    for tick in PARITY_TICKS:
        if audits_b.get(tick) != audits_c.get(tick):
            diff = _first_diff(audits_b.get(tick), audits_c.get(tick),
                               f"B↔C@t{tick}")
            raise AssertionError(f"B↔C 分歧 @tick {tick}: {diff}")
    # 受控买兵/出兵事实：脚本出兵（敌方）+ UI 买兵（我方）
    kinds = [e["type"] for e in events_c["events"]]
    assert "spawn_free" in kinds, "浏览器未见脚本出兵"
    assert "buy_ok" in kinds, "浏览器未见 UI 买兵成功"
    nectar0 = audits_c[PARITY_TICKS[0]]["nectar"]
    assert nectar0[0] == 10 - 3, f"扣款不符: {nectar0}"
    return CaseResult("PASS",
                      f"Chromium 实启：UI 买兵+脚本出兵；B↔C "
                      f"{len(PARITY_TICKS)} 采样点 audit 全等；无页面错误")


# ── C03 地图/实体绘制（W3） ──────────────────────────────────────────
def c03(ctx):
    sync_playwright = _need_playwright()
    if not (ctx.web_out / "atlas.json").is_file():
        raise BlockedError("out/web 无 atlas.json")
    url, srv = _serve(ctx.web_out)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 720})
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            _set_camera_and_wait(page, None, ctx, errors, "c03-explicit-overview")
            page.click("#buy-littlebeetle")          # 我方单位在场
            page.evaluate("window.__bb_test.advanceTo(60)")
            page.wait_for_timeout(300)               # 等待 rAF 至少一帧
            snap = page.evaluate("window.__bb_test.snapshot()")
            draws = page.evaluate("window.__bb_test.drawLog()")
            fb_hits = page.evaluate("window.__bb_test.fallbackHits()")
            # 断言 1：快照中可见存活实体均有 draw 或明确裁剪原因
            drawn = {d["id"] for d in draws if not d.get("culled")}
            culled = {d["id"]: d["culled"] for d in draws if d.get("culled")}
            alive = [b for b in snap["bugs"] if not b["dead"]]
            assert alive, "tick60 无存活实体（前提失败）"
            for b in alive:
                assert b["id"] in drawn or b["id"] in culled, \
                    f"存活虫 {b['id']} 既无 draw 也无裁剪记录"
                assert b["id"] not in culled or culled[b["id"]] in \
                    ("offscreen", "no-clip", "no-sprite"), \
                    f"虫 {b['id']} 非法裁剪原因: {culled[b['id']]}"
            drew_bugs = [d for d in draws
                         if d.get("clip") in ("walk", "idle", "normal_attack")]
            assert drew_bugs, "无虫精灵绘制"
            assert any(d["id"].startswith("flower:") for d in draws), "花未绘制"
            assert any(d["id"].startswith("hive:") for d in draws), "巢未绘制"
            assert any(d["id"].startswith("nectar:") for d in draws), \
                "路径蜜未绘制"
            # 断言 2：canvas 像素数值代理（非空 + 多样 + 地形/精灵并存）
            px_stats = page.evaluate("""() => {
              const c = document.getElementById('scene');
              const d = c.getContext('2d').getImageData(0, 0, 640, 640).data;
              const colors = new Set();
              let nonBlank = 0, bright = 0;
              for (let i = 0; i < d.length; i += 16) {
                const r = d[i], g = d[i+1], b = d[i+2];
                colors.add((r<<16)|(g<<8)|b);
                if (r+g+b > 30) nonBlank++;
                if (r+g+b > 180) bright++;
              }
              return {colors: colors.size, nonBlank, bright, samples: d.length/16};
            }""")
            assert px_stats["colors"] > 100, \
                f"画面色彩单一: {px_stats['colors']} 色"
            assert px_stats["nonBlank"] > px_stats["samples"] * 0.2, \
                f"画面大面积空白: {px_stats}"
            assert px_stats["bright"] > px_stats["samples"] * 0.02, \
                f"无明亮像素（地形未绘制?）: {px_stats}"
            # 断言 3：缺图回退在页面显式可见（不静默假装有动画）
            page.locator("#diagnostics summary").click()
            report = page.inner_text("#fallback-report")
            assert "special_attack" in report and "missing" in report, \
                f"fallback 报告缺项: {report[:120]!r}"
            # 断言 4：单位按世界尺寸投影（NC-03）——绘制尺寸 = 世界足迹投影，
            # 远小于图集像素宽（旧 drawSprite 用 128px 图集宽冒充物理尺寸）。
            bug_draw = next(d for d in draws
                            if d.get("key") and not d.get("culled")
                            and d.get("scale") is not None)
            mfs = json.loads((ctx.web_out / "manifest.json")
                             .read_text(encoding="utf-8"))
            lv02m = next(lv for lv in mfs["levels"] if lv["id"] == "level_02")
            # NC-03：scale=lam（图集像素→画布像素）——瓦片绘制宽 = 128×lam，
            # 内容宽 ≈ 0.8×；远小于旧 drawSprite 的图集像素宽（k×128）
            drawn_w = 128 * bug_draw["scale"]
            assert 3 < drawn_w < 60, \
                f"单位绘制宽度 {drawn_w:.1f}px 不在世界尺寸范围（图集像素宽冒充物理尺寸？）"
            # Python 权威复刻与 host.js unitBillboard 一致（跨环境空间合同）
            exp_px, exp_py, exp_camz, exp_lam = _unit_billboard(
                ctx.web_out, bug_draw["unit"], bug_draw["pos"], lv02m["world"])
            assert abs(bug_draw["scale"] - exp_lam) < 1e-6 * max(1, exp_lam), \
                f"unitBillboard lam 不一致: {bug_draw['scale']} vs {exp_lam}"
            assert abs(bug_draw["px"] - exp_px) < 1e-6 * max(1, abs(exp_px)), \
                f"unitBillboard px 不一致: {bug_draw['px']} vs {exp_px}"
            assert abs(bug_draw["py"] - exp_py) < 1e-6 * max(1, abs(exp_py)), \
                f"unitBillboard py 不一致: {bug_draw['py']} vs {exp_py}"
            assert abs(bug_draw["camZ"] - exp_camz) < 1e-6 * max(1, exp_camz), \
                f"unitBillboard camZ 不一致: {bug_draw['camZ']} vs {exp_camz}"
            shot = ctx.run_dir / "c03-render.png"
            page.screenshot(path=str(shot))
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面/控制台错误: {errors[:5]}"
    return CaseResult("PASS",
                      f"{len(drew_bugs)} 虫精灵+花+巢+蜜绘制；存活实体 "
                      f"{len(alive)}/{len(alive)} draw/裁剪可解释；"
                      f"canvas {px_stats['colors']} 色/bright "
                      f"{px_stats['bright']}；缺图回退 {len(fb_hits)} 类")


# ── C04 手动时钟 30/60/144Hz+抖动（H4） ──────────────────────────────
def _frames(hz, seconds=1.0, jitter=None):
    """合成帧时刻表（毫秒）；jitter=逐帧偏移序列（确定性）。"""
    out, t, i = [], 0.0, 0
    step = 1000.0 / hz
    while t < seconds * 1000:
        j = jitter[i % len(jitter)] if jitter else 0
        out.append(t + j)
        t += step
        i += 1
    return out


def c04(ctx):
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            audits, ticks = {}, {}
            for name, frames in (
                    ("30Hz", _frames(30, seconds=1.05)),
                    ("60Hz", _frames(60, seconds=1.05)),
                    ("144Hz", _frames(144, seconds=1.05)),
                    ("60Hz+抖动", _frames(60, seconds=1.05,
                                          jitter=[3, -4, 8, -7, 2, -2]))):
                page.evaluate("window.__bb_test.resetGame(2026)")
                page.wait_for_timeout(50)
                r = page.evaluate(
                    "t => window.__bb_test.simulateClock(t)", frames)
                assert r["paused"] is False and r["backlog"] is False, \
                    f"{name} 异常暂停: {r}"
                ticks[name] = r["tick"]
                audits[name] = page.evaluate("window.__bb_test.audit()")
                assert r["tick"] == 20, \
                    f"{name}: 1s 模拟应推进 20 tick，得 {r['tick']}"
            assert len({json.dumps(a, sort_keys=True)
                        for a in audits.values()}) == 1, \
                "不同渲染频率/抖动下同输入状态分叉"
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:3]}"
    return CaseResult("PASS", "30/60/144Hz+抖动 → 各 20 tick 且 audit 全等")


# ── C05 暂停/继续 + 标签页隐藏（H4） ─────────────────────────────────
def c05(ctx):
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(10)")
            # 暂停：墙钟流逝不推进；买兵被拒（合同：暂停期间拒绝输入）
            page.evaluate("window.__bb_test.pause()")
            page.evaluate("window.__bb_test.simulateClock([100,200,400,800])")
            assert page.evaluate("window.__bb_test.currentTick()") == 10, \
                "暂停期间逻辑 tick 推进了"
            ui = page.evaluate("window.__bb_test.uiState()")
            assert any(ui["buyDisabled"]), "暂停时买兵按钮未禁用"
            # 禁用按钮不派发 click（UI 层第一道拒绝）；同一 submitBuy 处理器
            # （按钮 onclick 同一函数）验证 E_PAUSED 兜底路径
            page.evaluate("window.__bb_test.buy('ant')")
            receipt = page.evaluate("window.__bb_test.receipt()")
            assert receipt["queued"] is False \
                and receipt["reason"] == "E_PAUSED", \
                f"暂停买兵未被拒绝: {receipt}"
            # 继续：锚点重置，不补算暂停时长（+250ms → 恰 5 tick）
            page.evaluate("window.__bb_test.resume()")
            page.evaluate("window.__bb_test.simulateClock([0, 50, 100, 150, 200, 250])")
            t = page.evaluate("window.__bb_test.currentTick()")
            assert t == 15, f"恢复后应从 10 → 15（不补算），得 {t}"
            # 标签页隐藏自动暂停 / 恢复
            assert page.evaluate("window.__bb_test.hiddenPause(true)") is True, \
                "隐藏未触发自动暂停"
            page.evaluate("window.__bb_test.simulateClock([300, 600])")
            assert page.evaluate("window.__bb_test.currentTick()") == 15, \
                "隐藏暂停期间 tick 推进"
            assert page.evaluate("window.__bb_test.hiddenPause(false)") is False, \
                "可见未自动恢复"
            page.evaluate("window.__bb_test.simulateClock([0, 100, 200])")
            assert page.evaluate("window.__bb_test.currentTick()") == 19, \
                "自动恢复后未续跑（锚点未重置则不同值）"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "暂停无推进+买兵拒 E_PAUSED+恢复不补算；"
                      "隐藏自动暂停/恢复锚点重置")


# ── C06 重开 10 次（H4：无泄漏/无监听翻倍） ──────────────────────────
def c06(ctx):
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            for i in range(10):
                page.evaluate(f"window.__bb_test.resetGame({SEED + i})")
                ui = page.evaluate("window.__bb_test.uiState()")
                assert ui["tick"] == 0 and ui["eventCursor"] == 0, \
                    f"第 {i} 次重开后 tick/游标未清零: {ui}"
            # 重开 10 次后一次点击只买一只（监听器不翻倍）
            page.click("#buy-littlebeetle")
            page.wait_for_timeout(200)
            page.evaluate("window.__bb_test.advanceTo(3)")
            evs = page.evaluate("window.__bb_test.events()")
            buys = [e for e in evs["events"] if e["type"] == "buy_ok"]
            assert len(buys) == 1, f"一次点击产生 {len(buys)} 次购买（监听翻倍?）"
            log_lines = page.evaluate(
                "document.getElementById('eventlog').childElementCount")
            assert log_lines >= 1, "事件日志未渲染"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "10 次重开 tick/游标清零、一次点击恰 1 购买、"
                      "事件日志更新")


# ── C07 点击选道映射（H3：CSS 缩放/resize/DPR/边缘） ─────────────────
def c07(ctx):
    sync_playwright = _need_playwright()
    errors = []
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    pr = mf["projection"]["world_02"]
    world = json.loads((ctx.web_out / "worlds" / "world_02.json")
                       .read_text(encoding="utf-8"))
    starts0 = {s["index"]: s["pos"] for s in world["starts"] if s["sideId"] == 0}
    url, srv = _serve(ctx.web_out)

    def to_canvas(x, z):
        # 静态斜俯视透视（host.js worldToCanvas 同公式，y=0 地面）
        dx = x - pr["cx"]; dz = z - pr["cz"]
        cam_z = pr["distance"] + dz * pr["cosP"]
        ndc_x = pr["cot"] * dx / cam_z
        ndc_y = pr["cot"] * (dz * pr["sinP"]) / cam_z
        tx = (ndc_x + 1) * 0.5 * pr["size"]
        ty = (1 - ndc_y) * 0.5 * pr["size"]
        return tx * 640 / pr["size"], ty * 640 / pr["size"]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            results = []
            for dpr, vp in ((1, (1000, 720)), (2, (1000, 720)),
                            (1, (420, 700))):        # 窄窗 → canvas CSS 缩放
                page = browser.new_page(viewport={"width": vp[0], "height": vp[1]},
                                        device_scale_factor=dpr)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()", timeout=60000)
                page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()",
                    timeout=60000)
                _set_camera_and_wait(page, None, ctx, errors, "c07-explicit-overview")
                page.evaluate("window.__bb_test.advanceTo(1)")
                got = {}
                for lane, pos in sorted(starts0.items()):
                    cx, cy = to_canvas(pos[0], pos[2])
                    # 每次点击前重测画布位置（防布局竞态），并滚入视野
                    page.evaluate(
                        "document.getElementById('worldstage')"
                        ".scrollIntoView({block: 'center'})")
                    box = page.evaluate(
                        "() => { const c = document.getElementById('scene');"
                        " const r = c.getBoundingClientRect();"
                        " return {l: r.left, t: r.top, w: r.width, h: r.height,"
                        " bl: c.clientLeft, bt: c.clientTop}; }")
                    # NC-03：backing ↔ 内容框（border-box 减边框）精确换算——
                    # 旧版按 border-box 线性映射（与 canvasToWorld 同一系统性
                    # 偏移互相抵消）；边框感知后独立校验精确合同
                    cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
                    px = box["l"] + box["bl"] + cx * cw / 640
                    py = box["t"] + box["bt"] + cy * ch / 640
                    # 直接逆映射断言：mapClient(px,py) ≈ 出生点世界坐标
                    # （1 backing px ≈ 1.1 世界单位；容差 ±4）
                    wx, wz = page.evaluate(
                        "([x, y]) => window.__bb_test.mapClient(x, y)",
                        [px, py])
                    assert abs(wx - pos[0]) < 4.0 and abs(wz - pos[2]) < 4.0, \
                        (f"DPR={dpr} 宽={vp[0]} 泳道 {lane} 逆映射偏差: "
                         f"mapClient=({wx:.1f},{wz:.1f}) vs start="
                         f"({pos[0]:.1f},{pos[2]:.1f})")
                    page.mouse.click(px, py)
                    got[lane] = page.evaluate("window.__bb_test.lane()")
                # 点击地图边缘外（letterbox 角）→ 不改选
                box = page.evaluate(
                    "() => { const r = document.getElementById('scene')"
                    ".getBoundingClientRect();"
                    "  return {l: r.left, t: r.top, w: r.width, h: r.height}; }")
                page.mouse.click(box["l"] + 3, box["t"] + 3)
                after_edge = page.evaluate("window.__bb_test.lane()")
                results.append((dpr, vp[0], got, after_edge))
                page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"C07 page errors: {errors}"
    for dpr, w, got, after_edge in results:
        for lane, selected in got.items():
            assert selected == str(lane), \
                f"DPR={dpr} 宽={w}: 点击泳道 {lane} 落到 {selected}（坐标拉伸错位）"
    # 边角点击不得清空/改选（仍是最后一次有效选择）
    for _, _, _, after_edge in results:
        assert after_edge in ("0", "1", "2", "3"), \
            f"边缘点击误选: {after_edge!r}"
    return CaseResult("PASS",
                      f"DPR 1/2 + 窄窗（CSS 缩放）点击 {len(starts0)} 泳道全中 + "
                      f"{len(starts0)}×3 视口逆映射直接断言（内容框精确换算，"
                      "边框偏移已修）；letterbox 边角无误选")


# ── C08 真实时钟 UI 命令日志 native 复放（H3） ───────────────────────
def c08(ctx):
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    diag = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.goto(f"{url}index.html?record=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            try:
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            except Exception:                    # noqa: BLE001 - 诊断后重抛
                diag.append("status=" + page.evaluate(
                    "document.getElementById('status').textContent"))
                diag.append("class=" + page.evaluate(
                    "document.getElementById('status').className"))
                diag.append("errbox=" + page.evaluate(
                    "document.getElementById('error-detail').textContent"))
                diag.append("errors=" + "; ".join(errors[:5]))
                raise
            page.wait_for_timeout(1200)            # 真实 rAF 时钟跑 ~24 tick
            page.click("#buy-littlebeetle")        # 泳道 0
            page.select_option("#lane", "1")
            page.wait_for_timeout(400)
            page.click("#buy-ant")
            page.wait_for_timeout(1200)
            # 先暂停再采样：消除真实时钟在 tick 读取与 audit 之间的推进竞态
            page.evaluate("window.__bb_test.pause()")
            final_tick = page.evaluate("window.__bb_test.currentTick()")
            receipts = page.evaluate("window.__bb_test.receipts()")
            audit_c = page.evaluate("window.__bb_test.audit()")
            page.screenshot(path=str(ctx.run_dir / "c08-record.png"))
            browser.close()
    finally:
        srv.shutdown()
    if diag:
        raise AssertionError(f"C08 诊断: {' | '.join(diag)}")
    assert not errors, f"页面错误: {errors[:3]}"
    buys = [r for r in receipts if r and r.get("queued")]
    assert len(buys) == 2, f"UI 买兵记录异常: {receipts}"
    # native 复放：同命令日志（commandId/targetTick/unit/lane）CPython 重建
    data = {
        "level": json.loads((ctx.web_out / "levels" / "level_02.json")
                            .read_text(encoding="utf-8")),
        "world": json.loads((ctx.web_out / "worlds" / "world_02.json")
                            .read_text(encoding="utf-8")),
        "units": json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8")),
    }
    b = web_bridge.WebBridge()
    info = b.init("level_02", SEED, data["level"], data["world"], data["units"],
                  opts={"buyable": ["ant", "littlebeetle", "bee"]})
    for r in buys:
        cmd = {"commandId": r["commandId"], "targetTick": r["targetTick"],
               "type": "buy", "unit": r["unit"], "lane": r["lane"]}
        rr = b.submit(dict(cmd, sessionId=info["sessionId"]))
        assert rr["queued"], f"复放被拒: {rr} vs {cmd}"
    while b.session.sim.tick < final_tick and b.session.sim.winner is None:
        b.advance(min(5, final_tick - b.session.sim.tick))
    audit_b = b.audit_state()
    if audit_b != audit_c:
        raise AssertionError(f"UI 命令日志 native 复放分歧 @tick {final_tick}: "
                             f"{_first_diff(audit_b, audit_c)}")
    return CaseResult("PASS",
                      f"真实 rAF 时钟 {final_tick} tick + 2 次 UI 买兵 → "
                      "native 复放 audit 全等")


# ── C09 level_02 完整一局（W5：生产页完整操作链，无测试 hook） ───────
def c09(ctx):
    """固定自动购买脚本驱动真实 UI：选关开始 → 买兵 → 终局 → 终局文案 → 重开。

    自动购买节奏（固定并提交于本用例，非生产代码）：每 ~500ms 依次
    ant×2 → littlebeetle 轮换，泳道 0-3 轮转；按钮禁用时跳过。
    """
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 760})
            page_errors = []
            page.on("pageerror", lambda e: page_errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: page_errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.goto(f"{url}index.html?seed={SEED}")
            # 1) 选关开始屏（生产流程，无 hook）
            page.wait_for_selector("#overlay:not([hidden])", timeout=20000)
            page.click(".level-btn.sel")
            page.fill("#seed-input", str(SEED))
            page.click("#start-btn")
            page.wait_for_function(
                "document.getElementById('overlay').hidden === true",
                timeout=30000)
            page.wait_for_function(
                "document.getElementById('hud-nectar').textContent !== '—'",
                timeout=30000)
            # 2) 自动购买驱动直至终局（level_02 bot 参考 ~1264t ≈ 63s 墙钟）
            deadline_ms = 180_000
            start = __import__("time").monotonic()
            winner_text = None
            seq = 0
            units = ("ant", "ant", "littlebeetle")
            while __import__("time").monotonic() - start < deadline_ms / 1000:
                if page.is_visible("#endscreen:not([hidden])"):
                    winner_text = page.inner_text("#end-title")
                    break
                unit = units[seq % len(units)]
                lane = seq % 4
                seq += 1
                if not page.is_disabled(f"#buy-{unit}"):
                    page.select_option("#lane", str(lane))
                    try:
                        # 短超时：终局与点击竞态时让路（下一轮终局检测退出）
                        page.click(f"#buy-{unit}", timeout=2000)
                    except Exception:              # noqa: BLE001 - 竞态让路
                        pass
                elif page.is_visible("#pause-btn:not([disabled])") \
                        and page.inner_text("#pause-btn") == "继续":
                    page.click("#pause-btn")      # backlog 自动暂停 → 继续
                page.wait_for_timeout(500)
            assert winner_text is not None, \
                f"180s 内未终局（tick={page.inner_text('#tick')}）"
            assert winner_text == "胜利！", f"终局结果: {winner_text}"
            # 终局文案（texts.json LEVELWIN_02 值）
            texts = json.loads((ctx.web_out / "texts.json").read_text(encoding="utf-8"))
            end_text = page.inner_text("#end-text")
            assert end_text == texts["LEVELWIN_02"], \
                f"终局文案不符: {end_text[:40]!r}"
            # 3) 重开（终局屏按钮）→ 新一局 tick 从 0 重新计
            page.click("#end-restart")
            page.wait_for_function(
                "document.getElementById('endscreen').hidden === true",
                timeout=20000)
            page.wait_for_function(
                "document.getElementById('tick').textContent === '0'"
                " || parseInt(document.getElementById('tick').textContent) < 50",
                timeout=20000)
            shot = ctx.run_dir / "c09-end.png"
            page.screenshot(path=str(shot))
            tick_after = int(page.locator("#tick").text_content())
            assert tick_after < 50, f"重开后 tick 未重置: {tick_after}"
            # 4) 返回选关
            page.click("#back-btn")
            page.wait_for_selector("#overlay:not([hidden])", timeout=10000)
            browser.close()
    finally:
        srv.shutdown()
    assert not page_errors, f"页面错误: {page_errors[:5]}"
    return CaseResult("PASS", f"生产页完整一局：胜利（{winner_text}）+ 终局文案"
                      " + 重开 tick 重置 + 返回选关")


# ── C10 坏 manifest / 缺音频（H4 故障恢复） ──────────────────────────
def c10(ctx):
    sync_playwright = _need_playwright()
    # 1) 坏 manifest（JSON 损坏）→ 显式错误，非永久 loading
    # HARNESS-01（F1 迁移，独立审查 2026-09-27）：整包副本经 scratch 登记
    broken = ctx.work_dir("broken-manifest")
    if broken.exists():
        shutil.rmtree(broken)
    shutil.copytree(ctx.web_out, broken,
                    ignore=shutil.ignore_patterns("audio"))
    (broken / "manifest.json").write_text("{broken json", encoding="utf-8")
    url, srv = _serve(broken)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_selector("#status.error", timeout=20000)
            assert page.is_visible("#error-box"), "错误框未显示"
            page.screenshot(path=str(ctx.run_dir / "c10-bad-manifest.png"))
            browser.close()
    finally:
        srv.shutdown()
    # 2) 缺音频（audio/ 目录整体移除）→ 逻辑不阻断，tick 照常推进
    noaudio = ctx.work_dir("no-audio")
    if noaudio.exists():
        shutil.rmtree(noaudio)
    shutil.copytree(ctx.web_out, noaudio,
                    ignore=shutil.ignore_patterns("audio"))
    url, srv = _serve(noaudio)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(10)")
            assert page.evaluate("window.__bb_test.currentTick()") == 10, \
                "缺音频时逻辑被阻断"
            astate = page.evaluate("window.__bb_test.audioState()")
            assert astate["sfxLoaded"] or astate["note"], \
                "音频缺失败未被记录（应显式 note 不静默）"
            page.screenshot(path=str(ctx.run_dir / "c10-no-audio.png"))
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "坏 manifest→显式错误；缺音频→逻辑照常+显式 note")


# ── P01–P05 性能（W6/H5；预算=合同 §7.1 参考机器工程目标） ───────────
def _pct(samples, p):
    if not samples:
        return None
    s = sorted(samples)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def p01(ctx):
    """冷/热启动可交互 ≤15s ×3（冷=新 context，热=同 context 新页）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    import time
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            cold, hot = [], []
            for i in range(3):
                context = browser.new_context()      # 冷：全新缓存
                page = context.new_page()
                t0 = time.monotonic()
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()", timeout=60000)
                page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                cold.append(time.monotonic() - t0)
                context.close()
            context = browser.new_context()
            for i in range(3):                       # 热：同 context 复用缓存
                page = context.new_page()
                t0 = time.monotonic()
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()", timeout=60000)
                page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                hot.append(time.monotonic() - t0)
                page.close()
            context.close()
            browser.close()
    finally:
        srv.shutdown()
    worst = max(cold + hot)
    assert worst <= 15.0, f"启动超预算: cold={cold} hot={hot}"
    return CaseResult("PASS",
                      f"冷={[f'{t:.1f}' for t in cold]}s "
                      f"热={[f'{t:.1f}' for t in hot]}s（max {worst:.1f}s ≤15s）")


def p02(ctx):
    """100 虫逻辑 tick p95 ≤50ms（同用户路径买 100 只免费蚁；advance 批计时）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            # 100 只免费 ant（同 submitBuy 用户路径；蚂蚁采集→巡逻/回巢全链负载）。
            # OFR-02B：泳道冷却下跨 4 泳道分散，每批 200 tick 让冷却到期；
            # 敌方脚本虫会沿途击杀采集蚁 → 超买 160 只（40 批）以保 ≥100 存活。
            page.evaluate("""async () => {
              for (let batch = 0; batch < 40; batch++) {
                for (let lane = 0; lane < 4; lane++) {
                  document.getElementById('lane').value = String(lane);
                  await window.__bb_test.buy('ant');
                }
                await window.__bb_test.advanceTo((batch + 1) * 200);
              }
            }""")
            snap = page.evaluate("window.__bb_test.snapshot()")
            base = snap["tick"]
            alive = sum(1 for b in snap["bugs"] if not b["dead"])
            assert alive >= 100, f"100 虫场景未建立（存活 {alive}）"
            # 500 tick 分批计时（含 snapshot+events 往返=真实每批成本；从建场后 base 起）
            batches = page.evaluate("""async (base) => {
              const t = [];
              for (let i = 1; i <= 100; i++) {
                const t0 = performance.now();
                await window.__bb_test.advanceTo(base + i * 5);
                t.push(performance.now() - t0);
              }
              return t;
            }""", base)
            per_tick = [ms / 5 for ms in batches]
            p95 = _pct(per_tick, 95)
            worst = max(per_tick)
            (ctx.run_dir / "p02-advance.json").write_text(
                json.dumps({"batchesMs": batches, "perTickMs": per_tick}),
                encoding="utf-8")
            browser.close()
    finally:
        srv.shutdown()
    assert p95 is not None and p95 <= 50.0, \
        f"100 虫逻辑 tick p95={p95:.1f}ms >50ms（worst {worst:.1f}ms）"
    return CaseResult("PASS", f"100 虫 500 tick：per-tick p95={p95:.1f}ms "
                      f"worst={worst:.1f}ms ≤50ms")


def p03(ctx):
    """真实时钟 60s 负载：主线程帧间隔 p95≤33.4ms + tick 漂移 + 游标/内存。

    60 虫规模（买 60 只蚁）持续负载；漂移=|tick − 墙钟×20|（backlog 暂停会
    显式暴露而非静默）。
    """
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    import time
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?record=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.evaluate("""async () => {
              for (let i = 0; i < 60; i++) { await window.__bb_test.buy('ant'); }
            }""")
            t0 = time.monotonic()
            page.wait_for_timeout(60000)             # 60s 真实负载
            elapsed = time.monotonic() - t0
            stats = page.evaluate("window.__bb_test.perfStats()")
            evs = page.evaluate("window.__bb_test.events()")
            shot = ctx.run_dir / "p03-load.png"
            page.screenshot(path=str(shot))
            browser.close()
    finally:
        srv.shutdown()
    frames = stats["frameTimes"]
    p95 = _pct(frames, 95)
    expected = elapsed * 20
    drift = abs(stats["tick"] - expected)
    report = {"frameP95": p95, "frameCount": len(frames), "tick": stats["tick"],
              "elapsedSec": elapsed, "driftTicks": drift,
              "backlog": stats["backlog"], "mem": stats["mem"]}
    (ctx.run_dir / "p03-load.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    assert not stats["backlog"], "60s 负载触发 backlog 自动暂停（性能不足）"
    assert p95 is not None and p95 <= 33.4, \
        f"主线程帧间隔 p95={p95:.1f}ms >33.4ms"
    assert drift <= max(40, expected * 0.05), \
        f"tick 漂移 {drift:.0f}（期望 ~{expected:.0f}）"
    assert evs.get("gap") is not True, "事件游标出现 gap"
    mem_note = f"JS堆 {stats['mem']['usedJSHeapMB']}MB" if stats["mem"] \
        else "performance.memory 不可用"
    return CaseResult("PASS", f"60s 负载：帧 p95={p95:.1f}ms≤33.4ms；"
                      f"tick {stats['tick']} 漂移 {drift:.0f}；{mem_note}"
                      "（WASM 堆不可测=缺口）")


def p04(ctx):
    """10 次重开：JS heap 无持续增长（泄漏代理）+ resetCount。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            before = page.evaluate("window.__bb_test.perfStats()")
            for i in range(10):
                page.evaluate(
                    f"window.__bb_test.resetGame({SEED + i})")
                page.wait_for_timeout(150)
            page.wait_for_timeout(2000)              # 稳定化
            after = page.evaluate("window.__bb_test.perfStats()")
            count = page.evaluate("window.__bb_test.resetCount()")
            browser.close()
    finally:
        srv.shutdown()
    assert count == 10, f"resetCount={count}"
    report = {"before": before["mem"], "after": after["mem"]}
    (ctx.run_dir / "p04-reset.json").write_text(
        json.dumps(report), encoding="utf-8")
    # PBA-09：生命周期(resetCount=10)已独立验证；heap 无增长是 required 命题，
    # 缺 performance.memory 时无法验证 → BLOCKED（不虚构缺指标、不改 required 回避）。
    if not before["mem"] or not after["mem"]:
        raise BlockedError("performance.memory 不可用——10 次重开 heap 对比无法验证"
                           "（生命周期 resetCount=10 已通过）")
    growth = after["mem"]["usedJSHeapMB"] - before["mem"]["usedJSHeapMB"]
    assert growth < 150, f"10 次重开 JS heap 增长 {growth}MB（疑似泄漏）"
    return CaseResult("PASS", f"10 次重开 heap {before['mem']['usedJSHeapMB']}"
                      f"→{after['mem']['usedJSHeapMB']}MB"
                      f"（Δ{growth:+d}MB<150；WASM 堆缺口标注）")


# ── C02 坏包错误路径 ─────────────────────────────────────────────────
def c02(ctx):
    sync_playwright = _need_playwright()
    if not (ctx.web_out / "py-bundle.json").is_file():
        raise BlockedError("out/web 无 py-bundle.json——需含 vendor 的重建")
    # HARNESS-01（F1 迁移，独立审查 2026-09-27）：整包工作副本经 scratch 登记，
    # PASS 回收/FAIL 有界保留——不再落 out/web-harness run_dir
    broken = ctx.work_dir("broken-web")
    if broken.exists():
        shutil.rmtree(broken)
    shutil.copytree(ctx.web_out, broken, ignore=shutil.ignore_patterns("vendor"))
    url, srv = _serve(broken)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            # 缺 pyodide → Worker bootError/网络失败 → 显式错误（非永久 loading）
            page.wait_for_selector("#status.error", timeout=20000)
            status = page.inner_text("#status")
            assert any(w in status for w in ("失败", "错误", "异常")), \
                f"错误信息不明确: {status!r}"
            assert page.is_visible("#error-box"), "错误框未显示"
            shot = ctx.run_dir / "c02-broken.png"
            page.screenshot(path=str(shot))
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", f"缺 vendor → 显式错误（{status[:40]}…），"
                      "无永久 loading")


# ── F01 full 覆盖矩阵（W7/H5：每关装载+500 tick，浏览器复用 runtime） ──
def f01(ctx):
    """full 包全部关卡：startGame(reset) → 500 tick 短跑 → 无异常/不误判。"""
    sync_playwright = _need_playwright()
    if ctx.profile != "full":
        raise BlockedError("F01 仅适用 full profile")
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    levels = [lv["id"] for lv in mf["levels"]]
    assert len(levels) >= 60, f"full 关数异常: {len(levels)}"
    url, srv = _serve(ctx.web_out)
    rows = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page_errors = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            for lid in levels:
                page.evaluate(
                    f"window.__bb_test.startGame({lid!r}, {SEED})")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                page.evaluate("window.__bb_test.advanceTo(500)")
                snap = page.evaluate("window.__bb_test.snapshot()")
                rows.append({"id": lid, "tick": snap["tick"],
                             "winner": snap["winner"],
                             "alive": sum(1 for b in snap["bugs"]
                                          if not b["dead"])})
            browser.close()
    finally:
        srv.shutdown()
    (ctx.run_dir / "f01-coverage.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    assert not page_errors, f"页面错误: {page_errors[:3]}"
    bad = [r for r in rows if r["tick"] < 500 and r["winner"] is None]
    assert not bad, f"未到 500 tick 且无终局: {bad[:5]}"
    early = [r for r in rows if r["winner"] is not None]
    by_type = {}
    for lv in mf["levels"]:
        by_type.setdefault(lv["type"], []).append(lv["id"])
    return CaseResult("PASS",
                      f"{len(rows)} 关装载+500t（类型分布 "
                      + ", ".join(f"{k}×{len(v)}" for k, v in
                                  sorted(by_type.items()))
                      + f"；早终局 {len(early)} 关: "
                      + ", ".join(f"{r['id']}@t{r['tick']}" for r in early[:6])
                      + "）")


# ── F02 各类型完整终局（W7/H5：加速驱动到规定结束条件） ──────────────
# 各类型驱动策略（镜像 tests/test_e2e 各类型 Bot 调参；纯测试代码不进生产页）
# (level, 说明, cap, 预期, 策略 ants/attackUnit/garrison/lane)
_FULL_RUNS = [
    ("level_02", "battle：摧毁敌巢", 8000, 0,
     {"ants": 8, "attack": "littlebeetle", "garrison": None, "lane": 0}),
    ("level_01", "gather：GoalNectar 达标", 12000, 0,
     {"ants": 20, "attack": None, "garrison": 0, "lane": 0, "rotate": False}),
    ("level_04", "defense：速攻或倒计时存活", 10000, 0,
     {"ants": 6, "attack": "littlebeetle", "garrison": None, "lane": 0,
      "rotate": True}),
    ("rescue_01", "rescue：接触被困虫（可买兵种流全泳道轮换）", 10000, 0,
     {"ants": 10, "attack": None, "garrison": None, "lane": 0, "rotate": True,
      "flood": True}),
    ("multi_01", "multibattle：双方 wasp 对抗（演示虫栏）", 16000, "side",
     {"ants": 10, "attack": "wasp", "garrison": 12, "lane": 0}),
    ("multir_01", "multirandom：双方 wasp 对抗（H28 演示虫栏）", 16000, "side",
     {"ants": 10, "attack": "wasp", "garrison": 12, "lane": 0}),
    ("challenge_01", "challenge：生存模式（无胜出分支；败=巢破）", 4000, "no_win",
     {"ants": 8, "attack": "littlebeetle", "garrison": 4, "lane": 0}),
]


def f02(ctx):
    sync_playwright = _need_playwright()
    if ctx.profile != "full":
        raise BlockedError("F02 仅适用 full profile")
    url, srv = _serve(ctx.web_out)
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            for lid, desc, cap, expect, strat in _FULL_RUNS:
                page.evaluate(f"window.__bb_test.startGame({lid!r}, {SEED})")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                # 加速驱动（测试态手动推进；hook.buy 同用户路径；策略镜像
                # test_e2e 各类型 Bot 调参——attack=None 用花蜜权重最大兵种）
                out = page.evaluate("""async ([cap, strat]) => {
                  let last = 0, purchases = 0;
                  while (true) {
                    const snap = await window.__bb_test.snapshot();
                    const mine = snap.bugs.filter(b => b.side === 0 && !b.dead);
                    const ants = mine.filter(b => b.unit === 'ant').length;
                    for (let i = ants; i < strat.ants; i++) {
                      // OFR-02B：泳道冷却下采集蚁跨泳道分散（与 bot 同款）
                      document.getElementById('lane').value =
                        String((purchases++) % 4);
                      await window.__bb_test.buy('ant');
                    }
                    const attackUnit = strat.attack !== null ? strat.attack
                      : Array.from(document.querySelectorAll('button.buy'))
                          .map(b => b.dataset.unit).filter(u => u !== 'ant').pop()
                        || null;
                    if (attackUnit !== null) {
                      const have = mine.filter(b => b.unit === attackUnit).length;
                      const want = strat.garrison === null ? 1e9 : strat.garrison;
                      if (have < want) {
                        if (strat.flood) {
                          // flood：花光当前蜜持续买（E2E garrison 流量近似）
                          for (let k = 0; k < 20; k++) {
                            document.getElementById('lane').value =
                              String(purchases % 4);
                            purchases += 1;
                            const r = await window.__bb_test.buy(attackUnit);
                            if (!r.ok || !r.result || r.result.queued === false) {
                              break;
                            }
                          }
                        } else {
                          if (strat.rotate) {
                            document.getElementById('lane').value =
                              String(purchases % 4);
                            purchases += 1;
                          } else {
                            // 固定泳道（strat.lane）——rotate=False 时攻击兵种
                            // 集中同一泳道（与 test_e2e Bot 同款），不被 ant 循环残留泳道干扰
                            document.getElementById('lane').value =
                              String(strat.lane ?? 0);
                          }
                          await window.__bb_test.buy(attackUnit);
                        }
                      }
                    } else {
                      // garrison 模式：维持首个非蚁可买兵种的数量
                      const u = Array.from(
                        document.querySelectorAll('button.buy'))
                        .map(b => b.dataset.unit).find(x => x !== 'ant');
                      if (u) {
                        const have = mine.filter(b => b.unit === u).length;
                        if (have < strat.garrison) {
                          await window.__bb_test.buy(u);
                        }
                      }
                    }
                    await window.__bb_test.advanceTo(Math.min(cap, last + 20));
                    last = window.__bb_test.currentTick();
                    const w = (await window.__bb_test.snapshot()).winner;
                    if (w !== null || last >= cap) { return {tick: last, winner: w}; }
                  }
                }""", [cap, strat])
                results.append({"id": lid, "desc": desc, **out, "expect": expect})
            browser.close()
    finally:
        srv.shutdown()
    (ctx.run_dir / "f02-fullruns.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        if r["expect"] == "no_win":
            # challenge 无胜出分支：winner 只能 None（存活）或 1（巢破=负）
            assert r["winner"] in (None, 1), \
                f"{r['id']}（challenge）非法胜出: {r['winner']}"
        elif r["expect"] == "side":
            # multi 敌我同构：任一方胜都算明确终局
            assert r["winner"] in (0, 1), \
                f"{r['id']}（{r['desc']}）{r['tick']} tick 未终局"
        else:
            assert r["winner"] == r["expect"], \
                f"{r['id']}（{r['desc']}）winner={r['winner']} != {r['expect']}"
    parts = []
    for r in results:
        w = "无胜出" if r["winner"] is None else f"胜方{r['winner']}"
        parts.append(f"{r['id']}→{w}@t{r['tick']}")
    return CaseResult("PASS", "；".join(parts))


# ── F03 离线交付（W7/H5：封锁全部外网请求仍可玩） ────────────────────
def f03(ctx):
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    blocked = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            # 路由层封锁一切非本源请求（CDN 依赖=0 的硬证据）
            context.route("**/*", lambda route: (
                route.continue_() if route.request.url.startswith(url)
                else (blocked.append(route.request.url), route.abort())))
            page = context.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(100)")
            assert page.evaluate("window.__bb_test.currentTick()") == 100, \
                "离线（外网封锁）下逻辑未推进"
            snap = page.evaluate("window.__bb_test.snapshot()")
            assert any(b["side"] == 1 for b in snap["bugs"]), "离线下无脚本出兵"
            page.screenshot(path=str(ctx.run_dir / "f03-offline.png"))
            browser.close()
    finally:
        srv.shutdown()
    assert not blocked, f"存在外网请求: {blocked[:3]}"
    return CaseResult("PASS", "外网请求 0；本地 HTTP 封锁路由下 100 tick"
                      " 推进+脚本出兵正常（Pyodide vendor 全本地）")


# ── FIX-01 生命周期回归（L01–L06；loop-web-fix.md §3） ──────────────
# A2 暂停态泄漏 / stopLoop 不停 / rAF 循环重复注册 / A6 advanceTo 丢 winner /
# A23 booted 竞态 / A17 旧回包串局。生产(record)路径=真实 rAF 循环；故障注入用
# __bb_test.setReplyDelay / 受控网络延迟。

def l01(ctx):
    """A2：暂停中重开/换关 → 新局不继承 paused/backlog/错误框，且可推进。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            # 暂停（手动 + 后台）后重开，新局须干净
            page.evaluate("window.__bb_test.pause()")
            page.evaluate("window.__bb_test.hiddenPause(true)")
            page.evaluate("window.__bb_test.resetGame(2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            ui = page.evaluate("window.__bb_test.uiState()")
            assert ui["paused"] is False, f"重开后仍暂停: {ui}"
            assert ui["backlog"] is False, f"重开后 backlog 残留: {ui}"
            err_hidden = page.evaluate(
                "document.getElementById('error-box').hidden")
            assert err_hidden is True, "重开后错误框未隐藏"
            # 新局可正常推进
            page.evaluate("window.__bb_test.advanceTo(10)")
            assert page.evaluate("window.__bb_test.currentTick()") == 10, \
                "重开后新局无法推进"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "暂停/后台暂停后重开：新局不继承 paused/backlog/"
                      "错误框且可推进")


def l02(ctx):
    """stopLoop 不停：生产(record)路径返回选关后 tick 冻结（逻辑循环已停）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?record=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.wait_for_function(
                "window.__bb_test.currentTick() >= 10", timeout=30000)
            page.click("#back-btn")
            page.wait_for_selector("#overlay:not([hidden])", timeout=10000)
            # 先让在途 advance 批落定/被淘汰，再取冻结基线
            page.wait_for_timeout(400)
            t_before = page.evaluate("window.__bb_test.currentTick()")
            page.wait_for_timeout(800)
            t_after = page.evaluate("window.__bb_test.currentTick()")
            assert t_after == t_before, \
                f"返回选关后 tick 继续推进: {t_before}→{t_after}"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "返回选关后 tick 冻结（逻辑循环真正停止）")


def l03(ctx):
    """rAF 循环重复注册：生产(record)连续重开 10 次活动逻辑循环始终 ≤1。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?record=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            for i in range(10):
                page.evaluate(f"window.__bb_test.resetGame({SEED + i})")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                ls = page.evaluate("window.__bb_test.loopStats()")
                assert ls["activeLoops"] <= 1, \
                    f"第 {i} 次重开后活动逻辑循环 >1: {ls}"
            ls = page.evaluate("window.__bb_test.loopStats()")
            assert ls["running"] is True and ls["activeLoops"] == 1, \
                f"终态逻辑循环异常: {ls}"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "连续重开 10 次活动逻辑循环始终 ≤1")


def l04(ctx):
    """A23：受控网络延迟下 booted() 与 overlay/列表渲染完成对齐（多轮）。"""
    import asyncio
    from playwright.async_api import async_playwright
    url, srv = _serve(ctx.web_out)
    rounds = 20

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for _ in range(rounds):
                page = await browser.new_page()
                async def slow_texts(route):          # noqa: E306
                    if "texts.json" in route.request.url:
                        await asyncio.sleep(0.6)
                        await route.continue_()
                    else:
                        await route.continue_()
                await page.route("**/*", slow_texts)
                await page.goto(f"{url}index.html?test=1&seed={SEED}")
                # booted() 首次为真时 overlay/列表必须已就绪（A23 合同）
                await page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()",
                    timeout=60000)
                shown = await page.evaluate(
                    "!document.getElementById('overlay').hidden")
                n = await page.evaluate(
                    "document.getElementById('level-list').childElementCount")
                assert shown, "booted() 为真时 overlay 未显示（竞态复现）"
                assert n > 0, "booted() 为真时关卡列表未渲染"
                await page.close()
            await browser.close()

    try:
        asyncio.run(run())
    finally:
        srv.shutdown()
    return CaseResult("PASS", f"{rounds} 轮受控网络延迟下 booted() 与 overlay/"
                      "列表完成对齐，无竞态复显")


def l05(ctx):
    """A17：受控回包延迟下切局，旧在途回包不推进 tick/不弹终局。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?record=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.wait_for_function(
                "window.__bb_test.currentTick() >= 10", timeout=30000)
            page.evaluate("window.__bb_test.setReplyDelay(600)")
            page.click("#back-btn")
            page.wait_for_selector("#overlay:not([hidden])", timeout=10000)
            t_before = page.evaluate("window.__bb_test.currentTick()")
            page.wait_for_timeout(1200)   # 等延迟回包落地
            t_after = page.evaluate("window.__bb_test.currentTick()")
            assert t_after == t_before, \
                f"切局后旧在途回包推进了新 tick: {t_before}→{t_after}"
            endscreen = page.evaluate(
                "!document.getElementById('endscreen').hidden")
            assert not endscreen, "切局后终局屏意外弹出（旧 winner 串局）"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "切局后旧在途回包不推进 tick、不弹终局")


def l06(ctx):
    """A6：快进路径保留 winner → 终局屏出现 + 按钮锁定 + winner 一致。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            out = page.evaluate("""async () => {
              let last = 0;
              for (let i = 0; i < 60; i++) {
                const snap = await window.__bb_test.snapshot();
                const mine = snap.bugs.filter(b => b.side === 0 && !b.dead);
                const ants = mine.filter(b => b.unit === 'ant').length;
                for (let j = ants; j < 8; j++) { await window.__bb_test.buy('ant'); }
                const lbs = mine.filter(b => b.unit === 'littlebeetle').length;
                for (let j = lbs; j < 4; j++) {
                  await window.__bb_test.buy('littlebeetle');
                }
                await window.__bb_test.advanceTo(Math.min(8000, last + 200));
                last = window.__bb_test.currentTick();
                const w = (await window.__bb_test.snapshot()).winner;
                if (w !== null || last >= 8000) { return {tick: last, winner: w}; }
              }
              return {tick: last, winner: (await window.__bb_test.snapshot()).winner};
            }""")
            assert out["winner"] == 0, f"level_02 快进未胜: {out}"
            endscreen = page.evaluate(
                "!document.getElementById('endscreen').hidden")
            assert endscreen, "快进路径终局屏未出现（winner 被 advanceTo 丢弃）"
            title = page.evaluate("document.getElementById('end-title').textContent")
            assert title == "胜利！", f"终局标题不符: {title!r}"
            title_class = page.evaluate(
                "document.getElementById('end-title').className")
            assert title_class == "win", f"A5 胜局标题配色类未生效: {title_class!r}"
            ui = page.evaluate("window.__bb_test.uiState()")
            assert all(ui["buyDisabled"]), "终局后买兵按钮未锁定"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "快进路径保留 winner：终局屏出现+按钮锁定+winner 一致")


# ── FIX-03 UI 反馈（A3/A4/A8/A21/A22）──────────────────────────────
def u04(ctx):
    """A4 买兵栏中文名+价格+稳定 unit ID；A3 buy_reject 可见反馈（真实 UI 点击）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            # A4: 中文名 + 价格 + 稳定 unit ID（不靠 textContent 取 ID）
            bar = page.evaluate("""() => Array.from(
              document.querySelectorAll('button.buy')).map(b => ({
                id: b.id, unit: b.dataset.unit, text: b.textContent }))""")
            by_id = {b["id"]: b for b in bar}
            assert by_id["buy-ant"]["unit"] == "ant", f"ant data-unit: {by_id}"
            assert "工蚁" in by_id["buy-ant"]["text"], f"ant 无中文名: {by_id}"
            assert "0" in by_id["buy-ant"]["text"], f"ant 无价格: {by_id}"
            assert by_id["buy-littlebeetle"]["unit"] == "littlebeetle", \
                f"littlebeetle data-unit: {by_id}"
            assert "小型甲虫" in by_id["buy-littlebeetle"]["text"], \
                f"littlebeetle 无中文名: {by_id}"
            assert "3" in by_id["buy-littlebeetle"]["text"], \
                f"littlebeetle 无价格: {by_id}"
            # A3: 真实 UI 点击买空花蜜（level_02 初始蜜 10，littlebeetle 价 3，
            # 跨 4 泳道各买 1 只 → 蜜 10→7→4→1，第 4 次 E_PRICE）→ 可见「花蜜不足」
            # （OFR-02B：同泳道连点会被冷却拦成 E_CD，故跨泳道以触发 E_PRICE）
            page.evaluate("window.__bb_test.advanceTo(1)")
            for lane in range(4):
                page.select_option("#lane", str(lane))
                page.click("#buy-littlebeetle")
            page.evaluate("window.__bb_test.advanceTo(20)")
            feedback = page.evaluate(
                "document.getElementById('buy-feedback').textContent")
            assert "花蜜不足" in feedback, f"buy_reject 无可见反馈: {feedback!r}"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "买兵栏中文名+价格+稳定 unit ID；buy_reject 可见反馈")


def u05(ctx):
    """A8 泳道下拉来自世界 START（非硬编码 0..3）；地图泳道标记；非法点击不改选+提示。"""
    sync_playwright = _need_playwright()
    world = json.loads((ctx.web_out / "worlds" / "world_02.json")
                       .read_text(encoding="utf-8"))
    starts0 = {s["index"]: s["pos"] for s in world["starts"] if s["sideId"] == 0}
    n_lanes = len(starts0)
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(1)")
            # 泳道下拉选项 == 世界 START 泳道数（不硬编码）
            opts = page.evaluate("""Array.from(
              document.getElementById('lane').options).map(o => o.value)""")
            assert opts == [str(i) for i in range(n_lanes)], \
                f"泳道下拉不符: {opts}（世界 START {n_lanes} 泳道）"
            # 地图泳道标记（draw log clip==='lane'）
            page.wait_for_timeout(300)          # 等 rAF 一帧
            draws = page.evaluate("window.__bb_test.drawLog()")
            lanes = [d for d in draws if d.get("clip") == "lane"]
            assert len(lanes) == n_lanes, \
                f"泳道标记数 {len(lanes)} != {n_lanes}"
            # 非法点击（远角）不改选 + 明确提示
            before = page.evaluate("window.__bb_test.lane()")
            page.evaluate("window.__bb_test.canvasClickAt(3, 3)")  # 同 onCanvasClick
            after = page.evaluate("window.__bb_test.lane()")
            assert after == before, f"非法点击改选了泳道: {before} -> {after}"
            status = page.evaluate("document.getElementById('status').textContent")
            assert "无有效泳道" in status, f"非法点击无提示: {status!r}"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS",
                      f"泳道下拉={n_lanes} 泳道（世界 START）；地图标记；非法点击提示")


def u06(ctx):
    """A21/A22 draw 标记与快照一致（depleted↔flower.nectar≤0；trapped↔bug.trapped）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(60)")
            page.wait_for_timeout(300)
            snap = page.evaluate("window.__bb_test.snapshot()")
            draws = page.evaluate("window.__bb_test.drawLog()")
            # A22: 花 draw.depleted == snapshot flower.nectar <= 0
            fd = {d["id"]: d for d in draws
                  if isinstance(d.get("id"), str)
                  and d["id"].startswith("flower:")}
            assert fd, "无花绘制"
            for f in snap["flowers"]:
                key = f"flower:{f['name']}"
                if key in fd:
                    assert fd[key].get("depleted") == ((f["nectar"] or 0) <= 0), \
                        f"{key}: depleted 与快照不一致"
            # A21: 虫 draw.trapped == snapshot bug.trapped
            bd = {d["id"]: d for d in draws if "unit" in d}
            for b in snap["bugs"]:
                if b["id"] in bd:
                    assert bool(bd[b["id"]].get("trapped")) == bool(b["trapped"]), \
                        f"bug {b['id']}: trapped 与快照不一致"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "花 depleted / 虫 trapped draw 标记与快照一致")


# ── FIX-04 内存峰值与资源生命周期（§6，M01–M03）────────────────────
def m01(ctx):
    """按关卡依赖加载图集页：loaded == deps.atlasPages（非全量 44 页解码）。"""
    sync_playwright = _need_playwright()
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            lv02 = next(lv for lv in mf["levels"] if lv["id"] == "level_02")
            needed = set(lv02["deps"]["atlasPages"])
            loaded = page.evaluate("window.__bb_test.atlasPagesLoaded()")
            assert set(loaded["loaded"]) == needed, \
                f"level_02 载入页 {sorted(loaded['loaded'])} != 依赖 {sorted(needed)}"
            total = loaded["total"]
            switch_note = ""
            other = next((lv for lv in mf["levels"]
                          if lv["id"] != "level_02"), None)
            if other is not None:
                page.evaluate(f"window.__bb_test.startGame({other['id']!r}, 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                needed2 = set(other["deps"]["atlasPages"])
                loaded2 = page.evaluate("window.__bb_test.atlasPagesLoaded()")
                assert set(loaded2["loaded"]) == needed2, \
                    f"{other['id']} 载入页 {sorted(loaded2['loaded'])} != 依赖 {sorted(needed2)}"
                switch_note = f"；换关 {other['id']} 载入 {len(needed2)} 页"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS",
                      f"level_02 载入 {len(needed)}/{total} 页（按关卡依赖）{switch_note}")


def m02(ctx):
    """RF-02：受控延迟下切世界——旧局图集回包不污染新局（loaded==新关 deps）。

    用 Playwright 路由层延迟 atlas_*.png 响应（与 host.js 版本无关），制造旧局
    图集装载在途；随后立即切世界。旧实现无会话校验会把旧局图集写回全局 → loaded
    成为旧∪新关页并集（红）；修复后旧局位图释放、不回写 → loaded==新关 deps（绿）。
    """
    sync_playwright = _need_playwright()
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    a = next(lv for lv in mf["levels"] if lv["id"] == "level_02")
    b = next(lv for lv in mf["levels"]
             if lv["world"] != a["world"]
             and set(lv["deps"]["atlasPages"]) != set(a["deps"]["atlasPages"]))
    need_a, need_b = set(a["deps"]["atlasPages"]), set(b["deps"]["atlasPages"])
    assert need_a != need_b, "预置关卡图集页集合需不同"
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            def _slow(route):
                import time as _t
                _t.sleep(1.0)
                route.continue_()
            page.route("**/atlas_*.png", _slow)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            # fire-and-forget 开局 A（在途装载）；随后立即开 B（代次+1）
            page.evaluate(f"window.__bb_test.startGame('level_02', {SEED}); true")
            page.wait_for_timeout(300)      # 等 A 进入 loading/在途
            page.evaluate(f"window.__bb_test.startGame({b['id']!r}, {SEED}); true")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.wait_for_timeout(1500)     # 等 A 的延迟图集回包落地
            loaded = page.evaluate("window.__bb_test.atlasPagesLoaded()")
            assert set(loaded["loaded"]) == need_b, \
                f"切世界后 loaded={sorted(loaded['loaded'])} != 新关 deps {sorted(need_b)}"
            # 地形切世界释放由 M03（顺序 10 次切换）验证；此处 A 在图集后即被代次
            # 淘汰、从未装载地形，故不设 terrainCloseCount 断言。
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS",
                      f"延迟切世界后 loaded=={b['id']} deps({len(need_b)}页)（无旧关 stale 页）")


def m03(ctx):
    """RF-02：10 次跨世界切换——图集页/地形无累积（terrain 释放计数递增）。"""
    sync_playwright = _need_playwright()
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    a = mf["levels"][0]
    b = next(lv for lv in mf["levels"] if lv["world"] != a["world"])
    ids = [a["id"], b["id"]]
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.setLoadDelay(0)")
            for k in range(10):
                lv_id = ids[k % 2]
                page.evaluate(f"window.__bb_test.startGame({lv_id!r}, {SEED})")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                lv = next(x for x in mf["levels"] if x["id"] == lv_id)
                need = set(lv["deps"]["atlasPages"])
                loaded = page.evaluate("window.__bb_test.atlasPagesLoaded()")
                assert set(loaded["loaded"]) == need, \
                    f"第{k}次切换 {lv_id} loaded={sorted(loaded['loaded'])} != deps {sorted(need)}"
            rs = page.evaluate("window.__bb_test.resourceState()")
            # 10 次切换（9 次换世界）→ 旧地形释放计数应 ≥9（不累积旧图集页）
            assert rs["terrainCloseCount"] >= 9, \
                f"terrainCloseCount={rs['terrainCloseCount']} < 9（旧地形未释放）"
            terrain_close = rs["terrainCloseCount"]
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS",
                      f"10 次跨世界切换 loaded 恒==当前 deps；terrainCloseCount={terrain_close}")


# ── OFR-01 回归（BUG-02/03 装载锁 + BUG-05 对话换行）────────────────
def l07(ctx):
    """BUG-02/03：装载相位锁定买兵/暂停/重开；装载中 buy=E_NOT_RUNNING 无副作用。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            # 先完整装载一局，建立买兵栏（旧栏在装载窗口内须被冻结）
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            n_buy = page.evaluate(
                "document.querySelectorAll('button.buy').length")
            assert n_buy > 0, "买兵栏未建立（前提失败）"
            # 换局（reset，同 level_02）→ 延迟 worker 回包制造确定性装载窗口
            page.evaluate("window.__bb_test.setReplyDelay(600)")
            page.evaluate("window.__bb_test.resetGame(2026); true")   # fire-and-forget
            # 装载窗口内：旧买兵栏 + 暂停 + 重开全部禁用
            ui = page.evaluate("window.__bb_test.uiState()")
            assert len(ui["buyDisabled"]) > 0 and all(ui["buyDisabled"]), \
                f"装载相位买兵按钮未禁用: {ui['buyDisabled']}"
            assert page.evaluate("document.getElementById('pause-btn').disabled"), \
                "装载相位暂停按钮未禁用（BUG-03）"
            assert page.evaluate("document.getElementById('reset-btn').disabled"), \
                "装载相位重开按钮未禁用"
            # 装载中买兵 → E_NOT_RUNNING，不静默 no-op（BUG-02）
            r = page.evaluate("window.__bb_test.buy('ant')")
            assert r == {"ok": False, "error": "E_NOT_RUNNING"}, f"装载中 buy: {r}"
            receipt = page.evaluate("window.__bb_test.receipt()")
            assert receipt == {"queued": False, "reason": "E_NOT_RUNNING"}, \
                f"装载中 receipt: {receipt}"
            # 装载完成 → 解锁且新局未暂停
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            ui = page.evaluate("window.__bb_test.uiState()")
            assert ui["paused"] is False, f"装载完成新局仍暂停: {ui}"
            assert not any(ui["buyDisabled"]), "装载完成买兵按钮仍未解锁"
            assert not page.evaluate(
                "document.getElementById('pause-btn').disabled"), \
                "装载完成暂停按钮未解锁"
            # 解锁后可正常买兵
            page.evaluate("window.__bb_test.advanceTo(1)")
            page.evaluate("window.__bb_test.buy('ant')")
            receipt = page.evaluate("window.__bb_test.receipt()")
            assert receipt["queued"] is True, f"解锁后买兵被拒: {receipt}"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "装载相位锁定买兵/暂停/重开+E_NOT_RUNNING；"
                      "完成解锁且新局未暂停")


def d01(ctx):
    """BUG-05：wrapText 先按显式换行 \\n 分段再按宽度折行（对话多行根因）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            out = page.evaluate("""() => {
              const c = document.createElement('canvas').getContext('2d');
              c.font = '14px sans-serif';
              const w = (t) => window.wrapText(c, t, 80);
              return {
                explicit: w('第一行\\n第二行'),
                blank: w('A\\n\\nB'),
                long: w('0123456789abcdefghijklmnopqrstuvwxyz'),
                single: w('单行'),
                empty: w(''),
              };
            }""")
            assert out["explicit"] == ["第一行", "第二行"], \
                f"显式换行未分段: {out['explicit']}"
            assert out["blank"] == ["A", "", "B"], f"空行丢失: {out['blank']}"
            assert len(out["long"]) >= 2, f"长文本未自动折行: {out['long']}"
            assert out["single"] == ["单行"], f"单行异常: {out['single']}"
            assert out["empty"] == [""], f"空文本异常: {out['empty']}"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS",
                      f"wrapText：显式换行{out['explicit']}/空行/自动折行"
                      f"{len(out['long'])}行/空文本 全符合")


def e01(ctx):
    """A7/A20：seed=0 有效；URL/UI 非法种子拒绝（不静默回退为 NaN/默认）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # A20：URL 非法种子 → 默认 2026 + 明确提示（不显示 NaN）
            page.goto(f"{url}index.html?test=1&seed=abc")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            assert page.evaluate("window.__bb_test.seed()") == 2026, \
                "URL 非法种子未回退默认 2026"
            assert "种子" in page.evaluate(
                "document.getElementById('status').textContent"), \
                "URL 非法种子无明确提示"
            # A7：UI seed=0 有效（不因 falsy 回退）
            page.fill("#seed-input", "0")
            page.evaluate("window.__bb_test.startGame(null, null)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            assert page.evaluate("window.__bb_test.seed()") == 0, \
                "seed=0 未生效（被 falsy 回退）"
            # 非法整数输入（绕过 type=number 校验直设值）→ 拒绝，不进入对局
            page.evaluate(
                "document.getElementById('seed-input').value = '1.5'")
            page.evaluate("window.__bb_test.startGame(null, null)")
            page.wait_for_selector("#error-box:not([hidden])", timeout=10000)
            assert "种子" in page.evaluate(
                "document.getElementById('status').textContent"), \
                "非整数种子未拒绝"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "seed=0 有效；URL/UI 非法种子拒绝且不静默回退")


def e02(ctx):
    """A19：无效关卡明确提示并可返回选择（不静默回退第一关）。"""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('nonexistent', 2026)")
            page.wait_for_selector("#error-box:not([hidden])", timeout=10000)
            assert "不存在" in page.evaluate(
                "document.getElementById('status').textContent"), \
                "无效关卡无明确提示"
            assert not page.evaluate(
                "document.getElementById('overlay').hidden"), \
                "无效关卡未返回选择"
            assert page.evaluate("window.__bb_test.levelId()") == "nonexistent", \
                "无效关卡被静默回退到其它关卡"
            browser.close()
    finally:
        srv.shutdown()
    return CaseResult("PASS", "无效关卡明确提示并返回选择")


# ── NC-01 真实浏览器/Worker 专用场景 ─────────────────────────────────
# A 终局原因与胜者：真实 Worker+桥推进至终局，断言标题/正文/样式/状态栏与
# 权威 winner/endKind 一致。合成夹具（拦截 levels/<id>.json 缩短 DefenseTime）
# 控制时长，保留合法 schema——这是合成场景，非原作运行时值。
_END_REASON = {None: None, "timeup": "时间到", "survived": "防守成功",
               "rescued": "营救成功"}


def _end_state(page):
    """读 showEndScreen 的权威值（sim winner/endKind）与 DOM 呈现。"""
    winner = page.evaluate(
        "async () => (await window.__bb_test.snapshot()).winner")
    endkind = page.evaluate("window.__bb_test.endKind()")
    return {
        "winner": winner, "endKind": endkind,
        "title": page.evaluate(
            "document.getElementById('end-title').textContent"),
        "titleClass": page.evaluate(
            "document.getElementById('end-title').className"),
        "status": page.evaluate(
            "document.getElementById('status').textContent"),
        "endText": page.evaluate(
            "document.getElementById('end-text').textContent"),
    }


def _assert_end(st, expect_winner, expect_endkind, tag, expect_text=True):
    """DOM 标题/样式/状态栏与权威 winner/endKind 一致。"""
    assert st["winner"] == expect_winner, \
        f"{tag}: winner={st['winner']} != {expect_winner}"
    assert st["endKind"] == expect_endkind, \
        f"{tag}: endKind={st['endKind']!r} != {expect_endkind!r}"
    exp_title = "胜利！" if expect_winner == 0 else "失败"
    exp_class = "win" if expect_winner == 0 else "lose"
    assert st["title"] == exp_title, \
        f"{tag}: 标题 {st['title']!r} != {exp_title!r}"
    assert st["titleClass"] == exp_class, \
        f"{tag}: 样式 {st['titleClass']!r} != {exp_class!r}"
    reason = _END_REASON[expect_endkind]
    who = "玩家胜" if expect_winner == 0 else "敌方胜"
    assert st["status"].startswith(f"终局：{who}"), \
        f"{tag}: 状态栏 {st['status']!r} 不以「终局：{who}」开头"
    if reason:
        assert reason in st["status"], \
            f"{tag}: 状态栏 {st['status']!r} 缺原因 {reason!r}"
    else:
        assert "（" not in st["status"].split("@tick")[0], \
            f"{tag}: 非超时胜负状态栏不应带原因: {st['status']!r}"
    assert "@tick" in st["status"], f"{tag}: 状态栏缺 @tick: {st['status']!r}"
    if expect_text:
        assert st["endText"], f"{tag}: 终局正文为空"


def _patch_level(page, web_out, lid, mutate):
    """合成夹具：拦截 levels/<lid>.json，返回 mutate 修改后的合法关卡。"""
    orig = json.loads((web_out / "levels" / f"{lid}.json")
                      .read_text(encoding="utf-8"))
    mutate(orig)
    body = json.dumps(orig, ensure_ascii=False)

    def handler(route):
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route(f"**/levels/{lid}.json", handler)


def n01(ctx):
    """NC-01.A：终局原因与胜者——winner/endKind → 标题/正文/样式/状态栏一致。

    真实 Worker+桥推进至终局（合成夹具只缩短 DefenseTime/调 BaseSize 控场景，
    不改 schema）。覆盖：battle 非超时胜(0,null) / defense 存活(0,survived) /
    rescue 超时负(1,timeup) / multi 我方 HP 领先超时(0,timeup) /
    **multi 等值 HP 平局超时（本地双败=1,timeup）/ multi 敌方 HP 领先超时
    (1,timeup) / battle 非超时失败（我巢破 1,null）**。
    """
    if ctx.profile != "full":
        raise BlockedError("n01 仅适用 full profile（需 defense/rescue/multi 关卡）")
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def run(lid, expect_winner, expect_endkind, patch=None, drive="end",
                    expect_text=True):
                page = browser.new_page()
                page.on("pageerror",
                        lambda e: errors.append(f"{lid} pageerror: {e}"))
                page.on("console", lambda m: errors.append(
                    f"{lid} console.{m.type}: {m.text}")
                    if m.type == "error" else None)
                if patch:
                    _patch_level(page, ctx.web_out, lid, patch)
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()",
                    timeout=60000)
                page.evaluate(f"window.__bb_test.startGame({lid!r}, {SEED})")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()",
                    timeout=60000)
                if drive == "end":
                    page.evaluate("""async () => {
                      let last = 0;
                      for (let i = 0; i < 60; i++) {
                        const snap = await window.__bb_test.snapshot();
                        const mine = snap.bugs.filter(b => b.side === 0 && !b.dead);
                        const ants = mine.filter(b => b.unit === 'ant').length;
                        for (let j = ants; j < 8; j++) {
                          await window.__bb_test.buy('ant');
                        }
                        const lbs = mine.filter(b => b.unit === 'littlebeetle').length;
                        for (let j = lbs; j < 4; j++) {
                          await window.__bb_test.buy('littlebeetle');
                        }
                        await window.__bb_test.advanceTo(Math.min(8000, last + 200));
                        last = window.__bb_test.currentTick();
                        const w = (await window.__bb_test.snapshot()).winner;
                        if (w !== null || last >= 8000) { return; }
                      }
                    }""")
                elif drive == "loss":
                    # 非超时失败：不买兵（不设防），等脚本敌兵摧毁我巢
                    page.evaluate("""async () => {
                      let last = 0;
                      for (let i = 0; i < 60; i++) {
                        await window.__bb_test.advanceTo(Math.min(8000, last + 200));
                        last = window.__bb_test.currentTick();
                        const w = (await window.__bb_test.snapshot()).winner;
                        if (w !== null || last >= 8000) { return; }
                      }
                    }""")
                else:
                    # 合成夹具短 DefenseTime：推进越过 deadline 触发终局
                    page.evaluate("window.__bb_test.advanceTo(40)")
                page.wait_for_function(
                    "document.getElementById('endscreen').hidden === false",
                    timeout=30000)
                st = _end_state(page)
                _assert_end(st, expect_winner, expect_endkind, lid,
                            expect_text=expect_text)
                page.close()
                return {"id": lid, "winner": st["winner"],
                        "endKind": st["endKind"], "status": st["status"]}

            results.append(run("level_02", 0, None, drive="end"))
            results.append(run("level_04", 0, "survived",
                               lambda lv: lv["props"].update(
                                   {"DefenseTime": ["1"],
                                    "PlayerBaseSize": ["999"]})))
            results.append(run("rescue_01", 1, "timeup",
                               lambda lv: lv["props"].update(
                                   {"DefenseTime": ["1"],
                                    "PlayerBaseSize": ["999"]})))
            results.append(run("multi_01", 0, "timeup",
                               lambda lv: lv["props"].update(
                                   {"DefenseTime": ["1"],
                                    "PlayerBaseSize": ["999"],
                                    "EnemyBaseSize": ["1"]}),
                               expect_text=False))
            # NC-01 缺口补齐（round4 恢复调度）：
            # 5) 既定平局：multi 等值 HP 超时双败（本地视角 winner=1+timeup）
            results.append(run("multi_01", 1, "timeup",
                               lambda lv: lv["props"].update(
                                   {"DefenseTime": ["1"],
                                    "PlayerBaseSize": ["999"],
                                    "EnemyBaseSize": ["999"]}),
                               drive="short", expect_text=False))
            # 6) multi 敌方 HP 领先超时（与 4) 我方领先成对）
            results.append(run("multi_01", 1, "timeup",
                               lambda lv: lv["props"].update(
                                   {"DefenseTime": ["1"],
                                    "PlayerBaseSize": ["500"],
                                    "EnemyBaseSize": ["999"]}),
                               drive="short", expect_text=False))
            # 7) 非超时失败：battle 我巢破（endKind=None，状态栏不带原因）
            results.append(run("level_02", 1, None,
                               lambda lv: lv["props"].update(
                                   {"PlayerBaseSize": ["1"]}),
                               drive="loss"))
            browser.close()
    finally:
        srv.shutdown()

    assert not errors, f"页面/控制台错误: {errors[:5]}"
    parts = [f"{r['id']}→w{r['winner']}/{r['endKind']}" for r in results]
    return CaseResult("PASS", "；".join(parts))


def n02(ctx):
    """NC-01.B：submitBuy 代次守卫——旧局延迟购买回包不污染新局。

    真实 Worker+桥：A 局提交购买 → setReplyDelay 延迟回包 → 切到 B 局 → 放行 A 的
    回包。断言 B 的 receipts/lastReceipt 不被旧请求写入，且同代次新购买仍有效。
    round4 缺口补齐：旧回包覆盖三种回执形态——queued 成功 + E_UNIT 业务拒绝
    （militant 不在 level_02 buyable）+ E_LANE 泳道无效（lane=9）；放行点精确到
    B 局 ready（init 完成、receipts 空）之后。监听 pageerror/unhandled rejection。
    超时路径（>30s call 超时后旧回包静默丢弃）与 generation 守卫移除反例见
    research/n02_guard_mutation.cjs（Node VM，可控时钟）。
    """
    if ctx.profile != "full":
        raise BlockedError("n02 仅适用 full profile（需多关卡切换）")
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("unhandledrejection",
                    lambda e: errors.append(f"unhandledrejection: {e}"))
            page.on("console", lambda m: errors.append(
                f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(1)")
            gen_a = page.evaluate("window.__bb_test.generation()")
            # 延迟回包 + fire-and-forget 提交 A 局购买（三种回执形态）
            page.evaluate("window.__bb_test.setReplyDelay(600)")
            page.evaluate(
                "window.__bb_test.buy('littlebeetle').catch(() => {}); 'fired-ok'")
            # E_UNIT：militant 在 units.json 但不在 level_02 buyable
            page.evaluate(
                "window.__bb_test.buy('militant').catch(() => {}); 'fired-unit'")
            # E_LANE：泳道 9 无效（world.start(0,9)=None）——先设泳道再买
            page.evaluate(
                "document.getElementById('lane').value = '9'")
            page.evaluate(
                "window.__bb_test.buy('ant').catch(() => {}); 'fired-lane'")
            page.wait_for_timeout(300)   # 等 worker 处理提交、回包进入延迟队列
            # 切到 B 局（init 回包同样被延迟，settle 后 ready = 精确放行点）
            page.evaluate("window.__bb_test.startGame('level_04', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            gen_b = page.evaluate("window.__bb_test.generation()")
            assert gen_b == gen_a + 1, f"generation 未递增: {gen_a}→{gen_b}"
            page.wait_for_timeout(1000)   # 放行 A 的三种延迟回包
            # B 局 receipts/lastReceipt 不被 A 的旧购买写入（含成功/业务拒绝/错误）
            assert page.evaluate("window.__bb_test.receipts()") == [], \
                "A 局旧购买回包写入了 B 局 receipts"
            assert page.evaluate("window.__bb_test.receipt()") is None, \
                "A 局旧购买回包写入了 B 局 lastReceipt"
            # 同代次新购买仍有效（守卫不破坏正常路径）
            page.evaluate("window.__bb_test.setReplyDelay(0)")
            page.evaluate(
                "document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.advanceTo(2)")
            page.evaluate("window.__bb_test.buy('ant')")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.receipt() !== null",
                timeout=10000)
            r = page.evaluate("window.__bb_test.receipt()")
            assert r["queued"] is True, f"B 局同代次购买被拒: {r}"
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面/控制台错误: {errors[:5]}"
    return CaseResult("PASS",
                      "旧局三种延迟回包（queued/E_UNIT/E_LANE）不写 B 局 "
                      "receipts/lastReceipt；同代次购买仍有效")


def n03(ctx):
    """NC-01.C：图集部分失败与重试——成功页被接管、失败页重试只补失败页。

    真实 Worker+桥：route 拦截 atlas_1.png 使其失败，其余页成功 → 部分失败
    （loadAtlasPages allSettled 不吞成功页，成功 bitmap 发布到 render.pages，失败抛错）；
    解除拦截后重开，仅重载失败页（成功页已接管不重载）。
    round4 缺口补齐：**请求计数**证明成功页不重复加载（失败页恰 2 次、成功页各
    1 次网络请求）；**旧代次晚到 bitmap 唯一所有权**（setLoadDelay 延迟 A 局解码
    → 切 B 局 → A 晚到 bitmap 经 gen 失配逐个 close：不接管不泄漏、不误关 B 的
    资源；观测面 = host.js render.atlasCloseCount）。
    """
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    import re as _re
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"console.{m.type}: {m.text}") if m.type == "error"
                and "Failed to load resource" not in m.text else None)
            # 请求计数（NC-01.C 缺口）：atlas_*.png 每文件网络请求次数
            fetch_counts = {}

            def _count_request(req):
                m = _re.search(r"atlas_\d+\.png$", req.url)
                if m:
                    fetch_counts[m.group(0)] = \
                        fetch_counts.get(m.group(0), 0) + 1

            page.on("request", _count_request)
            # 常驻 passthrough route：Playwright 存在任何 route 即禁用 HTTP 缓存
            # （否则成功页「未重复请求」可能被缓存掩盖，计数就不成硬证据）
            page.route("**/manifest.json", lambda route: route.continue_())
            mf = json.loads((ctx.web_out / "manifest.json")
                            .read_text(encoding="utf-8"))
            lv02 = next(lv for lv in mf["levels"] if lv["id"] == "level_02")
            need = sorted(set(lv02["deps"]["atlasPages"]))
            assert len(need) >= 2, "level_02 图集页 <2，无法构造部分失败"
            fail_page = need[1]           # 让第 2 个依赖页失败
            fail_file = json.loads((ctx.web_out / "atlas.json")
                                   .read_text(encoding="utf-8"))["pages"][fail_page]["file"]
            page.route(f"**/{fail_file}", lambda route: route.abort())
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            # 部分失败：错误框出现 + 成功页已发布（接管，非泄漏）
            page.wait_for_selector("#error-box:not([hidden])", timeout=30000)
            loaded = page.evaluate("window.__bb_test.atlasPagesLoaded()")
            got = set(loaded["loaded"])
            assert fail_page not in got, f"失败页 {fail_page} 不应已载入: {got}"
            assert got == (set(need) - {fail_page}), \
                f"成功页未全部接管: 缺 {set(need) - {fail_page} - got}"
            # 解除拦截 → 重开只重载失败页（成功页不重载）
            page.unroute(f"**/{fail_file}")
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            loaded2 = page.evaluate("window.__bb_test.atlasPagesLoaded()")
            assert set(loaded2["loaded"]) == set(need), \
                f"重开后 loaded={sorted(set(loaded2['loaded']))} != deps {need}"
            page.close()
            # ── 请求计数：成功页各恰 1 次、失败页恰 2 次（成功页未重复加载）──
            atlas = json.loads((ctx.web_out / "atlas.json")
                               .read_text(encoding="utf-8"))
            ok_files = [atlas["pages"][i]["file"]
                        for i in need if i != fail_page]
            assert fetch_counts.get(fail_file) == 2, \
                f"失败页 {fail_file} 应恰 2 次请求: {fetch_counts}"
            for f in ok_files:
                assert fetch_counts.get(f) == 1, \
                    f"成功页 {f} 应恰 1 次请求（重开被重复加载?）: {fetch_counts}"
            # ── 旧代次晚到 bitmap：close 唯一所有权（不接管/不泄漏/不误关 B）──
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            lv04 = next(lv for lv in mf["levels"] if lv["id"] == "level_04")
            need04 = sorted(set(lv04["deps"]["atlasPages"]))
            page.evaluate("window.__bb_test.setLoadDelay(1500)")
            # fire-and-forget：evaluate 会 await 返回的 promise——若直接调用会
            # 阻塞到 A 局完整装载（无竞态可言）；不返回 promise 才能让 A 挂起
            page.evaluate(
                "window.__bb_test.startGame('level_02', 2026); 'fired-a'")
            page.wait_for_timeout(200)
            page.evaluate("window.__bb_test.setLoadDelay(0)")
            close_before = page.evaluate(
                "window.__bb_test.resourceState().atlasCloseCount")
            page.evaluate("window.__bb_test.startGame('level_04', 2026)")  # B 新代次
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.wait_for_timeout(2500)   # A 延迟解码完成 → gen 失配 → close
            rs = page.evaluate("window.__bb_test.resourceState()")
            assert rs["atlasCloseCount"] == close_before + len(need), \
                (f"旧代次晚到 bitmap 应 close {len(need)} 个: "
                 f"{close_before} → {rs['atlasCloseCount']}")
            assert set(rs["atlasLoaded"]) == set(need04), \
                f"B 局图集被旧代次污染/误关: {rs['atlasLoaded']} != {need04}"
            page.evaluate("window.__bb_test.advanceTo(5)")
            assert page.evaluate("window.__bb_test.currentTick()") == 5, \
                "B 局在晚到 bitmap 释放后不可推进"
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面/控制台错误: {errors[:5]}"
    return CaseResult("PASS",
                      f"部分失败后成功页接管 {len(need)-1}/{len(need)}，重开只补失败页 "
                      f"{fail_file}（请求计数：失败页×2 成功页×1）；旧代次晚到 "
                      f"{len(need)} bitmap 全 close、B 资源完好可推进")


def n04(ctx):
    """NC-01.D：native↔Worker 冷却与回执——相同初态/种子/命令序列比较。

    浏览器（Worker）与 CPython（native）跑同一冷却购买序列，比较买兵事件迹
    （buy_ok/buy_reject 类型/原因/泳道/tick）与最终 laneCdUntil 全等。
    round4 缺口补齐：期限边界（前=E_CD@402 / 当=ok@403 / 后=ok@604，ant 价 0
    无花蜜约束）；reset 后审计对照（tick/nectar/nextId/winner/laneCdUntil/bugs/vm
    七字段范围 vs 全新 init）；幂等 E_DUP（native 桥层直测——Worker 内同一
    bridge 代码，B 套件等价面；页面侧无法自选 commandId，不加生产作弊入口）；
    脚本出生门禁夹具（PBA-12：同 tick 同泳道第二条 sendenemy 被拒——无实体、
    不刷新冷却、spawn_free 仅 1 条）。
    """
    sync_playwright = _need_playwright()
    if not (ctx.web_out / "py-bundle.json").is_file():
        raise BlockedError("out/web-full 无 py-bundle.json——需含 vendor 的重建")
    url, srv = _serve(ctx.web_out)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            # 与 _cpython_cd_trace 逐 tick 同构的购买序列（真实 UI 买兵路径）
            page.evaluate("window.__bb_test.advanceTo(1)")
            page.evaluate("document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.buy('littlebeetle')")
            page.evaluate("window.__bb_test.advanceTo(2)")
            page.evaluate("document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.buy('littlebeetle')")
            page.evaluate("document.getElementById('lane').value = '1'")
            page.evaluate("window.__bb_test.buy('littlebeetle')")
            page.evaluate("window.__bb_test.advanceTo(3)")
            page.evaluate("window.__bb_test.advanceTo(202)")
            page.evaluate("document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.buy('littlebeetle')")
            page.evaluate("window.__bb_test.advanceTo(203)")
            # ── 期限边界（前/当/后；ant 价 0，lane0 until=403）──
            page.evaluate("window.__bb_test.advanceTo(401)")
            page.evaluate("document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.buy('ant')")     # target 402 → E_CD
            page.evaluate("window.__bb_test.advanceTo(402)")
            page.evaluate("window.__bb_test.buy('ant')")     # target 403 → ok
            page.evaluate("window.__bb_test.advanceTo(603)")
            page.evaluate("window.__bb_test.buy('ant')")     # target 604 → ok
            page.evaluate("window.__bb_test.advanceTo(604)")
            evs = page.evaluate("window.__bb_test.events()")
            buys = [(e["type"], e["data"].get("reason"), e["data"].get("lane"),
                     e["tick"])
                    for e in evs["events"]
                    if e["type"] in ("buy_ok", "buy_reject")]
            audit = page.evaluate("window.__bb_test.audit()")
            # ── reset：同关同种子重开 → tick0 新局审计 ──
            page.evaluate("window.__bb_test.resetGame(2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            audit_reset = page.evaluate("window.__bb_test.audit()")
            page.close()
            # ── 脚本出生门禁夹具（PBA-12）：同 tick 同泳道第二条 sendenemy ──
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"console.{m.type}: {m.text}") if m.type == "error" else None)
            _patch_level(page, ctx.web_out, "level_02", _patch_scripts_insert_sendenemy)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            page.evaluate("window.__bb_test.advanceTo(4)")
            page.wait_for_timeout(100)
            evs2 = page.evaluate("window.__bb_test.events()")
            spawns = [e for e in evs2["events"] if e["type"] == "spawn_free"]
            audit2 = page.evaluate("window.__bb_test.audit()")
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面/控制台错误: {errors[:5]}"
    native = _cpython_cd_trace(ctx.web_out)
    assert buys == native["buys"], \
        f"买兵事件迹 native↔Worker 不一致:\n  worker={buys}\n  native={native['buys']}"
    assert audit["laneCdUntil"] == native["laneCdUntil"], \
        f"laneCdUntil native↔Worker 不一致:\n  worker={audit['laneCdUntil']}\n" \
        f"  native={native['laneCdUntil']}"
    kinds = [b[0] for b in buys]
    assert "buy_reject" in kinds, "序列未触发 E_CD 拒绝（同泳道二购）"
    # 期限边界事件形状（前=E_CD@402 / 当=ok@403 / 后=ok@604）
    edge = [b for b in buys if b[3] in (402, 403, 604) and b[2] == 0]
    assert ("buy_reject", "E_CD", 0, 402) in edge, f"期限前 402 未 E_CD: {edge}"
    assert ("buy_ok", None, 0, 403) in edge, f"期限当 403 未放行: {edge}"
    assert ("buy_ok", None, 0, 604) in edge, f"期限后 604 未放行: {edge}"
    # reset 后审计 == 全新 init（七字段范围）
    for k in ("tick", "nectar", "nextId", "winner", "laneCdUntil", "bugs", "vm"):
        assert audit_reset[k] == native["fresh_audit"][k], \
            f"reset 后审计字段 {k} 不等于新局: {audit_reset[k]} vs " \
            f"{native['fresh_audit'][k]}"
    # 幂等（native 桥层）：同 commandId 二次提交 → E_DUP
    assert native["dup"]["reason"] == "E_DUP" and not native["dup"]["queued"], \
        f"同 commandId 二次提交未 E_DUP: {native['dup']}"
    # 脚本出生门禁：第二条同泳道 sendenemy 被拒（PBA-12）
    native_gate = _cpython_script_gate(ctx.web_out)
    gate = {"spawn_free_n": len(spawns),
            "lane12_cd": audit2["laneCdUntil"].get("1:2"),
            "enemy_lb": sum(1 for x in audit2["bugs"]
                            if x["side"] == 1 and x["unit"] == "littlebeetle")}
    assert gate == native_gate, \
        f"脚本门禁夹具 native↔Worker 不一致: {gate} vs {native_gate}"
    assert gate["spawn_free_n"] == 1 and gate["enemy_lb"] == 1, \
        f"同 tick 同泳道第二条 sendenemy 未被拒（PBA-12 回归）: {gate}"
    assert gate["lane12_cd"] == 203, \
        f"被拒出生刷新了冷却（until 应保持 203）: {gate}"
    return CaseResult(
        "PASS",
        f"冷却序列+期限边界(前/当/后)+reset 对照+幂等 E_DUP+脚本门禁 "
        f"native↔Worker 全等：{len(buys)} 买事件、spawn_free {gate['spawn_free_n']}、"
        f"laneCd 全等（七字段 reset 对照范围）")


# ── N05 NC-03 世界尺寸与投影样板 ────────────────────────────────────
def _n05_drawn_units(draws):
    """可见存活单位绘制记录（NC-03 字段齐备：px/py/scale/camZ/pos/unit/key）。"""
    return [d for d in draws
            if d.get("unit") and not d.get("culled")
            and d.get("scale") is not None and d.get("camZ") is not None]


def _n05_parity(ctx, d, world, tag):
    """逐字段对照 Python 权威复刻（billboard.py）↔ 页面实测 unitBillboard。"""
    exp_px, exp_py, exp_camz, exp_lam = _unit_billboard(
        ctx.web_out, d["unit"], d["pos"], world)
    for name, got, exp in (("px", d["px"], exp_px), ("py", d["py"], exp_py),
                           ("scale", d["scale"], exp_lam),
                           ("camZ", d["camZ"], exp_camz)):
        assert abs(got - exp) <= 1e-6 * max(1.0, abs(exp)), \
            f"{tag} {d['unit']}#{d['id']} {name}: 页面 {got} vs 复刻 {exp}"
    return exp_lam, exp_camz


_N05_POSE_CACHE = {}


def _n05_expected_pose_width(web_out, unit, clip, frame, yaw_idx):
    """姿态级独立期望宽（模型世界单位）：皮肤 clip 第 frame 帧，按 yaw×45°
    旋转后的网格 x 跨度——直接从模型+动画数据计算，不经烘焙管线。

    screen-x 不受 pitch 影响（pitch 只混合 y/z）→ 旋转网格 x 跨度 = 精灵内容宽。
    静态 clip（bind 共享）用 bind 顶点。按**索引缓冲实际引用的顶点**度量：
    部分 .v3d（如 bee）子网格未全解析、idx 只覆盖部分顶点（formats/v3d.md
    已登记降级）——期望与绘制须同口径（引用集），否则把解析缺口误报为投影错。
    """
    import math
    from bugbits import unitdb
    from bugbits.assets import pose as posemod, van, v3d
    from bugbits.render import bake
    atlas = json.loads((web_out / "atlas.json").read_text(encoding="utf-8"))
    cdef = atlas["clips"][unit][clip]
    key = (unit, clip, frame)
    if key not in _N05_POSE_CACHE:
        spec = unitdb.load_unit(unit)
        rp = bake._resolve_model(spec.model, ".v3d")
        (verts, idx, _k), skin, recs, _tex = v3d.parse_v3d(rp)
        if cdef["kind"] == "static":
            posed = verts
        else:
            ref = spec.anims[clip]
            blocks = van.parse_van(bake._resolve_model(ref, ".van"))
            dur = blocks[0][-1][0]
            n = cdef["frames"]
            posed = posemod.skin_at(skin, posemod.worlds_from_records(recs),
                                    posemod.worlds_at(recs, blocks,
                                                      dur * frame / n))
        used = sorted({i for i in idx if i < len(posed)})
        _N05_POSE_CACHE[key] = [posed[i] for i in used]
    posed = _N05_POSE_CACHE[key]
    a = math.radians(yaw_idx * 45.0)
    ca, sa = math.cos(a), math.sin(a)
    xs = [v[0][0] * ca - v[0][2] * sa for v in posed]
    return max(xs) - min(xs)


def _n05_world_width_check(ctx, d, tag):
    """独立几何验收：内容宽（模型世界单位）≈ 姿态网格旋转 x 跨度。

    期望来自模型+动画原始数据（_n05_expected_pose_width，独立于烘焙管线）；
    实测 = atlas cb 宽 × atlasScale。容差 8%：光栅化取整 + colorkey 边缘。
    """
    atlas = json.loads((ctx.web_out / "atlas.json").read_text(encoding="utf-8"))
    units = json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8"))
    sp = atlas["sprites"][d["key"]]
    content_w_model = sp["cb"][2] * units[d["unit"]]["atlasScale"]
    expect = _n05_expected_pose_width(ctx.web_out, d["unit"], d["clip"],
                                      d["frame"], d["yaw"])
    assert 0.92 * expect <= content_w_model <= 1.08 * expect, \
        (f"{tag} {d['unit']}#{d['id']} {d['clip']}.f{d['frame']}.y{d['yaw']} "
         f"内容宽 {content_w_model:.2f} vs 姿态网格旋转 x 跨度 {expect:.2f}"
         f"（模型世界单位）")


def n05(ctx):
    """NC-03：世界尺寸与投影样板——level_02 三单位 + level_08 飞行高度。

    固定 seed=2026/viewport=1000×720/tick 的可见样板与独立几何验收：
    - level_02（合成夹具 InitialNectar=110，schema 合法字段）：买 ant+bee +
      脚本 littlebeetle（第 3 条命令，每 tick 恰一条 → tick3），tick3 三类型齐绘；
      逐字段复刻一致（px/py/scale/camZ）；
      内容宽 ≈ 旋转 AABB 宽；透视常数 λ·camZ/(asc·sf)=cot·canvas/2 跨深度一致。
    - level_08（world_04 第二世界，无夹具）：脚本 wasp@y=80 + 买 ant——飞行高度
      可见（y=80 投影 py 高于其地面投影 >8px 且 camZ 更小→λ 更大）。
    截图 n05-level02.png / n05-level08.png 存 run_dir（样板前后对照另见
    out/nc03-sample/，由离线脚本对旧包/新包同夹具产出）。
    """
    if ctx.profile != "full":
        raise BlockedError("n05 仅适用 full profile（需 level_08/多世界）")
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    measurements = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # ── 样板 A：level_02（world_02）ant+littlebeetle+bee ──
            page = browser.new_page(viewport={"width": 1000, "height": 720})
            page.on("pageerror", lambda e: errors.append(f"L02 pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"L02 console.{m.type}: {m.text}") if m.type == "error" else None)
            _patch_level(page, ctx.web_out, "level_02",
                         lambda lv: lv["props"].update({"InitialNectar": ["110"]}))
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            _set_camera_and_wait(page, None, ctx, errors, "n05-explicit-overview")
            page.evaluate("document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.buy('ant')")
            page.evaluate("document.getElementById('lane').value = '1'")
            page.evaluate("window.__bb_test.buy('bee')")
            page.evaluate("window.__bb_test.advanceTo(3)")
            page.wait_for_timeout(300)               # 等 rAF 至少一帧
            snap = page.evaluate("window.__bb_test.snapshot()")
            draws = page.evaluate("window.__bb_test.drawLog()")
            drawn = _n05_drawn_units(draws)
            types = {d["unit"] for d in drawn}
            # 三类型齐绘（两个不同体量地面单位 + 一个飞行单位；CPython 探针：tick3 共存）
            assert {"ant", "littlebeetle", "bee"} <= types, \
                f"tick3 三类型未齐绘: {sorted(types)}（夹具买兵前提失败？）"
            mf = json.loads((ctx.web_out / "manifest.json")
                            .read_text(encoding="utf-8"))
            lv = next(l for l in mf["levels"] if l["id"] == "level_02")
            proj = mf["projection"][lv["world"]]
            units_meta = json.loads((ctx.web_out / "units.json")
                                    .read_text(encoding="utf-8"))
            # 逐单位：复刻一致 + 独立几何宽 + 透视常数（跨深度近中远一致性）
            for d in drawn:
                lam, camz = _n05_parity(ctx, d, lv["world"], "L02")
                _n05_world_width_check(ctx, d, "L02")
                asc = units_meta[d["unit"]]["atlasScale"]
                sf = _unit_scale(d["unit"], ctx.web_out)
                k_persp = d["scale"] * d["camZ"] / (asc * sf)
                expect_k = proj["cot"] * 640 / 2.0
                assert abs(k_persp - expect_k) <= 1e-6 * expect_k, \
                    (f"L02 透视常数不一致 {d['unit']}#{d['id']}: "
                     f"{k_persp} vs {expect_k}")
                measurements.append({"level": "level_02", "unit": d["unit"],
                                     "id": d["id"], "pos": d["pos"],
                                     "yaw": d["yaw"], "lam": d["scale"],
                                     "camZ": d["camZ"], "px": d["px"],
                                     "py": d["py"]})
            alive = [b for b in snap["bugs"] if not b["dead"]]
            assert len(alive) >= 3, f"tick1 存活实体 {len(alive)} < 3（前提失败）"
            page.screenshot(path=str(ctx.run_dir / "n05-level02.png"))
            page.close()
            # ── 样板 B：level_08（world_04）wasp@y=80 飞行高度 ──
            page = browser.new_page(viewport={"width": 1000, "height": 720})
            page.on("pageerror", lambda e: errors.append(f"L08 pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"L08 console.{m.type}: {m.text}") if m.type == "error" else None)
            page.goto(f"{url}index.html?test=1&seed={SEED}")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            page.evaluate("window.__bb_test.startGame('level_08', 2026)")
            page.wait_for_function("window.__bb_test && window.__bb_test.ready()",
                                   timeout=60000)
            _set_camera_and_wait(page, None, ctx, errors, "n05-explicit-overview")
            page.evaluate("document.getElementById('lane').value = '0'")
            page.evaluate("window.__bb_test.buy('ant')")     # InitialNectar=12
            page.evaluate("window.__bb_test.advanceTo(1)")
            page.wait_for_timeout(300)
            draws8 = page.evaluate("window.__bb_test.drawLog()")
            drawn8 = _n05_drawn_units(draws8)
            lv8 = next(l for l in mf["levels"] if l["id"] == "level_08")
            types8 = {d["unit"] for d in drawn8}
            assert "wasp" in types8 and "ant" in types8, \
                f"level_08 tick1 未同时绘 wasp(飞行)+ant(地面): {sorted(types8)}"
            wasp = next(d for d in drawn8 if d["unit"] == "wasp")
            assert wasp["pos"][1] > 40, \
                f"wasp 未处飞行高度（FlyHeight=80）: pos={wasp['pos']}"
            for d in drawn8:
                _n05_parity(ctx, d, lv8["world"], "L08")
            # 飞行高度可见：y=80 的投影 py 高于（小于）同点地面投影 >8px，
            # 且 camZ 更小（离相机更近 → λ 更大）
            gpx, gpy, gcamz, glam = _unit_billboard(
                ctx.web_out, "wasp", (wasp["pos"][0], 0.0, wasp["pos"][2]),
                lv8["world"])
            assert wasp["py"] < gpy - 8.0, \
                (f"飞行高度不可见: wasp py={wasp['py']:.1f} "
                 f"vs 地面投影 py={gpy:.1f}")
            assert wasp["camZ"] < gcamz, \
                f"wasp camZ={wasp['camZ']:.1f} 应小于地面 {gcamz:.1f}"
            assert wasp["scale"] > glam, \
                f"wasp λ={wasp['scale']:.4f} 应大于地面 λ={glam:.4f}"
            for d in drawn8:
                measurements.append({"level": "level_08", "unit": d["unit"],
                                     "id": d["id"], "pos": d["pos"],
                                     "yaw": d["yaw"], "lam": d["scale"],
                                     "camZ": d["camZ"], "px": d["px"],
                                     "py": d["py"]})
            page.screenshot(path=str(ctx.run_dir / "n05-level08.png"))
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面/控制台错误: {errors[:5]}"
    (ctx.run_dir / "n05-measurements.json").write_text(
        json.dumps({"seed": SEED, "tick": 3, "viewport": [1000, 720],
                    "units": measurements}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return CaseResult(
        "PASS",
        f"世界尺寸样板：level_02 三类型（ant/littlebeetle/bee）+level_08 "
        f"wasp@y={wasp['pos'][1]:.0f}；{len(measurements)} 单位复刻逐字段一致、"
        f"内容宽≈旋转AABB、透视常数跨深度一致；飞行高度位移 "
        f"{gpy - wasp['py']:.1f}px 可见")


# ── N06 NC-04 DPR 清晰度 ────────────────────────────────────────────
def _n06_edge_band(page, unit, half=12):
    """读画布单位中心水平扫描带（2*half+1 行）原生 backing 像素。

    行带 y ∈ [py−half, py+half] 逻辑坐标（py=公告板中心=bind 中心投影）。NC-03A
    后锚点改瓦片中心，单行 y=py 可能落在轮廓较缓（对角）边缘上致 DPR 判别减弱；
    取整带内**最锐行**（最小 TV/maxΔ）比较，对锚点位置稳健。
    返回 (rows, scale)，rows 为 [[[r,g,b,a], ...], ...]。
    """
    draws = page.evaluate("window.__bb_test.drawLog()")
    d = next(x for x in draws
             if x.get("unit") == unit and not x.get("culled")
             and x.get("px") is not None)
    info = page.evaluate("window.__bb_test.dprInfo()")
    s = info["dprScale"]
    x0 = int(round((d["px"] - 16) * s))
    y0 = int(round((d["py"] - half) * s))
    w = int(round(32 * s))
    h = int(round((2 * half + 1) * s))
    data = page.evaluate(
        "([x, y, w, h]) => { const c = document.getElementById('scene')"
        ".getContext('2d'); const d = c.getImageData(x, y, w, h).data;"
        "  const out = []; for (let i = 0; i < h; i++) { const r = [];"
        "  for (let j = 0; j < w; j++)"
        "  { r.push([d[(i*w+j)*4], d[(i*w+j)*4+1], d[(i*w+j)*4+2], d[(i*w+j)*4+3]]); }"
        "  out.push(r); } return out; }", [x0, y0, w, h])
    return data, s


def _n06_blur(row):
    """行级模糊度（尺度不变）：总变差 / 最大单步跃变。

    硬边（1 px 阶跃）→ 比值≈边缘数；n px 软边 → 每边贡献 TV 不变但 max_step
    ↓n 倍 → 比值↑。上采样（合成器放大）把每边 max_step 减半 → 模糊度≈×2。
    返回 None = 行内无有效边缘（前提失败）。
    """
    def lum(p):
        return 0.30 * p[0] + 0.59 * p[1] + 0.11 * p[2]
    ls = [lum(p) for p in row]
    steps = [abs(ls[i + 1] - ls[i]) for i in range(len(ls) - 1)]
    tv = sum(steps)
    mx = max(steps) if steps else 0.0
    if mx < 8 or tv < 24:
        return None
    return tv / mx


def _n06_min_blur(rows):
    """行带内最小（最锐）有效模糊度；全无效 → None。"""
    blurs = [b for b in (_n06_blur(r) for r in rows) if b is not None]
    return min(blurs) if blurs else None


def n06(ctx):
    """NC-04：DPR 清晰度——backing 随 DPR 缩放，dpr2 显示锐利度优于 dpr1 上采样。

    同一固定场景（level_02 夹具 InitialNectar=110，买 ant+bee，tick=1，与 N05
    同输入）分别在 DPR 1 / DPR 2 页面渲染：
    - dprInfo 断言：DPR1 backing=640/scale=1；DPR2 backing=1280/scale=2（上限 2）。
    - 锐利度度量（独立于截图映射，直接读画布 backing 像素）：取 ant 中心水平
      扫描带（25 行），dpr1 带经 ×2 双线性上采样（模拟合成器在 dpr2 显示屏上的
      放大）后与 dpr2 原生带比较**最锐行的最陡边缘过渡宽度**（中间值像素数）——
      断言 dpr2 过渡更窄（上采样模糊展宽过渡；取整带最锐行对 NC-03A 锚点稳健）。
    - 截图存档（n06-dpr1.png / n06-dpr2.png，固定条件前后对照=锐利度增量）。
    渲染层选择（imageSmoothingQuality=high、DPR 上限 2），非保真声明。
    """
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    bands = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for dpr in (1, 2):
                page = browser.new_page(viewport={"width": 1000, "height": 720},
                                        device_scale_factor=dpr)
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(
                    f"console.{m.type}: {m.text}") if m.type == "error" else None)
                _patch_level(page, ctx.web_out, "level_02",
                             lambda lv: lv["props"].update(
                                 {"InitialNectar": ["110"]}))
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()", timeout=60000)
                page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                _set_camera_and_wait(page, None, ctx, errors, "n06-explicit-overview")
                page.evaluate("document.getElementById('lane').value = '0'")
                page.evaluate("window.__bb_test.buy('ant')")
                page.evaluate("window.__bb_test.advanceTo(1)")
                page.wait_for_timeout(300)
                info = page.evaluate("window.__bb_test.dprInfo()")
                assert info["backing"] == 640 * dpr, \
                    f"DPR={dpr}: backing={info['backing']} != {640 * dpr}"
                assert abs(info["dprScale"] - dpr) < 1e-9, \
                    f"DPR={dpr}: dprScale={info['dprScale']}"
                band, s = _n06_edge_band(page, "ant")
                page.screenshot(path=str(ctx.run_dir / f"n06-dpr{dpr}.png"))
                bands[dpr] = (band, s, info)
                page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面/控制台错误: {errors[:5]}"
    band1, s1, _ = bands[1]
    band2, s2, _ = bands[2]
    assert s1 == 1 and s2 == 2, f"dprScale 异常: {s1}, {s2}"
    # dpr1 各行 ×2 双线性上采样（模拟合成器放大到 dpr2 显示）
    from PIL import Image
    up1 = []
    for row in band1:
        img = Image.new("RGBA", (len(row), 1))
        img.putdata([tuple(px) for px in row])
        u = img.resize((len(row) * 2, 1), resample=Image.BILINEAR)
        up1.append([list(u.getpixel((i, 0))) for i in range(u.size[0])])
    b1 = _n06_min_blur(up1)
    b2 = _n06_min_blur(band2)
    assert b1 is not None and b2 is not None, \
        f"扫描带无有效边缘（前提失败）: blur1={b1} blur2={b2}"
    assert b2 < 0.8 * b1, \
        f"DPR2 最锐行模糊度 {b2:.2f} 未显著优于 DPR1 上采样 {b1:.2f}（清晰度无增益）"
    return CaseResult("PASS",
                      f"backing 640/1280 随 DPR；ant 带最锐行模糊度（TV/maxΔ） "
                      f"dpr1上采样={b1:.2f} > dpr2原生={b2:.2f}（锐利度增益）")


# ── CAM01/CAM02 NC 相机交付：真实页面预设消费链 + 独立投影/操作验收 ────
# 依据 loop-harness-camera-delivery.md §4：研究脚本 Python 镜像只作数值参考，
# 本用例全部经真实 host.js 投影（mapWorld）/点击逆映射（mapClient）/渲染
# （drawLog）路径断言；预期值来自 manifest.cameraPresets + Python 权威
# （render/billboard + render/camera），不复製页面代码。

def _cam_mirror_proj(mf, world):
    """默认投影 closed-form 镜像（A08/C07 同口径）——默认复位断言用。"""
    pr = mf["projection"][world]

    def fwd(x, z):
        dx = x - pr["cx"]; dz = z - pr["cz"]
        cam_z = pr["distance"] + dz * pr["cosP"]
        ndc_x = pr["cot"] * dx / cam_z
        ndc_y = pr["cot"] * (dz * pr["sinP"]) / cam_z
        return ((ndc_x + 1) * 0.5 * pr["size"] * 640 / pr["size"],
                (1 - ndc_y) * 0.5 * pr["size"] * 640 / pr["size"])
    return fwd


def _cam_preset_assertions(web_out, page, world, preset_key, level_id,
                           shot_tag=None, run_dir=None, take_shot=False):
    """单视口内预设消费链断言集（返回摘要 dict）。"""
    from bugbits.render import billboard, camera as cam_mod
    mf = json.loads((web_out / "manifest.json").read_text(encoding="utf-8"))
    ps = mf["cameraPresets"][world][preset_key]
    proj = ps["projection"]
    # bounds 取自默认投影条目（预设投影只含相机几何常数）
    pr0 = mf["projection"][world]
    xmin, xmax = pr0["xmin"], pr0["xmax"]
    zmin, zmax = pr0["zmin"], pr0["zmax"]
    wd = json.loads((web_out / "worlds" / f"{world}.json")
                    .read_text(encoding="utf-8"))
    units_meta = json.loads((web_out / "units.json").read_text(encoding="utf-8"))
    cam = cam_mod.camera_from_spec((xmin, xmax, zmin, zmax), proj["size"],
                                   ps["camera"])
    consts = billboard.cam_consts(proj)

    info = page.evaluate("window.__bb_test.cameraInfo()")
    assert info["activePresetKey"] == preset_key, f"激活预设不符: {info}"
    assert preset_key in info["presets"], f"预设键未登记: {info['presets']}"
    # letterbox 分开断言（aspect=1.6 → 内容区 640×400、offY=120）
    lb = info["letterbox"]
    assert abs(lb["aspect"] - proj["aspect"]) < 1e-12
    assert abs(lb["contentH"] - 640 / proj["aspect"]) < 1e-9, f"contentH: {lb}"
    assert abs(lb["offY"] - (640 - 640 / proj["aspect"]) / 2) < 1e-9, f"offY: {lb}"
    assert info["spritePrefix"] == ps["spritePrefix"], f"前缀不符: {info}"

    # 正映射：已知世界点（两端巢穴 + 地图中心）→ 页面 mapWorld == Python 权威。
    # 近机位预设下地图局部在相机**背后**（cam_z≤0，正逆映射钳位域）——仅对
    # 相机前方点断言正映射+点击逆映射；背后点由截断登记断言覆盖（见下）。
    hives = {s["sideId"]: s["pos"] for s in wd["starts"] if s["index"] == 0}
    pts = {f"hive{k}": (v[0], v[2]) for k, v in hives.items()}
    pts["center"] = ((xmin + xmax) / 2, (zmin + zmax) / 2)
    box = page.evaluate(
        "() => { const c = document.getElementById('scene');"
        " const r = c.getBoundingClientRect();"
        " return {l: r.left, t: r.top, bl: c.clientLeft, bt: c.clientTop,"
        " w: r.width, h: r.height}; }")
    cw = box["w"] - 2 * box["bl"]; ch = box["h"] - 2 * box["bt"]
    page_pts = {}
    for name, (x, z) in pts.items():
        _, _, cam_z = cam.world_to_camera(float(x), 0.0, float(z))
        exp = billboard.project(consts, float(x), 0.0, float(z), 640.0)
        got = page.evaluate("([x, z]) => window.__bb_test.mapWorld(x, z)",
                            [x, z])
        assert abs(got[0] - exp[0]) < 1e-6 * max(1, abs(exp[0])) \
            and abs(got[1] - exp[1]) < 1e-6 * max(1, abs(exp[1])), \
            f"{name}: mapWorld={got} vs 权威=({exp[0]:.6f},{exp[1]:.6f})"
        page_pts[name] = got
        if cam_z <= 1.0:
            continue                     # 相机背后：钳位域，不作逆映射断言
        # 逆映射（CAM-02 边界合同）：投影像素在内容区内 → mapClient 必须命中
        # 且 round-trip ±4（真实点击路径）；在内容区外（如 world_02 wide_cam
        # 我方巢穴投影画布外 py≈852）→ 必须显式 null（黑带/画布外无命中，
        # 旧实现越界反解已被 CAM-02 禁止）。
        in_content = (0 <= got[0] <= 640
                      and lb["offY"] - 0.5 <= got[1]
                      <= lb["offY"] + lb["contentH"] + 0.5)
        px = box["l"] + box["bl"] + got[0] * cw / 640
        py = box["t"] + box["bt"] + got[1] * ch / 640
        hit = page.evaluate("([x, y]) => window.__bb_test.mapClient(x, y)",
                            [px, py])
        if in_content:
            assert hit is not None, \
                f"{name}: 内容区内合法命中被拒 null（py={got[1]:.1f}）"
            wx, wz = hit
            assert abs(wx - x) < 4.0 and abs(wz - z) < 4.0, \
                f"{name}: 点击逆映射 ({wx:.1f},{wz:.1f}) vs ({x:.1f},{z:.1f})"
        else:
            assert hit is None, \
                f"{name}: 内容区外应显式 null（py={got[1]:.1f}）: {hit}"
    # 至少一个前方点完成往返（否则断言集空洞）
    n_front = sum(1 for (x, z) in pts.values()
                  if cam.world_to_camera(float(x), 0.0, float(z))[2] > 1.0)
    assert n_front >= 1, "无相机前方测试点（预设参数异常）"
    # 方向：前方点 py 序与权威一致且差异显著（非平凡）
    front_names = [n for n, (x, z) in pts.items()
                   if cam.world_to_camera(float(x), 0.0, float(z))[2] > 1.0]
    if len(front_names) >= 2:
        pys = sorted(page_pts[n][1] for n in front_names)
        assert pys[-1] - pys[0] > 100, f"前方点 py 差过小: {pys}"
    # letterbox：中心点 py 落在内容区内（offY..offY+contentH）
    cy = page_pts["center"][1]
    assert lb["offY"] - 1 <= cy <= lb["offY"] + lb["contentH"] + 1, \
        f"中心点 py={cy} 出 letterbox 内容区"
    # 截断：metrics.truncatedTargets ↔ 实际出内容区（双向；背后=钳位域算截断）
    for hive_id, (hx, hz) in ((0, pts["hive0"]), (1, pts["hive1"])):
        cam_z = cam.world_to_camera(float(hx), 0.0, float(hz))[2]
        pp = page_pts[f"hive{hive_id}"]
        inside = (cam_z > 1.0 and 0 <= pp[0] <= 640
                  and lb["offY"] <= pp[1] <= lb["offY"] + lb["contentH"])
        listed = f"hive{hive_id}" in ps["metrics"]["truncatedTargets"]
        assert inside != listed, \
            f"hive{hive_id}: 在界={inside} 与 metrics 截断登记={listed} 矛盾"
    # 渲染锚点 + 近远缩放：真实 draw 日志 vs Python 单位公告板镜像
    # 调用方已等待本次预设对应的完成帧；不得用固定时间猜测 drawLog 新鲜度。
    draws = page.evaluate("window.__bb_test.drawLog()")
    bug_draws = [d for d in draws
                 if d.get("key") and not d.get("culled")
                 and d.get("scale") is not None]
    assert bug_draws, "无虫精灵绘制（预设链未消费？）"
    checked = 0
    for d in bug_draws:
        assert d["key"].startswith(ps["spritePrefix"]), \
            f"键未用预设前缀: {d['key']}（资产隔离失败）"
        um = units_meta.get(d["unit"]) or {}
        ws3 = um.get("worldSize") or {"w": 12, "h": 7, "d": 12}
        asc = ps["unitAtlasScale"].get(d["unit"]) or um.get("atlasScale")
        sf = _unit_scale(d["unit"], web_out)
        bb = billboard.unit_billboard(proj, d["pos"],
                                      (ws3["w"], ws3["h"], ws3["d"]), sf,
                                      asc, 640.0)
        assert abs(d["px"] - bb["px"]) < 1e-6 * max(1, abs(bb["px"])), \
            f"{d['unit']} px: {d['px']} vs {bb['px']}"
        assert abs(d["py"] - bb["py"]) < 1e-6 * max(1, abs(bb["py"])), \
            f"{d['unit']} py: {d['py']} vs {bb['py']}"
        assert abs(d["scale"] - bb["lam"]) < 1e-6 * max(1, bb["lam"]), \
            f"{d['unit']} lam: {d['scale']} vs {bb['lam']}"
        # 近远缩放不变量：λ·camZ = asc·sf·cot·640/(2·aspect)（每单位常数）
        expect = asc * sf * proj["cot"] * 640.0 / (2.0 * proj["aspect"])
        assert abs(d["scale"] * d["camZ"] - expect) < 1e-6 * expect, \
            f"{d['unit']} λ·camZ 不变量: {d['scale'] * d['camZ']} vs {expect}"
        checked += 1
    return {"checked_bugs": checked, "pts": page_pts, "letterbox": lb}


def _cam_case(ctx, level_id, world, preset_keys, viewports, shot_tag):
    sync_playwright = _need_playwright()
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    for pk in preset_keys:
        if not mf.get("cameraPresets", {}).get(world, {}).get(pk):
            raise BlockedError(f"manifest.cameraPresets 无 {world}/{pk}"
                               "——需含预设的重建")
    url, srv = _serve(ctx.web_out)
    errors = []
    summary = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for dpr, vp in viewports:
                page = browser.new_page(
                    viewport={"width": vp[0], "height": vp[1]},
                    device_scale_factor=dpr)
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console",
                        lambda m: errors.append(f"console.error: {m.text}")
                        if m.type == "error" else None)
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()",
                    timeout=60000)
                page.evaluate(f"window.__bb_test.startGame({level_id!r}, {SEED})")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                _set_camera_and_wait(page, None, ctx, errors, "_cam_case-explicit-overview")
                page.evaluate(f"window.__bb_test.buy('ant')")
                page.evaluate("window.__bb_test.advanceTo(60)")
                _wait_frame(page, "(rs) => rs.tick >= 60 && rs.tick !== null"
                            f" && rs.generation === {page.evaluate('window.__bb_test.generation()')}",
                            ctx=ctx, tag=f"{shot_tag}-{dpr}-{vp[0]}-start",
                            stage="默认开局目标帧", errors=errors)
                # 默认基线：激活键为空 + mapWorld == 默认投影镜像
                info0 = page.evaluate("window.__bb_test.cameraInfo()")
                assert info0["activePresetKey"] is None, \
                    f"开局激活预设应为空: {info0['activePresetKey']}"
                mf2 = json.loads((ctx.web_out / "manifest.json")
                                 .read_text(encoding="utf-8"))
                fwd0 = _cam_mirror_proj(mf2, world)
                gx, gz = info0["projection"]["cx"], info0["projection"]["cz"]
                got0 = page.evaluate(
                    "([x, z]) => window.__bb_test.mapWorld(x, z)", [gx, gz])
                exp0 = fwd0(gx, gz)
                assert abs(got0[0] - exp0[0]) < 1e-6 and abs(got0[1] - exp0[1]) < 1e-6, \
                    f"默认 mapWorld 与投影常数不符: {got0} vs {exp0}"
                # 逐预设切换（真实异步地形换载）+ 断言 + 复位回默认
                for pk in preset_keys:
                    _set_camera_and_wait(page, pk, ctx, errors,
                                         f"{shot_tag}-{dpr}-{vp[0]}-{pk}")
                    summary[(dpr, vp[0], pk)] = _cam_preset_assertions(
                        ctx.web_out, page, world, pk, level_id)
                    # 复位：null → 默认位（mapWorld 回默认镜像）
                    _set_camera_and_wait(page, None, ctx, errors,
                                         f"{shot_tag}-{dpr}-{vp[0]}-{pk}-reset")
                    got1 = page.evaluate(
                        "([x, z]) => window.__bb_test.mapWorld(x, z)", [gx, gz])
                    assert abs(got1[0] - exp0[0]) < 1e-9 \
                        and abs(got1[1] - exp0[1]) < 1e-9, \
                        f"复位后 mapWorld 未回默认: {got1} vs {exp0}"
                    if dpr == 1 and vp[0] >= 900:
                        _set_camera_and_wait(page, pk, ctx, errors,
                                             f"{shot_tag}-{pk}-shot")
                        _save_backing_png(page, ctx.run_dir / f"{shot_tag}-{pk}-backing-canvas.png")
                        page.locator("#worldstage").screenshot(
                            path=str(ctx.run_dir / f"{shot_tag}-{pk}-stage.png"))
                        page.screenshot(
                            path=str(ctx.run_dir / f"{shot_tag}-{pk}-page.png"))
                        _set_camera_and_wait(page, None, ctx, errors,
                                             f"{shot_tag}-{pk}-shot-reset")
                page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:5]}"
    checked = sum(s["checked_bugs"] for s in summary.values())
    first_lb = next(iter(summary.values()))["letterbox"]
    return CaseResult(
        "PASS",
        f"{len(viewports)} 视口预设链全过：正映射==权威、点击逆映射±4u、"
        f"letterbox {first_lb}"
        f"、截断双向一致、{checked} 虫锚点/λ·camZ 不变量、默认复位逐位回退")


def cam01(ctx):
    """CAM01（slice/world_02）：original_cam+wide_cam 预设消费链（DPR1/2+窄窗）。"""
    return _cam_case(ctx, "level_02", "world_02",
                     ("original_cam", "wide_cam"),
                     ((1, (1000, 760)), (2, (1000, 760)), (1, (420, 700))),
                     "cam01-world02")


def cam02(ctx):
    """CAM02（full/world_03）：original_cam+wide_cam 预设消费链（CAM-03 矩阵扩展：
    低机位 22.9° pitch 差异断言 + 宽/窄视口 × DPR1/2）。

    注：original_cam 目标点为混合状态假设（web_build 参数化采样），不冒称
    原作跟随相机。
    """
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    lv = next(lv for lv in mf["levels"] if lv["id"] == "level_09")
    assert lv["world"] == "world_03", f"level_09 世界不符: {lv}"
    pr_default = mf["projection"]["world_03"]
    pr_preset = mf["cameraPresets"]["world_03"]["original_cam"]["projection"]
    assert abs(pr_preset["sinP"] - pr_default["sinP"]) > 0.1, \
        "world_03 预设 pitch 应显著低于默认 40°（22.9°）"
    return _cam_case(ctx, "level_09", "world_03",
                     ("original_cam", "wide_cam"),
                     ((1, (1000, 760)), (2, (1000, 760)), (1, (420, 700))),
                     "cam02-world03")


# ── CAM-01 预设请求生命周期（latest-intent-wins）──────────────────────
def cam03(ctx):
    """CAM03（CAM-01 真实浏览器回归）：预设请求生命周期 latest-intent-wins。

    Playwright 路由层对预设地形 PNG（original_cam/wide_cam）注入受控延迟与
    abort，经真实页面入口 __bb_test.setCameraPreset 驱动（Node 替身全场景见
    research/nc_camop_preset_lifecycle.cjs；此处验证真实 fetch/decode 入口）：
      ① A→null→A 迟到落地 → 最终 null（mapWorld 回默认闭式）、close 计数 +1
      ② A→B 逆序完成（B 响应先到、A 后到）→ 最终 B、close 计数 +1（A 淘汰）
      ③ 同 key 重入（active=A、在途 B、再选 A）→ 在途 B 落地被淘汰、最终 A
      ④ 跨局（在途请求 + startGame 换代）→ 迟到落地被淘汰不挂载、close +1
      ⑤ route.abort 装载失败 → 先前有效画面保持（投影/像素不变）、返回 false
    逐场景断言 cameraInfo()/mapWorld 实际投影与 resourceState()
    .presetTerrainCloseCount（位图只 close 一次的可观测面）；pageerror 全程
    为空（装载拒绝不得外泄未处理 Promise 拒绝；路由注入的 "Failed to load
    resource" 控制台噪声与 n03 同口径过滤）。
    用 async API + asyncio.sleep 路由延迟（l04 同模式）：同步 API 的
    time.sleep 处理器会阻塞单线程 dispatcher，使“先 A 后 B”的受控逆序
    退化为真实网络时序竞态。
    """
    import asyncio
    from playwright.async_api import async_playwright
    from bugbits.render import billboard
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    world = "world_02"
    presets = mf.get("cameraPresets", {}).get(world, {})
    for pk in ("original_cam", "wide_cam"):
        if pk not in presets:
            raise BlockedError(f"manifest.cameraPresets 无 {world}/{pk}"
                               "——需含预设的重建")
    pr0 = mf["projection"][world]
    center = ((pr0["xmin"] + pr0["xmax"]) / 2, (pr0["zmin"] + pr0["zmax"]) / 2)
    orig_glb = "**/terrain_world_02_original_cam.png"
    wide_glb = "**/terrain_world_02_wide_cam.png"

    def expected(preset_key):
        # 权威正映射镜像（默认/预设同口径：billboard.cam_consts+project）
        proj = presets[preset_key]["projection"] if preset_key else pr0
        consts = billboard.cam_consts(proj)
        return billboard.project(consts, center[0], 0.0, center[1], 640.0)

    url, srv = _serve(ctx.web_out)
    errors = []

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": 1000, "height": 760}, device_scale_factor=1)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(
                f"console.{m.type}: {m.text}") if m.type == "error"
                and "Failed to load resource" not in m.text else None)

            async def fire(key):
                # fire-and-forget：在途请求构造——返回值入页内 stash，场景末
                # 统一 settle（evaluate 立即返回，不等待在途装载）
                delayed = await page.evaluate("window.__cam03NextDecodeDelay > 0")
                previous_decodes = await page.evaluate("window.__cam03DelayedDecoded || 0")
                await page.evaluate(
                    "k => { (window.__cam03 = window.__cam03 || []).push("
                    "window.__bb_test.setCameraPreset(k)); return true; }", key)
                if delayed:
                    await page.wait_for_function("n => (window.__cam03DelayedDecoded || 0) > n",
                                                 arg=previous_decodes, timeout=10000)

            async def settled():
                # 拒绝折叠为 {ok:false}：正确实现应全为 {ok:true,v:false|true}
                await page.evaluate("(window.__cam03ReleaseDecodes || []).splice(0).forEach(release => release())")
                result = await _settle_camera_requests(page, ctx=ctx, errors=errors)
                await page.wait_for_function("(window.__cam03PendingDecode || 0) === 0", timeout=10000)
                return result

            async def apply(key):
                return await _camera_request_async(page, key, ctx=ctx, errors=errors)

            async def active_key():
                return await page.evaluate(
                    "window.__bb_test.cameraInfo().activePresetKey")

            async def close_count():
                return await page.evaluate(
                    "window.__bb_test.resourceState().presetTerrainCloseCount")

            async def check_map(preset_key, tag):
                exp = expected(preset_key)
                got = await page.evaluate(
                    "([x, z]) => window.__bb_test.mapWorld(x, z)",
                    [center[0], center[1]])
                assert abs(got[0] - exp[0]) < 1e-6 * max(1, abs(exp[0])) \
                    and abs(got[1] - exp[1]) < 1e-6 * max(1, abs(exp[1])), \
                    f"{tag}: mapWorld={got} vs 权威=({exp[0]:.6f},{exp[1]:.6f})"

            async def pixels():
                # 画面像素探针（DPR1：backing==逻辑 640）：失败路径前后应一致
                return await page.evaluate("""() => {
                  const c = document.getElementById('scene');
                  const ctx = c.getContext('2d');
                  const pts = [[320, 60], [50, 300], [320, 320], [600, 460],
                               [320, 600], [120, 480], [500, 180], [200, 240]];
                  return pts.map(([x, y]) =>
                    Array.from(ctx.getImageData(x, y, 1, 1).data));
                }""")

            async def delay_route(pattern, seconds):
                # A fetch aborted before decode creates no bitmap. Delay the real
                # decoder's already-created result instead: this preserves the
                # actual late-owned bitmap/close-once regression under cancellation.
                await page.evaluate("""ms => {
                  if (!window.__cam03RealDecode) {
                    window.__cam03RealDecode = window.createImageBitmap;
                    window.createImageBitmap = async (...args) => {
                      const wait=window.__cam03NextDecodeDelay || 0;
                      window.__cam03NextDecodeDelay=0;
                      const bitmap=await window.__cam03RealDecode(...args);
                      if(wait) {
                        window.__cam03DelayedDecoded=(window.__cam03DelayedDecoded||0)+1;
                        window.__cam03PendingDecode=(window.__cam03PendingDecode||0)+1;
                        await new Promise(resolve => {
                          (window.__cam03ReleaseDecodes=window.__cam03ReleaseDecodes||[]).push(resolve);
                        });
                        window.__cam03PendingDecode--;
                      }
                      return bitmap;
                    };
                  }
                  window.__cam03NextDecodeDelay=ms;
                }""", seconds * 1000)
                async def handler(route):
                    await route.continue_()
                await page.route(pattern, handler)
                return handler

            await page.goto(f"{url}index.html?test=1&seed={SEED}")
            await page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            await page.evaluate("window.__bb_test.startGame('level_02', 2026)")
            await page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            assert await active_key() == 'wide_cam', 'production default must also run in test mode'
            assert await apply(None) is True
            initial_closes = await close_count()
            assert initial_closes == 1, 'explicit overview releases the real default bitmap once'
            await check_map(None, "开局默认闭式")

            # ② A→B 逆序完成（B 响应先到、A 后到）→ 最终 B
            await page.evaluate("() => { window.__cam03 = []; return true; }")
            h = await delay_route(orig_glb, 0.9)
            await fire("original_cam")
            await fire("wide_cam")
            await page.wait_for_function(
                "window.__bb_test.cameraInfo().activePresetKey === 'wide_cam'",
                timeout=10000)
            st = await settled()               # 等 A 真正迟到落地（应被淘汰）
            assert await active_key() == "wide_cam", \
                f"逆序完成后应为 wide_cam（后到者覆盖?）: {await active_key()}"
            assert await page.evaluate(
                "window.__bb_test.cameraInfo().projection") \
                == presets["wide_cam"]["projection"], "激活投影应为 wide_cam"
            await check_map("wide_cam", "逆序完成 B")
            assert st == [{"ok": True, "v": False}, {"ok": True, "v": True}], \
                f"A(陈旧)应 false、B(最新)应 true: {st}"
            assert await close_count() == initial_closes + 1, \
                f"B 落地淘汰 A 后计数应 1: {await close_count()}"
            assert await apply(None) is True
            assert await active_key() is None and await close_count() == initial_closes + 2, \
                f"复位后应为默认且释放 B 位图: key={await active_key()}" \
                f" count={await close_count()}"
            await page.unroute(orig_glb, h)

            # ① A→null→A 迟到落地 → 最终 null（不复活）
            await page.evaluate("() => { window.__cam03 = []; return true; }")
            h = await delay_route(orig_glb, 0.9)
            await fire("original_cam")
            assert await apply(None) is True
            assert await active_key() is None, "复位后应为默认"
            st = await settled()               # A 迟到落地（应被淘汰）
            assert await active_key() is None, \
                f"复位后被淘汰的 A 不得复活: {await active_key()}"
            assert st == [{"ok": True, "v": False}], f"复位淘汰应 false: {st}"
            assert await close_count() == initial_closes + 3, \
                f"A 淘汰 close 后计数应 3: {await close_count()}"
            await check_map(None, "复位后默认闭式")
            await page.unroute(orig_glb, h)

            # ③ 同 key 重入：active=A、在途 B、再选 A → B 落地被淘汰、最终 A
            await page.evaluate("() => { window.__cam03 = []; return true; }")
            assert await apply("original_cam") is True
            assert await active_key() == "original_cam" \
                and await close_count() == initial_closes + 3, "首次装载不应 close"
            hw = await delay_route(wide_glb, 0.9)
            await fire("wide_cam")              # 在途 B
            assert await apply("original_cam") is True
            st = await settled()               # B 迟到落地（应被重入淘汰）
            assert await active_key() == "original_cam", \
                f"同 key 重入后应为 original_cam（在途 B 覆盖?）: " \
                f"{await active_key()}"
            assert st == [{"ok": True, "v": False}], f"在途 B 应被淘汰: {st}"
            assert await close_count() == initial_closes + 4, \
                f"B 淘汰 close 后计数应 4（A 原位图不重载不释放）: " \
                f"{await close_count()}"
            await check_map("original_cam", "重入后 A")
            assert await apply(None) is True
            assert await close_count() == initial_closes + 5, \
                f"复位释放 A 位图后应 5: {await close_count()}"
            await page.unroute(wide_glb, hw)

            # ④ 跨局：在途请求 + startGame 换代 → 迟到落地被淘汰不挂载
            await page.evaluate("() => { window.__cam03 = []; return true; }")
            h = await delay_route(orig_glb, 0.9)
            await fire("original_cam")
            await page.evaluate(
                "window.__bb_test.startGame('level_02', 2026); true")
            await page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            assert await active_key() == 'wide_cam', 'new generation must select its own default'
            assert await apply(None) is True
            st = await settled()               # 旧局回包迟到（应被淘汰）
            assert await active_key() is None, \
                f"跨局后不得挂载旧预设: {await active_key()}"
            assert st == [{"ok": True, "v": False}], f"跨局请求应 false: {st}"
            assert await close_count() == initial_closes + 7, \
                f"跨局淘汰 close 后计数应 6: {await close_count()}"
            await check_map(None, "跨局后默认闭式")
            await page.unroute(orig_glb, h)

            # ⑤ route.abort 装载失败 → 先前有效画面保持、返回 false
            await page.evaluate("() => { window.__cam03 = []; return true; }")
            before_frame = await page.evaluate("window.__bb_test.renderState()")
            generation = await page.evaluate("window.__bb_test.generation()")
            tick = await page.evaluate("window.__bb_test.currentTick()")
            assert await apply("original_cam") is True
            assert await active_key() == "original_cam"
            base = await close_count()
            # 等渲染帧落地预设画面（位图挂载与 rAF 绘制不同步）再取像素基线
            baseline_frame = await _wait_frame_async(
                page, _camera_frame_condition(before_frame, "original_cam",
                                               generation, tick),
                ctx=ctx, tag="cam03-before-abort", stage="失败前预设绘制",
                errors=errors)
            stage_before = await page.evaluate(_STAGE_MEASURE)
            _stage_geometry_assert(stage_before, presets["original_cam"]["projection"]["aspect"])
            p1 = await pixels()
            w1 = await page.evaluate(
                "([x, z]) => window.__bb_test.mapWorld(x, z)",
                [center[0], center[1]])

            async def aborted(route):
                await route.abort()
            await page.route(wide_glb, aborted)
            await fire("wide_cam")
            st = await settled()
            assert st == [{"ok": True, "v": False}], \
                f"装载失败应返回 false（非拒绝）: {st}"
            assert await active_key() == "original_cam", \
                f"失败后应保持先前预设: {await active_key()}"
            assert await page.evaluate(
                "window.__bb_test.cameraInfo().projection") \
                == presets["original_cam"]["projection"], "失败后投影应保持"
            assert await close_count() == base, \
                f"失败路径不得释放在位画面: {await close_count()} != {base}"
            w2 = await page.evaluate(
                "([x, z]) => window.__bb_test.mapWorld(x, z)",
                [center[0], center[1]])
            assert w1 == w2, f"失败后 mapWorld 不得漂移: {w1} vs {w2}"
            await _wait_frame_async(
                page, _camera_frame_condition(baseline_frame, "original_cam",
                                               generation, tick),
                ctx=ctx, tag="cam03-after-abort", stage="失败后画面保持",
                errors=errors)
            stage_after = await page.evaluate(_STAGE_MEASURE)
            for rect in ("stage", "canvas"):
                assert stage_after[rect] == stage_before[rect], "failed preset changed stage/canvas geometry"
            assert await pixels() == p1, \
                "失败后画面像素应保持（terrain/projection 无错配）"
            await page.unroute(wide_glb, aborted)
            assert await apply(None) is True
            assert await close_count() == base + 1, \
                "收尾复位应释放 A 位图恰一次"
            # ⑥ The automatic default participates in the same real DOM intent
            # queue. Hold a genuinely decoded bitmap; user overview must cancel
            # it before delivery, keep square stage and close the late owner once.
            before_default_closes = await close_count()
            decoded_before = await page.evaluate("window.__cam03DelayedDecoded || 0")
            default_hold = await delay_route(wide_glb, 1)
            await page.evaluate("window.__bb_test.startGame('level_02',2026);true")
            await page.wait_for_function("n => (window.__cam03DelayedDecoded || 0)>n",
                                         arg=decoded_before, timeout=10000)
            assert await page.evaluate("!document.getElementById('camera-mode').disabled"), \
                "loading default must offer real overview control on its valid world base"
            assert await page.evaluate("window.__bb_test.cameraInfo().pending === true"), \
                "default race fixture must actually hold a pending decoded request"
            control_hit = await page.evaluate("""() => {
              const c=document.getElementById('camera-mode'),r=c.getBoundingClientRect();
              const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
              return !!hit && c.contains(hit);
            }""")
            assert control_hit, "default-loading camera control is obstructed"
            await page.select_option('#camera-mode', 'overview', timeout=1000)
            await page.evaluate("(window.__cam03ReleaseDecodes || []).splice(0).forEach(release=>release())")
            await page.wait_for_function("window.__bb_test.ready() && (window.__cam03PendingDecode||0)===0",timeout=10000)
            await _wait_frame_async(page, 'rs=>rs.presetKey===null && rs.cameraReady',ctx=ctx,tag='cam03-default-dom-overview',errors=errors)
            assert await active_key() is None, "late default revived after real overview intent"
            _stage_geometry_assert(await page.evaluate(_STAGE_MEASURE),1)
            assert await close_count()==before_default_closes+1, "late real default bitmap must close exactly once"
            await page.unroute(wide_glb,default_hold)
            await browser.close()
            return before_default_closes + 1

    try:
        final_count = asyncio.run(run())
    finally:
        srv.shutdown()
    assert not errors, f"页面错误（含未处理拒绝）: {errors[:5]}"
    return CaseResult(
        "PASS",
        f"预设请求生命周期 5 场景（逆序/复位/重入/跨局/失败）全过："
        f"latest-intent-wins，presetTerrainCloseCount 终值 {final_count} 逐场景"
        "一致，mapWorld 逐场景==权威，失败画面保持，无未处理拒绝")


# ── CAM-02 内容区统一绘制/输入边界（letterbox 裁剪 + 显式无命中）────────
def cam04(ctx):
    """Visible stage DOM boundaries + full backing clip with a real straddler.

    Hidden logical padding stays covered precisely by FN01; no offscreen DOM
    skip or direct-handler fallback may count as a real mouse pass.
    """
    import subprocess
    from bugbits.render import billboard
    mf=json.loads((ctx.web_out/'manifest.json').read_text())
    atlas=json.loads((ctx.web_out/'atlas.json').read_text())
    worlds=[('world_02','level_02')]
    if any(l['id']=='level_09' for l in mf['levels']): worlds.append(('world_03','level_09'))
    url,srv=_serve(ctx.web_out)
    errors,summaries=[],[]
    try:
        with _need_playwright()() as p:
            browser=p.chromium.launch(headless=True)
            try:
                for world,level in worlds:
                    wd=json.loads((ctx.web_out/'worlds'/f'{world}.json').read_text())
                    starts={s['index']:s['pos'] for s in wd['starts'] if s['sideId']==0}
                    default=billboard.cam_consts(mf['projection'][world])
                    for dpr,vp in ((1,(1000,760)),(2,(1000,760)),(1,(420,700))):
                        tag=f'{world}-dpr{dpr}-vp{vp[0]}'
                        page=browser.new_page(viewport={'width':vp[0],'height':vp[1]},device_scale_factor=dpr)
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        try:
                            page.goto(url+'index.html?test=1&seed=2026')
                            page.wait_for_function('window.__bb_test && window.__bb_test.booted()',timeout=60000)
                            page.evaluate('l=>window.__bb_test.startGame(l,2026)',level)
                            page.wait_for_function('window.__bb_test.ready()',timeout=60000)
                            _set_camera_and_wait(page,'wide_cam',ctx,errors,tag+'-wide')
                            aspect=mf['cameraPresets'][world]['wide_cam']['projection']['aspect']
                            oy=(640-640/aspect)/2; bottom=640-oy
                            # Preserve actual cross-boundary sprite precondition on world_02.
                            straddler=None
                            if world=='world_02':
                                page.evaluate("document.getElementById('lane').value='0'")
                                for _ in range(4):page.evaluate("window.__bb_test.buy('ant')")
                                for t in range(20,620,20):
                                    page.evaluate('t=>window.__bb_test.advanceTo(t)',t)
                                    _wait_frame(page,f'rs=>rs.tick>={t}',ctx=ctx,tag=tag+f'-scan-{t}',errors=errors)
                                    for d in page.evaluate('window.__bb_test.drawLog()'):
                                        if not d.get('key') or d.get('culled') or d.get('scale') is None:continue
                                        half=atlas['sprites'][d['key']]['h']*d['scale']/2
                                        if d['py']+half>bottom+4 and d['py']-half<bottom-4:
                                            straddler={'tick':t,'unit':d['unit'],'py':d['py'],'half':half};break
                                    if straddler:break
                                assert straddler,'CAM04 no actual cross-clip sprite: pixel premise failed'
                            for key in ('wide_cam','original_cam'):
                                _set_camera_and_wait(page,key,ctx,errors,tag+'-'+key)
                                m=page.evaluate(_STAGE_MEASURE)
                                _stage_geometry_assert(m,aspect)
                                stage=m['stage']
                                # All four stage edges, real DOM coordinates physically in viewport.
                                for px,py in ((stage['l']+stage['w']/2,stage['t']-2),(stage['l']+stage['w']/2,stage['b']+2),(stage['l']-2,stage['t']+stage['h']/2),(stage['r']+2,stage['t']+stage['h']/2)):
                                    assert 0<=px<vp[0] and 0<=py<vp[1],('CAM04 stage edge outside viewport',tag,px,py)
                                    _op_select_real(page,'#lane','1')
                                    assert page.evaluate('p=>window.__bb_test.mapClient(...p)',[px,py]) is None
                                    page.mouse.click(px,py)
                                    assert page.locator('#lane').input_value()=='1',('outside stage DOM changed lane',tag,key,px,py)
                                # Valid selection radius is 200 world units. Derive
                                # candidate worlds and nearest friendly lane from
                                # original world data, never from the DOM answer.
                                consts=billboard.cam_consts(mf['cameraPresets'][world][key]['projection'])
                                candidates=[]
                                for origin in starts.values():
                                    for dx in range(-180,181,20):
                                        for dz in range(-180,181,20):
                                            x,z=origin[0]+dx,origin[2]+dz
                                            distances={lane:(pos[0]-x)**2+(pos[2]-z)**2 for lane,pos in starts.items()}
                                            lane=min(distances,key=distances.get)
                                            e=billboard.project(consts,x,0,z,640)
                                            if distances[lane]<39000 and e[2]>1 and 8<e[0]<632 and oy+8<e[1]<bottom-8:
                                                candidates.append({'world':[x,z],'logical':e[:2],'lane':lane,'d2':distances[lane]})
                                candidates.sort(key=lambda c:abs(c['logical'][0]-320)+abs(c['logical'][1]-320))
                                click_records=[]
                                clicked=0
                                for candidate in candidates:
                                    expected_lane=candidate['lane']
                                    _op_select_real(page,'#lane','0' if expected_lane else '1')
                                    before=page.evaluate(_STAGE_MEASURE)
                                    r=before['stage'];scale=r['w']/640
                                    px=r['l']+candidate['logical'][0]*scale
                                    py=r['t']+(candidate['logical'][1]-oy)*scale
                                    target=page.evaluate('p=>document.elementFromPoint(...p)?.id',[px,py])
                                    if target!='scene':continue
                                    hit=page.evaluate('p=>window.__bb_test.mapClient(...p)',[px,py])
                                    assert hit is not None and abs(hit[0]-candidate['world'][0])<1e-5 and abs(hit[1]-candidate['world'][1])<1e-5,('candidate independent inverse',candidate,hit)
                                    page.mouse.click(px,py)
                                    after=page.evaluate(_STAGE_MEASURE)
                                    status=page.locator('#status').text_content()
                                    observed=page.locator('#lane').input_value()
                                    click_records.append(dict(candidate,client=[px,py],rectBefore=before['stage'],rectAfter=after['stage'],status=status,observed=observed,kind='positive'))
                                    assert observed==str(expected_lane),('visible valid world DOM point missed',tag,key,click_records[-1])
                                    clicked+=1
                                    break
                                if key=='wide_cam':
                                    assert clicked>=1,('CAM04 wide has no real valid visible world click',tag,len(candidates))
                                # original_cam currently has no candidates in this
                                # independently sampled <200u region. Do not invent
                                # a positive click or relax the production radius.
                                if key=='original_cam':
                                    # Clear a stale invalid hint through a real
                                    # independently valid wide world click, not a
                                    # DOM/status assignment or handler invocation.
                                    wide_sample=next(c for g in reversed(summaries)
                                        if g['tag']==tag and g['key']=='wide_cam'
                                        for c in g['clicks'] if c['kind']=='positive')
                                    _set_camera_and_wait(page,'wide_cam',ctx,errors,tag+'-negative-valid-baseline')
                                    _op_select_real(page,'#lane','0' if wide_sample['lane'] else '1')
                                    baseline=page.evaluate(_STAGE_MEASURE)['stage']
                                    scale=baseline['w']/640
                                    px=baseline['l']+wide_sample['logical'][0]*scale
                                    py=baseline['t']+(wide_sample['logical'][1]-oy)*scale
                                    assert page.evaluate('p=>document.elementFromPoint(...p)?.id',[px,py])=='scene'
                                    page.mouse.click(px,py)
                                    assert page.locator('#lane').input_value()==str(wide_sample['lane'])
                                    assert '已选泳道' in page.locator('#status').text_content(), 'fresh valid baseline must come from real DOM listener'
                                    _set_camera_and_wait(page,key,ctx,errors,tag+'-negative-research-return')
                                negatives=0
                                for target_start in [v for v in wd['starts'] if v['sideId']==1]:
                                    x,z=target_start['pos'][0],target_start['pos'][2]
                                    d2=min((pos[0]-x)**2+(pos[2]-z)**2 for pos in starts.values())
                                    e=billboard.project(consts,x,0,z,640)
                                    if d2<40000 or e[2]<=1 or not (8<e[0]<632 and oy+8<e[1]<bottom-8):continue
                                    _op_select_real(page,'#lane','1')
                                    before=page.evaluate(_STAGE_MEASURE)
                                    r=before['stage'];scale=r['w']/640
                                    px=r['l']+e[0]*scale;py=r['t']+(e[1]-oy)*scale
                                    if page.evaluate('p=>document.elementFromPoint(...p)?.id',[px,py])!='scene':continue
                                    hit=page.evaluate('p=>window.__bb_test.mapClient(...p)',[px,py])
                                    assert hit is not None and abs(hit[0]-x)<1e-5 and abs(hit[1]-z)<1e-5,('negative world map remains legal',hit,(x,z))
                                    status_before=page.locator('#status').text_content()
                                    assert '已选泳道' in status_before and '无有效泳道' not in status_before,('negative hint must not be stale',tag,key,status_before)
                                    page.mouse.click(px,py)
                                    after=page.evaluate(_STAGE_MEASURE)
                                    status=page.locator('#status').text_content()
                                    observed=page.locator('#lane').input_value()
                                    click_records.append({'kind':'too-far-negative','world':[x,z],'client':[px,py],'d2':d2,'rectBefore':before['stage'],'rectAfter':after['stage'],'statusBefore':status_before,'statusAfter':status,'observed':observed})
                                    assert observed=='1' and '无有效泳道' in status,('far valid mapped DOM point must reject lane selection',tag,key,click_records[-1])
                                    negatives+=1
                                    break
                                assert negatives>=1,('CAM04 no visible too-far DOM negative',tag,key)
                                shot=ctx.run_dir/f'cam04-{tag}-{key}-backing-canvas.png'
                                _save_backing_png(page,shot)
                                r=subprocess.run([sys.executable,str(ROOT/'research/nc_camop_pixel_probe.py'),str(shot),'--input','backing','--aspect',str(aspect)],capture_output=True,text=True)
                                assert r.returncode==0,(tag,key,r.stdout,r.stderr)
                                summaries.append({'tag':tag,'key':key,'straddler':straddler,'pixel':json.loads(r.stdout),'worldClicks':clicked,'candidateCount':len(candidates),'negativeClicks':negatives,'clicks':click_records})
                            # Production camera control is not a canvas target; actual select
                            # changes exactly its intended camera and preserves lane selection.
                            before=page.locator('#lane').input_value()
                            _camera_select_real(page,'overview',ctx,errors,'camera-dom-overview')
                            _wait_frame(page,'rs=>rs.presetKey===null',ctx=ctx,tag=tag+'-dom-overview',errors=errors)
                            assert page.locator('#lane').input_value()==before
                            box=page.evaluate(_STAGE_MEASURE)['canvas']
                            for lane,pos in sorted(starts.items()):
                                e=billboard.project(default,pos[0],0,pos[2],640)
                                px=box['l']+e[0]*box['w']/640;py=box['t']+e[1]*box['h']/640
                                assert page.evaluate('p=>document.elementFromPoint(...p)?.id',[px,py])=='scene',('overview world point occluded',tag,lane)
                                page.mouse.click(px,py)
                                assert page.locator('#lane').input_value()==str(lane),('overview DOM four-lane regression',tag,lane)
                        finally:page.close()
            finally:browser.close()
    finally:
        srv.shutdown();srv.server_close()
        (ctx.run_dir/'cam04-stage.json').write_text(json.dumps({'originalDynamic':False,'groups':summaries,'errors':errors},ensure_ascii=False,indent=1))
    assert not errors,errors
    return CaseResult('PASS',f'{len(summaries)} stage/preset groups: four outside-edge real DOM no lane change, actual world DOM hit, full backing alpha clip and cross-clip sprite, production overview control/four lanes; function padding tests remain FN01')


# ── CAM-03 操作视口矩阵（双世界×双预设×宽/窄×DPR1/2）──────────────────
def cam05(ctx):
    """CAM05（CAM-03 操作视口矩阵）：world_02+world_03 × original_cam/wide_cam
    × 宽/窄视口 × DPR1/2。

    每组合真实买兵（地面行进=littlebeetle 全程穿泳道；飞行=bee/wildbee 采集
    巡逻——canFly 属性单位，非 y>0 假设）+ advanceTo 扫描确定采样 tick（固定
    seed 确定性，后续视口直接复用），断言：
      - 内容区内同时有地面行进单位与飞行单位（真实样本，非凭空坐标），且
        内容区内 camZ 覆散 ≥1.5（近/远样本；全程近→远轨迹入报告）；
      - 全部内容区内 drawn 虫过 λ·camZ 不变量 + px/py==Python 权威镜像；
      - 巢穴/泳道目标"可见或工程边缘指示补偿"：敌方巢穴必须可见（无补偿
        机制）；我方巢穴与选中泳道出生点不可见时必须有 indicator drawLog
        条目（target 一致 + 钳位几何）——不以"已登记 truncated"结束；
      - 像素探针（DPR1 宽窗）：indicator 实心三角中心像素==纯色 +
        letterbox 黑带纯净；
      - overview 恢复：setCameraPreset(null) → 指示消失 + 我方巢穴回默认
        闭式投影（mapWorld==权威）。
    world_02 两 profile 必需（缺预设=BlockedError）；world_03 需 full 包
    （结果消息显式记录跑没跑，不静默）。
    注：original_cam 目标点为混合状态假设（web_build 参数化采样），不冒称
    原作跟随相机；工程指示为补偿 UI，非原作呈现。
    """
    import subprocess
    sync_playwright = _need_playwright()
    from bugbits.render import billboard
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    units_meta = json.loads((ctx.web_out / "units.json")
                            .read_text(encoding="utf-8"))
    if not mf.get("cameraPresets", {}).get("world_02"):
        raise BlockedError("manifest.cameraPresets 无 world_02——需含预设的重建")
    # (level, world, 飞行单位, 初始买兵[(unit, lane)...], 补买轮 {tick: buys})
    # world_03 补买轮：小甲虫行进至遭遇线即亡（original_cam 可见带恰在遭遇
    # 区），多轮补充保证采样窗口内有地面样本在内容区（实测 t=1000 起满足）。
    worlds = [("level_02", "world_02", "bee",
               [("littlebeetle", 0), ("bee", 1),
                ("littlebeetle", 2), ("bee", 3)], {}),
              ("level_09", "world_03", "wildbee",
               [("littlebeetle", 0), ("wildbee", 1)],
               {300: [("littlebeetle", 0), ("wildbee", 1)],
                500: [("littlebeetle", 0), ("littlebeetle", 1)],
                700: [("littlebeetle", 0), ("littlebeetle", 1)],
                900: [("littlebeetle", 0), ("littlebeetle", 1)]})]
    if not mf.get("cameraPresets", {}).get("world_03"):
        worlds = [worlds[0]]            # slice 包无 world_03：只跑 world_02（结果显式记录）
    url, srv = _serve(ctx.web_out)
    errors = []
    summaries = {}
    pixel_summaries = {}
    PROBE = ROOT / "research/nc_camop_pixel_probe.py"

    def in_content(d, off_y, bottom):
        return off_y <= d["py"] <= bottom and 0 <= d["px"] <= 640

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for level_id, world, fly_unit, buys, rounds in worlds:
                presets = mf["cameraPresets"][world]
                pr_def = mf["projection"][world]
                wd = json.loads((ctx.web_out / "worlds" / f"{world}.json")
                                .read_text(encoding="utf-8"))
                starts0 = {s["index"]: s["pos"]
                           for s in wd["starts"] if s["sideId"] == 0}
                consts_def = billboard.cam_consts(pr_def)
                for pk in ("original_cam", "wide_cam"):
                    ps = presets[pk]
                    proj = ps["projection"]
                    consts = billboard.cam_consts(proj)
                    aspect = proj["aspect"]
                    content_h = 640 / aspect
                    off_y = (640 - content_h) / 2
                    bottom = off_y + content_h
                    t_star, traj = None, []
                    for dpr, vp in ((1, (1000, 760)), (2, (1000, 760)),
                                    (1, (420, 700))):
                        tag = f"{world}:{pk}:dpr{dpr}vp{vp[0]}"
                        page = browser.new_page(
                            viewport={"width": vp[0], "height": vp[1]},
                            device_scale_factor=dpr)
                        page.on("pageerror",
                                lambda e: errors.append(f"pageerror: {e}"))
                        page.on("console", lambda m: errors.append(
                            f"console.{m.type}: {m.text}") if m.type == "error"
                            and "Failed to load resource" not in m.text else None)
                        page.goto(f"{url}index.html?test=1&seed={SEED}")
                        page.wait_for_function(
                            "window.__bb_test && window.__bb_test.booted()",
                            timeout=60000)
                        page.evaluate(
                            f"window.__bb_test.startGame({level_id!r}, 2026)")
                        page.wait_for_function(
                            "window.__bb_test && window.__bb_test.ready()"
                            " && window.__bb_test.renderState().seq >= 1",
                            timeout=60000)
                        # FRAME-01：条件等待替换固定 400ms——预设已绘制
                        seq_p = page.evaluate(
                            "window.__bb_test.renderState().seq")
                        assert page.evaluate(
                            f"window.__bb_test.setCameraPreset({pk!r})") is True
                        _wait_frame(page,
                                    f"(rs) => rs.presetKey === {pk!r}"
                                    f" && rs.seq > {seq_p}",
                                    ctx=ctx, tag=f"cam05-{world}-{pk}-preset",
                                    stage=f"{pk} 挂载后绘制", errors=errors)
                        for unit, lane in buys:
                            page.evaluate(
                                "document.getElementById('lane').value"
                                f" = '{lane}'")
                            page.evaluate(
                                f"window.__bb_test.buy({unit!r})")

                        def drawn_bugs(min_tick):
                            # FRAME-01：条件等待替换固定 60ms——目标 tick 帧
                            # 已绘制后才读 drawLog（drawLog 与帧标记同帧自洽）
                            _wait_frame(
                                page,
                                f"(rs) => rs.tick !== null"
                                f" && rs.tick >= {min_tick}",
                                ctx=ctx, tag=f"cam05-{world}-{pk}-t{min_tick}",
                                stage=f"advanceTo({min_tick}) 后目标帧",
                                errors=errors)
                            return [d for d in page.evaluate(
                                "window.__bb_test.drawLog()")
                                if d.get("key") and not d.get("culled")
                                and d.get("scale") is not None]

                        # 扫描/重放统一：固定 seed 下逐 tick 推进（含二轮补买
                        # 的同一动作序列），首个"地面+飞行同时在内容区且 camZ
                        # 散布≥1.5"的 tick 记为 T*；后续视口重放同一序列到 T*
                        # （确定性复现，不重新扫描）。
                        for t in range(100, (t_star or 2000) + 1, 100):
                            page.evaluate(f"window.__bb_test.advanceTo({t})")
                            for unit, lane in rounds.get(t, []):
                                page.evaluate(
                                    "document.getElementById('lane')"
                                    f".value = '{lane}'")
                                page.evaluate(
                                    f"window.__bb_test.buy({unit!r})")
                            if t_star is not None:
                                if t >= t_star:
                                    break
                                continue
                            bugs = drawn_bugs(t)
                            inc = [d for d in bugs
                                   if in_content(d, off_y, bottom)]
                            if inc:
                                traj.append((t, round(min(
                                    d["camZ"] for d in inc)),
                                    round(max(d["camZ"] for d in inc))))
                            has_ground = any(d["unit"] == "littlebeetle"
                                             for d in inc)
                            has_fly = any(d["unit"] == fly_unit for d in inc)
                            czs = [d["camZ"] for d in inc]
                            if has_ground and has_fly and len(czs) >= 2 \
                                    and max(czs) / min(czs) >= 1.5:
                                t_star = t
                                break
                        assert t_star is not None, \
                            f"{tag}: 100..2000 tick 未找到地面+飞行内容区" \
                            "同时在场且 camZ 散布≥1.5 的采样点"
                        bugs = drawn_bugs(t_star)
                        inc = [d for d in bugs if in_content(d, off_y, bottom)]
                        assert any(d["unit"] == "littlebeetle" for d in inc), \
                            f"{tag}: 内容区无地面行进单位样本"
                        assert any(d["unit"] == fly_unit for d in inc), \
                            f"{tag}: 内容区无飞行单位样本（{fly_unit}）"
                        czs = [d["camZ"] for d in inc]
                        assert max(czs) / min(czs) >= 1.5, \
                            f"{tag}: 内容区 camZ 散布不足: {czs}"
                        # λ·camZ 不变量 + px/py==权威（全部内容区内 drawn 虫）
                        checked = 0
                        for d in inc:
                            assert d["key"].startswith(ps["spritePrefix"]), \
                                f"{tag}: 键未用预设前缀: {d['key']}"
                            um = units_meta.get(d["unit"]) or {}
                            ws3 = um.get("worldSize") or {"w": 12, "h": 7, "d": 12}
                            asc = ps["unitAtlasScale"].get(d["unit"]) \
                                or um.get("atlasScale")
                            sf = _unit_scale(d["unit"], ctx.web_out)
                            bb = billboard.unit_billboard(
                                proj, d["pos"], (ws3["w"], ws3["h"], ws3["d"]),
                                sf, asc, 640.0)
                            assert abs(d["px"] - bb["px"]) \
                                < 1e-6 * max(1, abs(bb["px"])), \
                                f"{tag}: {d['unit']} px {d['px']} vs {bb['px']}"
                            assert abs(d["py"] - bb["py"]) \
                                < 1e-6 * max(1, abs(bb["py"])), \
                                f"{tag}: {d['unit']} py {d['py']} vs {bb['py']}"
                            expect = asc * sf * proj["cot"] * 640.0 \
                                / (2.0 * proj["aspect"])
                            assert abs(d["scale"] * d["camZ"] - expect) \
                                < 1e-6 * expect, \
                                f"{tag}: {d['unit']} λ·camZ 不变量失败"
                            checked += 1
                        # 目标可见或工程补偿（巢穴/泳道）
                        snap = page.evaluate("window.__bb_test.snapshot()")
                        hives = {h["side"]: h for h in snap["hives"]}

                        def indicators():
                            return {d["id"]: d for d in page.evaluate(
                                "window.__bb_test.drawLog()")
                                if d.get("clip") == "indicator"}

                        for side, hive in hives.items():
                            e = billboard.project(consts, hive["pos"][0], 0.0,
                                                  hive["pos"][2], 640.0)
                            visible = (0 <= e[0] <= 640
                                       and off_y <= e[1] <= bottom
                                       and e[2] > 0)
                            if side == 0:
                                ind = indicators().get("indicator:我方巢穴")
                                if visible:
                                    assert ind is None, \
                                        f"{tag}: 我方巢穴可见却画了指示"
                                else:
                                    assert ind is not None, \
                                        f"{tag}: 我方巢穴不可见且无工程指示"
                                    assert ind["target"] == [hive["pos"][0],
                                                             hive["pos"][2]], \
                                        f"{tag}: 指示目标不符: {ind['target']}"
                                    assert 16 <= ind["px"] <= 624 \
                                        and off_y + 18 <= ind["py"] \
                                        <= off_y + content_h - 14, \
                                        f"{tag}: 指示未钳位在内容区内缘: {ind}"
                            else:
                                assert visible, \
                                    f"{tag}: 敌方巢穴不可见（无补偿机制，" \
                                    "预设不可操作）"
                        # 选中泳道出生点：指示跟随（非默认泳道验证）
                        sel_lane = 2 if len(starts0) > 2 else 0
                        page.evaluate(
                            "document.getElementById('lane').value"
                            f" = '{sel_lane}'")
                        # FRAME-01：条件等待替换固定 120ms——选道后的新帧
                        seq_l = page.evaluate(
                            "window.__bb_test.renderState().seq")
                        _wait_frame(page, f"(rs) => rs.seq > {seq_l}",
                                    ctx=ctx, tag=f"cam05-{world}-{pk}-lane",
                                    stage=f"选道 {sel_lane} 后重绘", errors=errors)
                        pos = starts0[sel_lane]
                        e = billboard.project(consts, pos[0], 0.0, pos[2], 640.0)
                        lane_visible = (0 <= e[0] <= 640 and off_y <= e[1] <= bottom
                                        and e[2] > 0)
                        ind = indicators().get(f"indicator:出生·泳道{sel_lane}")
                        if lane_visible:
                            assert ind is None, f"{tag}: 泳道可见却画了指示"
                        else:
                            assert ind is not None, \
                                f"{tag}: 泳道出生点不可见且无工程指示"
                            assert ind["target"] == [pos[0], pos[2]], \
                                f"{tag}: 泳道指示目标不符: {ind['target']}"
                        # 像素探针（DPR1 宽窗）：指示实心三角纯色 + 黑带纯净
                        if dpr == 1 and vp[0] >= 900:
                            shot = ctx.run_dir / f"cam05-{world}-{pk}.png"
                            # World-layer pixel contract, as in CAM04; DOM HUD
                            # composition is covered separately by GUI01/HUD01.
                            _save_backing_png(page, shot)
                            args = [sys.executable, str(PROBE), str(shot),
                                    "--input", "backing", "--aspect", str(aspect)]
                            for d in indicators().values():
                                args += ["--marker",
                                         f"{d['px']:.0f},{d['py']:.0f},"
                                         f"{d['color']}"]
                            r = subprocess.run(args, capture_output=True,
                                               text=True)
                            assert r.returncode == 0, \
                                f"{tag}: 像素探针失败: {r.stdout.strip()}" \
                                f" {r.stderr.strip()}"
                            pixel_summaries[f"{world}-{pk}"] = \
                                json.loads(r.stdout)
                        # overview 恢复：指示消失 + 我方巢穴回默认闭式
                        seq_r = page.evaluate(
                            "window.__bb_test.renderState().seq")
                        assert page.evaluate(
                            "window.__bb_test.setCameraPreset(null)") is True
                        # FRAME-01：条件等待替换固定 200ms——复位帧已绘制
                        _wait_frame(page,
                                    f"(rs) => rs.presetKey === null"
                                    f" && rs.seq > {seq_r}",
                                    ctx=ctx, tag=f"cam05-{world}-{pk}-restore",
                                    stage="overview 恢复后绘制", errors=errors)
                        assert not [d for d in page.evaluate(
                            "window.__bb_test.drawLog()")
                            if d.get("clip") == "indicator"], \
                            f"{tag}: overview 恢复后指示未消失"
                        hive0 = hives[0]
                        e0 = billboard.project(consts_def, hive0["pos"][0], 0.0,
                                               hive0["pos"][2], 640.0)
                        got = page.evaluate(
                            "([x, z]) => window.__bb_test.mapWorld(x, z)",
                            [hive0["pos"][0], hive0["pos"][2]])
                        assert abs(got[0] - e0[0]) < 1e-6 * max(1, abs(e0[0])) \
                            and abs(got[1] - e0[1]) \
                            < 1e-6 * max(1, abs(e0[1])), \
                            f"{tag}: 恢复后我方巢穴未回默认闭式: {got} vs {e0}"
                        summaries[tag] = {
                            "tick": t_star, "checked": checked,
                            "camZ": [round(min(czs)), round(max(czs))],
                            "units": sorted({d["unit"] for d in inc})}
                        page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:5]}"
    parts = []
    for tag, s in summaries.items():
        parts.append(f"{tag} t={s['tick']} 虫{s['checked']}@camZ{s['camZ']}"
                     f" {','.join(s['units'])}")
    traj_span = f"近→远轨迹 camZ {min(t[1] for t in traj)}.." \
                f"{max(t[2] for t in traj)}" if traj else ""
    detail = (f"{len(summaries)} 组合（{'world_02+world_03' if len(worlds) > 1 else 'world_02（slice 包无 world_03）'}）："
              "地面+飞行内容区样本、λ·camZ 不变量、巢穴/泳道可见或工程指示"
              f"（几何+像素）、overview 恢复；{traj_span}；像素探针 "
              f"{len(pixel_summaries)} 张全过")
    return CaseResult("PASS", detail + "；" + "；".join(parts[:6])
                      + ("…" if len(parts) > 6 else ""))


# ── UI-01（2026-09-27 轮）：CSS 逻辑尺寸与 backing 分离 + 首屏操作布局 ──
# 审查基准 ai/bug/2026-09-27-ui-provenance-review.md §UI-01：backing=640×DPR
# 写 canvas 属性 → DPR2 intrinsic 1280 → max-width 钳 ~970（backing 决定 CSS
# 布局）；flex-wrap 下 #side 被事件日志 min-content 挤到换行 → 1000×760 首屏
# 战场与操作栏不可同时使用；#fallback-report 无界（full 实测 1310px）。
# 本用例只读断言布局合同（视口/DPR/resize），操作填充走真实控件。

_UI01_MEASURE = """() => {
  const rectOf = (el) => { const r = el.getBoundingClientRect();
    return {l: +r.left.toFixed(2), t: +r.top.toFixed(2),
            w: +r.width.toFixed(2), h: +r.height.toFixed(2),
            r: +r.right.toFixed(2), b: +r.bottom.toFixed(2)}; };
  const out = {stageGeometry: window.__bb_test.stageGeometry(), vp: {w: innerWidth, h: innerHeight}, dpr: devicePixelRatio,
               els: {}};
  for (const id of ["scene", "worldstage", "side", "buybar", "lane", "pause-btn",
                    "eventlog", "fallback-report", "audio-note"]) {
    const el = document.getElementById(id);
    if (!el) { out.els[id] = null; continue; }
    const cs = getComputedStyle(el);
    const r = rectOf(el);
    const hit = document.elementFromPoint(
      Math.min(Math.max(r.l + r.w / 2, 1), innerWidth - 1),
      Math.min(Math.max(r.t + r.h / 2, 1), innerHeight - 1));
    out.els[id] = {rect: r, hidden: el.hidden,
                   maxHeight: cs.maxHeight, overflowY: cs.overflowY,
                   overflowWrap: cs.overflowWrap, fontSize: cs.fontSize,
                   scrollH: el.scrollHeight, clientH: el.clientHeight,
                   textLen: (el.textContent || "").length,
                   hitAtCenter: hit ? (hit.id || hit.tagName) : null,
                   hitIsSelfOrChild: hit ? el.contains(hit) : false};
  }
  out.buyButtons = Array.from(document.querySelectorAll("button.buy")).map(
    (b) => { const r = rectOf(b); const cs = getComputedStyle(b);
      const hit = document.elementFromPoint(r.l + r.w / 2, r.t + r.h / 2);
      return {unit: b.dataset.unit, rect: r, disabled: b.disabled,
              fontSize: cs.fontSize,
              hitIsSelfOrChild: hit ? b.contains(hit) : false}; });
  out.doc = {scrollW: document.documentElement.scrollWidth,
             clientW: document.documentElement.clientWidth};
  out.body = {scrollW: document.body.scrollWidth,
              clientW: document.body.clientWidth};
  return out;
}"""


def _css_px(v):
    """computed '160px' → 160.0；'none'/空 → None。"""
    if v is None or v == "none" or v == "":
        return None
    try:
        return float(str(v).replace("px", ""))
    except ValueError:
        return None


def _ui01_assert_group(tag, m, vp):
    """单视口组合同断言（测量值 m 来自 _UI01_MEASURE；vp=(w,h)）。"""
    els = m["els"]
    for need in ("scene", "worldstage", "side", "buybar", "lane", "pause-btn", "eventlog",
                 "fallback-report", "audio-note"):
        assert els.get(need), f"[{tag}] #{need} 缺失"
    scene = els["scene"]
    stage = els["worldstage"]
    aspect = m["stageGeometry"]["aspect"]
    assert abs(scene["rect"]["w"]-scene["rect"]["h"])<=.55, f"[{tag}] canvas is not square"
    assert abs(scene["rect"]["w"]-stage["rect"]["w"])<=.55, f"[{tag}] canvas/stage scales differ"
    assert abs(stage["rect"]["h"]-stage["rect"]["w"]/aspect)<=.55, f"[{tag}] independent stage width/aspect failed"
    assert stage["rect"]["l"]>=0 and stage["rect"]["r"]<=m["doc"]["clientW"]+.5, f"[{tag}] stage horizontal overflow"
    assert stage["rect"]["t"]>=0 and stage["rect"]["b"]<=vp[1], f"[{tag}] visible stage outside first screen: {stage}"
    # 3) 操作控件首屏完整可见 + 中心命中自身（无遮挡）+ 未被整体缩小
    for name in ("buybar", "lane", "pause-btn"):
        e = els[name]
        r = e["rect"]
        assert r["t"] >= 0 and r["b"] <= vp[1] and r["l"] >= 0 \
            and r["r"] <= vp[0], \
            f"[{tag}] #{name} 不在首屏: {r}（视口 {vp}）"
        assert e["hitIsSelfOrChild"], \
            f"[{tag}] #{name} 中心命中 {e['hitAtCenter']}（被遮挡）"
    assert m["buyButtons"], f"[{tag}] 无买兵按钮"
    for b in m["buyButtons"]:
        r = b["rect"]
        assert r["t"] >= 0 and r["b"] <= vp[1] and r["l"] >= 0 \
            and r["r"] <= vp[0], \
            f"[{tag}] 买兵按钮 {b['unit']} 不在首屏: {r}"
        assert b["hitIsSelfOrChild"], \
            f"[{tag}] 买兵按钮 {b['unit']} 被遮挡"
        assert r["w"] >= 88 and r["h"] >= 88, \
            f"[{tag}] 买兵按钮 {b['unit']} 被缩小: {r}（禁止整体缩小塞截图）"
    for name in ("lane", "pause-btn"):
        fs = _css_px(els[name]["fontSize"])
        assert fs is not None and fs >= 12, \
            f"[{tag}] #{name} 字号 {els[name]['fontSize']} 不可读"
    # 4) 无横向溢出（容差 0）
    assert m["doc"]["scrollW"] <= m["doc"]["clientW"], \
        f"[{tag}] 文档横向溢出: scrollW={m['doc']['scrollW']}" \
        f" > clientW={m['doc']['clientW']}"
    assert m["body"]["scrollW"] <= m["body"]["clientW"], \
        f"[{tag}] body 横向溢出: {m['body']}"
    # 5) 诊断区有界：max-height + overflow + 长词可断行（不删内容——textLen>0）
    log, fb, an = els["eventlog"], els["fallback-report"], els["audio-note"]
    for name, e, hcap in (("eventlog", log, 200), ("fallback-report", fb, 300),
                          ("audio-note", an, 120)):
        mh = _css_px(e["maxHeight"])
        assert mh is not None and mh <= hcap, \
            f"[{tag}] #{name} 无界: maxHeight={e['maxHeight']}"
        assert e["overflowY"] in ("auto", "scroll"), \
            f"[{tag}] #{name} overflowY={e['overflowY']}（不可独立滚动）"
        assert e["overflowWrap"] in ("anywhere", "break-word"), \
            f"[{tag}] #{name} overflowWrap={e['overflowWrap']}" \
            "（长诊断词决定 min-content 宽度）"
        assert e["scrollH"] >= e["clientH"], f"[{tag}] #{name} 度量异常"
    assert log["textLen"] > 0, f"[{tag}] 事件日志内容被清空"
    assert fb["textLen"] > 0, f"[{tag}] 缺图回退报告内容被清空"
    assert fb["clientH"] <= 300, f"[{tag}] 回退报告实际高度 {fb['clientH']}"
    # Approved 1000px production layout may place controls below the 800x500
    # stage; first-screen/control hit assertions above remain mandatory.
    if vp[0] >= 900:
        side = els["side"]
        assert side["rect"]["w"] <= 360, f"[{tag}] 侧栏超宽: {side['rect']}"


def _ui01_measure_now(page):
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(60)
    m = page.evaluate(_UI01_MEASURE)
    m["scrollY"] = page.evaluate("window.scrollY")
    return m


def _gui_asset_contract(page):
    """Independent original-reference structure, not pixel identity or DYNAMIC."""
    info = page.evaluate("""() => {
      const scene=document.getElementById('worldstage').getBoundingClientRect();
      const buttons=[...document.querySelectorAll('button.buy')];
      return {scene:{l:scene.left,t:scene.top,r:scene.right,b:scene.bottom},
        cards:buttons.map(b => { const r=b.getBoundingClientRect();
          const bar=b.querySelector('.buy-price-bar');
          return {x:r.x,y:r.y,w:r.width,h:r.height,
            priceParent:!!(bar && bar.querySelector('.price')),
            barTexture:bar?getComputedStyle(bar).backgroundImage:''}; }),
        top:getComputedStyle(document.getElementById('hud')).backgroundImage};
    }""")
    assert info["cards"], "original GUI contract: no buy cards"
    for card in info["cards"]:
        assert card["priceParent"] and "maingui_bar.png" in card["barTexture"], \
            "original STATIC: price must belong to the original maingui_bar container"
    assert "maingui_top.png" in info["top"], \
        "original DATA: top HUD texture is exported but unused"
    if page.viewport_size["width"] >= 900:
        s = info["scene"]
        cards = info["cards"]
        assert all(s["l"] <= c["x"] and c["x"] + c["w"] <= s["r"]
                   and s["t"] <= c["y"] and c["y"] + c["h"] <= s["b"]
                   for c in cards), "official reference: buy cards overlay the battlefield"
        assert all(abs(c["x"] - cards[0]["x"]) < 1 for c in cards), \
            "official reference: buy cards form a left vertical rail"
        assert all(b["y"] >= a["y"] + a["h"] + 22 for a, b in zip(cards, cards[1:])), \
            "official reference: cards must not overlap"
    if page.evaluate("window.__bb_test.levelId() === 'level_02' && window.__bb_test.currentTick() === 0"):
        assert page.locator("#hud-mine").text_content() == "100%"
        assert page.locator("#hud-enemy").text_content() == "30%", \
            "STATIC HP/10: initial enemy HP3 must show 30%, not HP/initialSize=100%"
    return info


def gui01(ctx):
    """Original GUI assets and parentage; engineering adaptation, not DYNAMIC."""
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for vp in ((1000, 760), (420, 700)):
                    page = browser.new_page(viewport={"width":vp[0], "height":vp[1]})
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(url + "index.html?test=1&seed=2026")
                    page.wait_for_function("window.__bb_test && window.__bb_test.booted()", timeout=60000)
                    page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                    info = _gui_asset_contract(page)
                    info['topVisiblePixels'] = _gui_top_pixels(page, ctx.web_out, ctx.run_dir, str(vp[0]))
                    (ctx.run_dir / f"gui01-{vp[0]}.json").write_text(json.dumps(info, indent=2))
                    page.screenshot(path=str(ctx.run_dir / f"gui01-{vp[0]}.png"))
                    page.close()
            finally:
                browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    assert not errors, errors
    return CaseResult("PASS", "原GUI bar价格父链、top素材、宽窗战场左竖列；窄窗工程适配；不等于原作DYNAMIC")


def ui01(ctx):
    """UI-01：CSS 逻辑尺寸与 backing 分离 + 响应式首屏操作布局。

    4 组视口（1000×760/420×700 × DPR1/2）逐组断言（不合并称全矩阵）：
    canvas CSS 盒=逻辑 640（宽视口）或等比缩进（窄视口）、DPR 不改变布局
    （跨组 rect 全等）、战场+买兵+选道+暂停首屏完整可见可点无遮挡、无横向
    溢出（容差 0）、诊断区（eventlog/fallback-report/audio-note）有界可独立
    滚动且长词不断行决定 min-content、买兵按钮未被整体缩小。另加同页
    resize 往返（1000×760 ↔ 420×700）。相机完整性：logical=640 + 默认投影
    常数==manifest + overview 正映射==闭式镜像（禁止偷改 FOV/预设修布局）。
    """
    sync_playwright = _need_playwright()
    from bugbits.render import billboard
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    pr = mf["cameraPresets"]["world_02"]["wide_cam"]["projection"]
    fwd0 = lambda x,z: billboard.project(billboard.cam_consts(pr), x, 0, z, 640)[:2]
    url, srv = _serve(ctx.web_out)
    errors = []
    groups = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for dpr, vp in ((1, (1000, 760)), (2, (1000, 760)),
                            (1, (420, 700)), (2, (420, 700))):
                tag = f"dpr{dpr}-vp{vp[0]}x{vp[1]}"
                page = browser.new_page(
                    viewport={"width": vp[0], "height": vp[1]},
                    device_scale_factor=dpr)
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(
                    f"console.{m.type}: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()",
                    timeout=60000)
                page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                # 诊断填充：真实控件买兵（4 泳道 buy_ok + 同泳道复购 E_CD）+
                # 推进（脚本事件）→ 事件日志有长 JSON 行、回退报告有内容
                for lane in ("0", "1", "2", "3"):
                    page.select_option("#lane", lane)
                    page.click("#buy-ant", timeout=10000)
                    page.wait_for_timeout(60)
                for lane in ("0", "1"):
                    page.select_option("#lane", lane)
                    page.click("#buy-ant", timeout=10000)
                    page.wait_for_timeout(60)
                page.evaluate("window.__bb_test.advanceTo(200)")
                page.wait_for_timeout(300)
                m = _ui01_measure_now(page)
                _ui01_assert_group(tag, m, vp)
                assert m["scrollY"] == 0, f"[{tag}] 测量时页面被滚动: {m['scrollY']}"
                # 相机完整性（禁止偷改 FOV/预设参数修布局）
                di = page.evaluate("window.__bb_test.dprInfo()")
                assert di["logical"] == 640, f"[{tag}] 逻辑尺寸被改: {di}"
                ci = page.evaluate("window.__bb_test.cameraInfo()")
                assert ci["activePresetKey"] == "wide_cam", f"[{tag}] 默认预设被改"
                for k in ("cx", "cz", "cot", "sinP", "cosP", "distance", "size", "aspect"):
                    assert abs(ci["projection"][k] - pr[k]) < 1e-12, \
                        f"[{tag}] 投影常数 {k} 被改: {ci['projection'][k]} vs {pr[k]}"
                got = page.evaluate(
                    "([x, z]) => window.__bb_test.mapWorld(x, z)",
                    [pr["cx"], pr["cz"]])
                exp = fwd0(pr["cx"], pr["cz"])
                assert abs(got[0] - exp[0]) < 1e-6 and abs(got[1] - exp[1]) < 1e-6, \
                    f"[{tag}] overview 默认正映射偏离闭式: {got} vs {exp}"
                page.screenshot(path=str(ctx.run_dir / f"ui01-{tag}.png"))
                (ctx.run_dir / f"ui01-{tag}.json").write_text(
                    json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
                groups[tag] = m
                if dpr == 1 and vp == (1000, 760):
                    # 同页 resize 往返：宽 ↔ 窄 ↔ 宽（合同在两态都成立）
                    page.set_viewport_size({"width": 420, "height": 700})
                    m2 = _ui01_measure_now(page)
                    _ui01_assert_group(tag + "-resize-narrow", m2, (420, 700))
                    assert m2["els"]["scene"]["rect"]["w"] < m["els"]["scene"]["rect"]["w"], \
                        "resize 窄态 canvas 未缩进容器"
                    page.set_viewport_size({"width": 1000, "height": 760})
                    m3 = _ui01_measure_now(page)
                    _ui01_assert_group(tag + "-resize-back", m3, (1000, 760))
                    assert abs(m3["els"]["scene"]["rect"]["w"] - m["els"]["scene"]["rect"]["w"]) <= 1, \
                        "resize 回宽态 canvas 未恢复原CSS宽度"
                    groups[tag + "-resize-narrow"] = m2
                    groups[tag + "-resize-back"] = m3
                page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:5]}"
    # DPR 无关：同视口 DPR1/DPR2 布局盒全等（canvas/侧栏/买兵栏/选道/暂停）
    for vp in ((1000, 760), (420, 700)):
        a = groups[f"dpr1-vp{vp[0]}x{vp[1]}"]
        b = groups[f"dpr2-vp{vp[0]}x{vp[1]}"]
        for name in ("scene", "side", "buybar", "lane", "pause-btn"):
            ra, rb = a["els"][name]["rect"], b["els"][name]["rect"]
            for k in ("l", "t", "w", "h"):
                assert abs(ra[k] - rb[k]) <= 0.5, \
                    f"vp{vp[0]} #{name}.{k} 随 DPR 变化: {ra[k]} vs {rb[k]}"
    lines = []
    for tag, m in groups.items():
        sc, bb = m["els"]["scene"], m["els"]["buybar"]
        lines.append(f"{tag}: scene={sc['rect']['w']:.0f}×{sc['rect']['h']:.0f}"
                     f"@y{sc['rect']['t']:.0f} buybar@y{bb['rect']['t']:.0f}"
                     f" hOverflow={m['doc']['scrollW'] - m['doc']['clientW']}"
                     f" fbH={m['els']['fallback-report']['clientH']}")
    return CaseResult("PASS", f"{len(groups)} 组视口/往返逐组合同全过"
                      f"（DPR1/2 布局全等）；" + "；".join(lines))


# ── UI-02（2026-09-27 轮）：真实 DOM 操作闭环 + 函数级边界拆分 ──────────

def _op_click_real(page, selector, timeout=8000):
    """UI-02：真实控件点击——命中元素与可见可操作性一起断言后再点。

    先滚入视野（可滚动容器如 62 关列表属合法 UX；首屏合同由 UI01 单独
    断言），然后断言：元素存在、非零尺寸、完整在视口内、中心命中自身
    （无遮挡）、非禁用；最后 page.click（playwright 自身还做
    actionability/hit-target 复核）。不用 force、不直接调 handler。
    """
    page.evaluate(
        "(sel) => { const el = document.querySelector(sel);"
        " if (el) { el.scrollIntoView({block: 'center'}); } }", selector)
    box = page.evaluate(
        """(sel) => { const el = document.querySelector(sel);
        if (!el) { return null; }
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(
          Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1),
          Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 1));
        return {l: r.left, t: r.top, w: r.width, h: r.height,
                vw: innerWidth, vh: innerHeight,
                hitOk: hit ? el.contains(hit) : false,
                hitTag: hit ? (hit.id || hit.tagName) : null,
                disabled: el.disabled === true}; }""", selector)
    assert box, f"{selector} 不存在"
    assert box["w"] > 0 and box["h"] > 0, f"{selector} 不可见: {box}"
    assert box["l"] >= 0 and box["t"] >= 0 \
        and box["l"] + box["w"] <= box["vw"] + 0.5 \
        and box["t"] + box["h"] <= box["vh"] + 0.5, \
        f"{selector} 不在视口内: {box}"
    assert box["hitOk"], f"{selector} 中心命中 {box['hitTag']}（被遮挡）"
    assert not box["disabled"], f"{selector} 处于禁用态（不应可点）"
    page.click(selector, timeout=timeout)


def _op_select_real(page, selector, value):
    """UI-02：真实选道（select 控件；不直接设 value）。"""
    page.select_option(selector, value)
    got = page.evaluate(
        "(sel) => document.querySelector(sel).value", selector)
    assert got == value, f"{selector} 选值失败: {got!r} != {value!r}"


def _camera_select_real(page, value, ctx, errors, tag):
    """Real DOM request; camera select publishes value only after async commit."""
    page.locator('#camera-mode').scroll_into_view_if_needed()
    hit=page.locator('#camera-mode').evaluate("""el=>{const r=el.getBoundingClientRect();
      const h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
      return {ok:!!h&&el.contains(h),disabled:el.disabled};}""")
    assert hit['ok'] and not hit['disabled'],('camera control inaccessible',hit)
    before=page.evaluate('window.__bb_test.renderState()')
    generation=page.evaluate('window.__bb_test.generation()')
    key=None if value=='overview' else value
    page.select_option('#camera-mode',value)
    _wait_frame(page,_camera_frame_condition(before,key,generation,page.evaluate('window.__bb_test.currentTick()')),
                ctx=ctx,tag=tag,errors=errors)
    assert page.locator('#camera-mode').input_value()==value,('camera option not committed',value)


def fn01(ctx):
    """FN01（UI-02 §1/§8）：canvasClickAt/mapClient **函数级**输入边界。

    与 CAM04 的 DOM 鼠标路径拆开（ai/bug/2026-09-27 §UI-02）：本用例只经
    __bb_test.canvasClickAt / mapClient（同一 onCanvasClick/canvasToWorld，
    仅绕过事件派发），逐坐标独立准备状态（真实 select 控件置已知泳道）与
    独立断言——**明确标注：不等于 DOM 验证**（DOM 路径见 CAM04/UI02）。
    受控变异负例（移除 canvas 监听/遮挡买兵按钮）不影响本用例（函数级
    不经事件派发与按钮命中）——变异红端见 out/nc-uigate/evidence/UI-02/。
    覆盖（world_02 wide_cam，DPR2）：黑带/边界外**含精确 1px 边界坐标
    (320,119/521)**（函数路径无事件坐标量化——DOM 物理路径对该坐标的
    限制见 CAM04 注释）显式无命中且不改道；画布内容框外 null；预设内
    合法命中 round-trip ±4；复位后默认相机四泳道函数级正向命中全中。
    full 追加 world_03 wide_cam 历史反例坐标（函数级）。
    """
    sync_playwright = _need_playwright()
    from bugbits.render import billboard
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    world = "world_02"
    presets = mf.get("cameraPresets", {}).get(world, {})
    for pk in ("original_cam", "wide_cam"):
        if pk not in presets:
            raise BlockedError(f"manifest.cameraPresets 无 {world}/{pk}"
                               "——需含预设的重建")
    aspect = presets["wide_cam"]["projection"]["aspect"]
    content_h = 640 / aspect
    off_y = (640 - content_h) / 2
    bottom = off_y + content_h
    pr = mf["projection"][world]
    wd = json.loads((ctx.web_out / "worlds" / f"{world}.json")
                    .read_text(encoding="utf-8"))
    starts0 = {s["index"]: s["pos"] for s in wd["starts"] if s["sideId"] == 0}
    starts1 = {s["index"]: s["pos"] for s in wd["starts"] if s["sideId"] == 1}
    consts_def = billboard.cam_consts(pr)
    consts_wide = billboard.cam_consts(presets["wide_cam"]["projection"])
    w03_presets = mf.get("cameraPresets", {}).get("world_03", {})
    w03_level = next((l for l in mf["levels"] if l["world"] == "world_03"), None)
    url, srv = _serve(ctx.web_out)
    errors = []
    NO_LANE = "无有效泳道"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def fn_page(level_id, vp=(1000, 760), dpr=2):
                page = browser.new_page(viewport={"width": vp[0],
                                                  "height": vp[1]},
                                        device_scale_factor=dpr)
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(
                    f"console.{m.type}: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()", timeout=60000)
                page.evaluate(f"window.__bb_test.startGame({level_id!r}, 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                page.evaluate("window.__bb_test.advanceTo(1)")
                return page

            def scene_box(page):
                page.evaluate("document.getElementById('worldstage')"
                              ".scrollIntoView({block: 'center'})")
                return page.evaluate(
                    "() => { const c = document.getElementById('scene');"
                    " const r = c.getBoundingClientRect();"
                    " return {l: r.left, t: r.top, w: r.width, h: r.height,"
                    " bl: c.clientLeft, bt: c.clientTop}; }")

            # ── world_02（两 profile 必需）──
            page = fn_page("level_02")
            seq0 = page.evaluate("window.__bb_test.renderState().seq")
            assert page.evaluate(
                "window.__bb_test.setCameraPreset('wide_cam')") is True
            _wait_frame(page,
                        f"(rs) => rs.presetKey === 'wide_cam' && rs.seq > {seq0}",
                        ctx=ctx, tag="fn01-wide", stage="wide_cam 绘制",
                        errors=errors)
            box = scene_box(page)
            cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]

            def css(lx, ly):
                return (box["l"] + box["bl"] + lx * cw / 640,
                        box["t"] + box["bt"] + ly * ch / 640)

            # 函数级负例：黑带/边界外/历史反例坐标 → 不改道 + 提示（逐坐标
            # 独立准备/断言；canvasClickAt 只调处理器，不经事件派发）。
            # select_option 会按需滚动页面 → 每次调用前重测画布盒。
            for ly in (60, 119, 521, 560, 600, 639):
                _op_select_real(page, "#lane", "1")
                box = scene_box(page)
                cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
                page.evaluate("([x, y]) => window.__bb_test.canvasClickAt(x, y)",
                              [box["l"] + box["bl"] + 320 * cw / 640,
                               box["t"] + box["bt"] + ly * ch / 640])
                lane = page.evaluate("window.__bb_test.lane()")
                status = page.evaluate(
                    "document.getElementById('status').textContent")
                assert lane == "1", \
                    f"[fn] 黑带 y={ly} 函数级点击改泳道: {lane}"
                assert NO_LANE in status, f"[fn] 黑带 y={ly} 函数级无提示"
            box = scene_box(page)
            cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
            # mapClient 同坐标显式 null + 画布内容框外 null（逆映射函数面）
            for lx, ly in ((320, 60), (320, 119), (320, 521), (320, 560),
                           (320, 600), (320, 639)):
                hit = page.evaluate("([x, y]) => window.__bb_test.mapClient(x, y)",
                                    list(css(lx, ly)))
                assert hit is None, f"[fn] mapClient({lx},{ly}) 应 null: {hit}"
            for ox, oy in ((box["l"] - 8, box["t"] + ch / 2),
                           (box["l"] + box["w"] + 8, box["t"] + ch / 2)):
                hit = page.evaluate("([x, y]) => window.__bb_test.mapClient(x, y)",
                                    [ox, oy])
                assert hit is None, \
                    f"[fn] mapClient 画布外({ox:.0f},{oy:.0f}) 应 null: {hit}"
            # 预设内合法命中 round-trip（side1 出生点在内容区内）
            checked = 0
            for lane, pos in starts1.items():
                e = billboard.project(consts_wide, pos[0], 0.0, pos[2], 640.0)
                if not (off_y + 1 <= e[1] <= bottom - 1):
                    continue
                hit = page.evaluate("([x, y]) => window.__bb_test.mapClient(x, y)",
                                    list(css(e[0], e[1])))
                assert hit is not None and abs(hit[0] - pos[0]) < 4.0 \
                    and abs(hit[1] - pos[2]) < 4.0, \
                    f"[fn] 合法命中 round-trip 失败: {hit} vs {pos}"
                checked += 1
            assert checked >= 1, "[fn] 无内容区内合法预设测试点"
            # 复位默认 → 四泳道函数级正向命中（C07 合同的函数面）
            seq1 = page.evaluate("window.__bb_test.renderState().seq")
            assert page.evaluate(
                "window.__bb_test.setCameraPreset(null)") is True
            _wait_frame(page,
                        f"(rs) => rs.presetKey === null && rs.seq > {seq1}",
                        ctx=ctx, tag="fn01-reset", stage="复位默认后绘制",
                        errors=errors)
            box = scene_box(page)
            cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
            for lane, pos in sorted(starts0.items()):
                _op_select_real(page, "#lane", "0" if lane != 0 else "1")
                box = scene_box(page)
                cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
                e = billboard.project(consts_def, pos[0], 0.0, pos[2], 640.0)
                page.evaluate("([x, y]) => window.__bb_test.canvasClickAt(x, y)",
                              [box["l"] + box["bl"] + e[0] * cw / 640,
                               box["t"] + box["bt"] + e[1] * ch / 640])
                got = page.evaluate("window.__bb_test.lane()")
                assert got == str(lane), \
                    f"[fn] 默认相机函数级点击泳道 {lane} 落到 {got}"
            page.close()

            # ── full：world_03 wide_cam 历史反例坐标（函数级）──
            w03_ran = False
            if w03_presets.get("wide_cam") and w03_level:
                w03_ran = True
                page = fn_page(w03_level["id"], dpr=1)
                seq0 = page.evaluate("window.__bb_test.renderState().seq")
                assert page.evaluate(
                    "window.__bb_test.setCameraPreset('wide_cam')") is True
                _wait_frame(page,
                            f"(rs) => rs.presetKey === 'wide_cam'"
                            f" && rs.seq > {seq0}",
                            ctx=ctx, tag="fn01-w03-wide",
                            stage="w03 wide_cam 绘制", errors=errors)
                box = scene_box(page)
                cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
                for ly in (60, 560, 600, 639):
                    _op_select_real(page, "#lane", "1")
                    box = scene_box(page)
                    cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
                    page.evaluate(
                        "([x, y]) => window.__bb_test.canvasClickAt(x, y)",
                        [box["l"] + box["bl"] + 320 * cw / 640,
                         box["t"] + box["bt"] + ly * ch / 640])
                    lane = page.evaluate("window.__bb_test.lane()")
                    status = page.evaluate(
                        "document.getElementById('status').textContent")
                    assert lane == "1", \
                        f"[fn-w03] 黑带 y={ly} 函数级点击改泳道: {lane}"
                    assert NO_LANE in status, f"[fn-w03] 黑带 y={ly} 无提示"
                for ly in (60, 600):
                    box = scene_box(page)
                    cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
                    hit = page.evaluate(
                        "([x, y]) => window.__bb_test.mapClient(x, y)",
                        [box["l"] + box["bl"] + 320 * cw / 640,
                         box["t"] + box["bt"] + ly * ch / 640])
                    assert hit is None, \
                        f"[fn-w03] mapClient(320,{ly}) 应 null: {hit}"
                page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:5]}"
    detail = ("world_02 wide_cam（DPR2）：黑带/边界外/画布外函数级无命中不改道"
              "+提示、mapClient null、合法命中 round-trip、默认四泳道函数级"
              "正向全中（函数级≠DOM 验证；DOM 路径见 CAM04/UI02）")
    if w03_ran:
        detail += "；world_03 wide_cam 历史反例坐标函数级不改道"
    else:
        detail += "（world_03 部分需 full 包）"
    return CaseResult("PASS", detail)


def ui02(ctx):
    """UI-02：真实 DOM 操作闭环（选关→选道→买兵→暂停/恢复）+负例+生产冒烟。

    操作全部走真实控件（click/select_option/fill/mouse），断言经只读查询
    （receipts/snapshot/drawLog/events）+ DOM 状态；禁止 hook 兜底（不直接
    调 handler、不设 value、不 hook buy、不 force）。test 模式冻结时钟仅作
    夹具（startGame/advanceTo/事件读取）；生产模式冒烟（B 节）完全不用
    __bb_test，等待全部 DOM 轮询（#tick/#hud-nectar/#buy-feedback/按钮文案）。

    A（test 夹具）：真实点击选关→开始；真实选道+真实点击买兵 → 新回执对应
    本次输入（commandId 新鲜、unit/lane 匹配）+ 资源变化（花蜜-price）+
    新出生实体（buy_ok.bugId ↔ snapshot 新 id ↔ drawLog 绘制，前后计数差）；
    负例：同泳道冷却复购（E_CD：无新实体、花蜜不变）、暂停后禁用按钮点击
    （playwright actionability 拒绝 + 回执不变）、黑带真实点击不改道；
    正向画布点选泳道（真实 mouse，默认相机）。
    B（生产冒烟）：选关→买兵（回执/花蜜/tick 推进 DOM 轮询）→暂停（tick 停
    +按钮禁用）→恢复（tick 续跑）。
    受控变异负例（移除 canvas 监听/遮挡买兵按钮 → 本用例必须 FAIL、FN01
    仍 PASS）经研究驱动器对 out/nc-uigate/web-mutated-* 跑，不入本用例。
    """
    sync_playwright = _need_playwright()
    from bugbits.render import billboard
    mf = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    pr = mf["projection"]["world_02"]
    wd = json.loads((ctx.web_out / "worlds" / "world_02.json")
                    .read_text(encoding="utf-8"))
    starts0 = {s["index"]: s["pos"] for s in wd["starts"] if s["sideId"] == 0}
    units_meta = json.loads((ctx.web_out / "units.json")
                            .read_text(encoding="utf-8"))
    price = units_meta["littlebeetle"]["price"]
    assert price and price > 0, "littlebeetle 价格须>0（资源变化断言前提）"
    consts_def = billboard.cam_consts(pr)
    url, srv = _serve(ctx.web_out)
    errors = []
    NO_LANE_MARK = "无有效泳道"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def fresh_page(vp=(1000, 760), dpr=1, query="test=1"):
                page = browser.new_page(viewport={"width": vp[0],
                                                  "height": vp[1]},
                                        device_scale_factor=dpr)
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(
                    f"console.{m.type}: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
                page.goto(f"{url}index.html?{query}&seed={SEED}")
                return page

            # ── A. test 模式（冻结时钟夹具；操作走真实控件） ──────────────
            page = fresh_page()
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.booted()", timeout=60000)
            assert page.evaluate(
                "!document.getElementById('overlay').hidden"), "选关遮罩未显示"
            _op_click_real(page, "#level-list button[data-id=level_02]")
            assert page.evaluate(
                "document.querySelector("
                "'#level-list button[data-id=level_02]').classList.contains('sel')"), \
                "关卡按钮未被选中"
            page.fill("#seed-input", str(SEED))
            _op_click_real(page, "#start-btn")
            page.wait_for_function(
                "window.__bb_test && window.__bb_test.ready()", timeout=60000)
            _set_camera_and_wait(page, None, ctx, errors, "ui02-explicit-overview")
            assert page.evaluate(
                "document.getElementById('overlay').hidden"), "开始后遮罩未隐藏"
            # 基线（只读）
            n0 = page.evaluate(
                "window.__bb_test.snapshot().then((s) => s.nectar[0])")
            bugs0 = page.evaluate(
                "window.__bb_test.snapshot().then((s) =>"
                " s.bugs.map((b) => b.id))")
            receipts0 = page.evaluate("window.__bb_test.receipts()")
            n_r0 = len(receipts0)
            # 真实选道 + 真实点击买兵 → 新回执对应本次输入
            _op_select_real(page, "#lane", "1")
            _op_click_real(page, "#buy-littlebeetle")
            page.wait_for_function(
                f"window.__bb_test.receipts().length === {n_r0 + 1}",
                timeout=10000)
            r = page.evaluate("window.__bb_test.receipts().slice(-1)[0]")
            assert r["queued"] is True and r["unit"] == "littlebeetle" \
                and r["lane"] == 1, f"回执不对应本次输入: {r}"
            assert r["commandId"] not in {x["commandId"] for x in receipts0}, \
                f"回执 commandId 非新鲜: {r['commandId']}"
            cid = r["commandId"]
            page.evaluate("window.__bb_test.advanceTo(2)")
            page.wait_for_function(
                "([cid]) => window.__bb_test.events().then((ev) =>"
                " ev.events.some((e) => e.type === 'buy_ok'"
                " && e.data.commandId === cid))",
                arg=[cid], timeout=10000)
            ev = page.evaluate(
                "([cid]) => window.__bb_test.events().then((ev) =>"
                " ev.events.find((e) => e.type === 'buy_ok'"
                " && e.data.commandId === cid))", [cid])
            # 资源变化方向正确（花蜜 -price）+ 新出生实体（前后计数差）
            snap = page.evaluate("window.__bb_test.snapshot()")
            assert snap["nectar"][0] == n0 - price, \
                f"花蜜变化不符: {snap['nectar'][0]} != {n0}-{price}"
            bug_id = ev["data"]["bugId"]
            assert bug_id not in set(bugs0), \
                f"新实体 id {bug_id} 在点击前已存在（历史快照冒充）"
            bugs1 = snap["bugs"]
            new_mine = [b for b in bugs1 if b["id"] not in set(bugs0)
                        and b["side"] == 0]
            assert any(b["id"] == bug_id and b["unit"] == "littlebeetle"
                       for b in new_mine), \
                f"新出生实体不匹配: bugId={bug_id} new={new_mine}"
            # 新实体被真实绘制（drawLog 条件等待，非固定延时）
            page.wait_for_function(
                "([id]) => window.__bb_test.drawLog().some((d) => d.id === id"
                " && !d.culled && d.key)", arg=[bug_id], timeout=10000)
            # 冷却负例：同泳道复购 bee → E_CD（无新实体、花蜜不变）
            _op_click_real(page, "#buy-bee")
            page.wait_for_function(
                f"window.__bb_test.receipts().length === {n_r0 + 2}",
                timeout=10000)
            r2 = page.evaluate("window.__bb_test.receipts().slice(-1)[0]")
            assert r2["queued"] is True and r2["unit"] == "bee", \
                f"bee 回执异常: {r2}"
            cid2 = r2["commandId"]
            page.evaluate("window.__bb_test.advanceTo(4)")
            page.wait_for_function(
                "([cid]) => window.__bb_test.events().then((ev) =>"
                " ev.events.some((e) => e.type === 'buy_reject'"
                " && e.data.commandId === cid))",
                arg=[cid2], timeout=10000)
            ev2 = page.evaluate(
                "([cid]) => window.__bb_test.events().then((ev) =>"
                " ev.events.find((e) => e.type === 'buy_reject'"
                " && e.data.commandId === cid))", [cid2])
            assert ev2["data"]["reason"] == "E_CD", \
                f"同泳道复购应 E_CD: {ev2['data']}"
            snap2 = page.evaluate("window.__bb_test.snapshot()")
            assert snap2["nectar"][0] == n0 - price, \
                f"E_CD 后花蜜变化: {snap2['nectar'][0]}"
            assert not [b for b in snap2["bugs"] if b["side"] == 0
                        and b["unit"] == "bee"], "E_CD 后出现了新 bee 实体"
            # 暂停（真实点击）→ 按钮文案/禁用/tick 停
            _op_click_real(page, "#pause-btn")
            assert page.evaluate(
                "document.getElementById('pause-btn').textContent") == "继续"
            assert page.evaluate(
                "Array.from(document.querySelectorAll('button.buy'))"
                ".every((b) => b.disabled)"), "暂停后买兵按钮未禁用"
            tp = page.evaluate("window.__bb_test.currentTick()")
            page.wait_for_timeout(300)
            assert page.evaluate("window.__bb_test.currentTick()") == tp, \
                "暂停期间 tick 推进"
            # 禁用按钮负例：actionability 拒绝（不可点）且状态不变
            clicked = True
            try:
                page.click("#buy-littlebeetle", timeout=1500)
            except Exception:                              # noqa: BLE001
                clicked = False
            assert clicked is False, "禁用按钮居然可点（actionability 失效?）"
            assert page.evaluate(
                f"window.__bb_test.receipts().length === {n_r0 + 2}"), \
                "禁用按钮点击产生了新回执"
            # 恢复（真实点击）→ 可推进
            _op_click_real(page, "#pause-btn")
            assert page.evaluate(
                "document.getElementById('pause-btn').textContent") == "暂停"
            assert page.evaluate(
                "Array.from(document.querySelectorAll('button.buy'))"
                ".every((b) => !b.disabled)"), "恢复后买兵按钮未解禁"
            page.evaluate(f"window.__bb_test.advanceTo({tp + 5})")
            assert page.evaluate("window.__bb_test.currentTick()") == tp + 5, \
                "恢复后无法推进"
            # 正向画布点选泳道（真实 mouse，默认相机，闭式投影出生点）
            page.evaluate("document.getElementById('worldstage')"
                          ".scrollIntoView({block: 'center'})")
            box = page.evaluate(
                "() => { const c = document.getElementById('scene');"
                " const r = c.getBoundingClientRect();"
                " return {l: r.left, t: r.top, w: r.width, h: r.height,"
                " bl: c.clientLeft, bt: c.clientTop}; }")
            cw, ch = box["w"] - 2 * box["bl"], box["h"] - 2 * box["bt"]
            lane3 = 3 if 3 in starts0 else sorted(starts0)[0]
            pos3 = starts0[lane3]
            e = billboard.project(consts_def, pos3[0], 0.0, pos3[2], 640.0)
            page.mouse.click(box["l"] + box["bl"] + e[0] * cw / 640,
                             box["t"] + box["bt"] + e[1] * ch / 640)
            got = page.evaluate(
                "document.getElementById('lane').value")
            assert got == str(lane3), \
                f"真实画布点击未选中泳道 {lane3}: {got}"
            # Cropped padding is not a visible canvas target. Outside stage DOM
            # click must preserve lane; exact geometric rejection remains FN01.
            _set_camera_and_wait(page, 'wide_cam', ctx, errors, 'ui02-wide')
            stage=page.evaluate(_STAGE_MEASURE)['stage']
            point=[stage['l']+stage['w']/2,stage['b']+2]
            assert page.evaluate('p=>window.__bb_test.mapClient(...p)',point) is None
            page.mouse.click(*point)
            assert page.locator('#lane').input_value()==got, 'stage outside DOM changed lane'
            assert page.evaluate(
                "window.__bb_test.setCameraPreset(null)") is True
            page.close()

            # ── B. 生产模式冒烟（无 __bb_test；DOM 轮询等待） ─────────────
            page2 = fresh_page(query="x=1")          # 无 test/record 参数
            page2.wait_for_selector("#overlay:not([hidden])", timeout=20000)
            _op_click_real(page2, "#level-list button[data-id=level_02]")
            page2.fill("#seed-input", str(SEED))
            _op_click_real(page2, "#start-btn")
            page2.wait_for_function(
                "document.getElementById('hud-nectar').textContent !== '—'",
                timeout=30000)
            page2.wait_for_function(
                "parseInt(document.getElementById('tick').textContent, 10) >= 3",
                timeout=30000)
            nb = int(page2.inner_text("#hud-nectar"))
            _op_select_real(page2, "#lane", "2")
            _op_click_real(page2, "#buy-littlebeetle")
            page2.wait_for_function(
                "document.getElementById('buy-feedback').textContent"
                ".includes('已购买')", timeout=10000)
            page2.wait_for_function(
                f"parseInt(document.getElementById('hud-nectar').textContent,"
                f" 10) === {nb - price}", timeout=10000)
            ta = int(page2.locator("#tick").text_content())
            page2.wait_for_function(
                f"parseInt(document.getElementById('tick').textContent, 10)"
                f" > {ta}", timeout=10000)
            _op_click_real(page2, "#pause-btn")
            page2.wait_for_function(
                "document.getElementById('pause-btn').textContent === '继续'",
                timeout=10000)
            # 让暂停时刻可能在途的 advance 批落定（≤1 批×5 tick）后再采样
            page2.wait_for_timeout(300)
            tb = int(page2.locator("#tick").text_content())
            page2.wait_for_timeout(600)
            assert int(page2.locator("#tick").text_content()) == tb, "暂停后 tick 未停"
            assert page2.evaluate(
                "document.getElementById('buy-littlebeetle').disabled"), \
                "生产模式暂停后买兵按钮未禁用"
            _op_click_real(page2, "#pause-btn")
            page2.wait_for_function(
                "document.getElementById('pause-btn').textContent === '暂停'",
                timeout=10000)
            page2.wait_for_function(
                f"parseInt(document.getElementById('tick').textContent, 10)"
                f" > {tb}", timeout=10000)
            page2.screenshot(path=str(ctx.run_dir / "ui02-prod-smoke.png"))
            page2.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:5]}"
    return CaseResult(
        "PASS",
        f"真实控件闭环：选关→选道→买兵（回执 commandId={cid[:16]}… 对应本次输入、"
        f"花蜜 {n0}→{n0 - price}、新实体 bugId={bug_id}↔drawLog）；"
        "E_CD/禁用/黑带负例不改状态；暂停→tick 停→恢复→推进；"
        "生产模式冒烟（无 __bb_test，DOM 轮询）全过")


# ── FRAME-01（2026-09-27 轮）：帧完成标记 + 条件等待 + 有限超时诊断 ──────

class _FrameWaitTimeout(AssertionError):
    """FRAME-01 条件等待超时（诊断落盘后抛出；首失败保留，不自动重跑）。"""


def _camera_frame_condition(before, key, generation, tick):
    """相机操作后的帧合同：新帧、新请求、当前局、目标 tick 与预设一致。"""
    return (f"(rs) => rs.seq > {before['seq']}"
            f" && rs.presetReq > {before['presetReq']}"
            f" && rs.generation === {generation}"
            f" && rs.tick !== null && rs.tick >= {tick}"
            f" && rs.presetKey === {json.dumps(key)}")


_CAMERA_REQUEST_JS = """key => {
  const entry = {done: false};
  window.__harnessCameraRequest = entry;
  Promise.resolve().then(() => window.__bb_test.setCameraPreset(key)).then(
    value => { entry.value = value; entry.done = true; },
    error => { entry.error = String(error); entry.done = true; });
  return true;
}"""
_CAMERA_REQUEST_DONE_JS = "() => window.__harnessCameraRequest.done && window.__harnessCameraRequest"


def _camera_request(page, key, timeout_ms=10000, ctx=None,
                    tag="camera-request", errors=None):
    import time as _time
    t0 = _time.monotonic()
    try:
        # evaluate 只登记 Promise，不把资源装载 Promise 返回给 Playwright。
        page.evaluate(_CAMERA_REQUEST_JS, key)
        handle = page.wait_for_function(_CAMERA_REQUEST_DONE_JS,
                                        timeout=timeout_ms, polling=50)
        try:
            result = handle.json_value()
        finally:
            handle.dispose()
        assert "error" not in result, f"相机请求拒绝: {result}"
        return result["value"]
    except Exception as error:
        _frame_diag(ctx, tag, "相机请求完成", timeout_ms,
                    (_time.monotonic() - t0) * 1000, error, errors)
        raise _FrameWaitTimeout(f"相机请求失败 [{tag}]（{timeout_ms}ms）") from error


async def _camera_request_async(page, key, timeout_ms=10000, ctx=None,
                                tag="camera-request-async", errors=None):
    import time as _time
    t0 = _time.monotonic()
    try:
        await page.evaluate(_CAMERA_REQUEST_JS, key)
        handle = await page.wait_for_function(_CAMERA_REQUEST_DONE_JS,
                                               timeout=timeout_ms, polling=50)
        try:
            result = await handle.json_value()
        finally:
            await handle.dispose()
        assert "error" not in result, f"相机请求拒绝: {result}"
        return result["value"]
    except Exception as error:
        _frame_diag(ctx, tag, "相机请求完成", timeout_ms,
                    (_time.monotonic() - t0) * 1000, error, errors)
        raise _FrameWaitTimeout(f"相机请求失败 [{tag}]（{timeout_ms}ms）") from error


def _set_camera_and_wait(page, key, ctx, errors, tag, timeout_ms=10000):
    before = page.evaluate("window.__bb_test.renderState()")
    generation = page.evaluate("window.__bb_test.generation()")
    tick = page.evaluate("window.__bb_test.currentTick()")
    assert _camera_request(page, key, timeout_ms=timeout_ms, ctx=ctx,
                           tag=tag + "-request", errors=errors) is True
    return _wait_frame(page, _camera_frame_condition(before, key, generation, tick),
                       timeout_ms=timeout_ms, ctx=ctx, tag=tag,
                       stage="相机操作后目标帧", errors=errors)


def _frame_diag(ctx, tag, stage, timeout_ms, elapsed_ms, error, errors):
    diag = {"tag": tag, "stage": stage, "timeoutMs": timeout_ms,
            "elapsedMs": round(elapsed_ms, 1),
            "waitError": str(error).splitlines()[0][:200],
            "renderState": None, "consolePageErrors": list(errors or [])[:20],
            "screenshot": None}
    path = ctx.run_dir / f"framediag-{tag}.json" if ctx is not None else None
    _write_frame_diag(path, diag)  # 先持久保存失败，再尝试可能失败的浏览器诊断。
    return diag, path


def _write_frame_diag(path, diag):
    if path is not None:
        path.write_text(json.dumps(diag, ensure_ascii=False, indent=1),
                        encoding="utf-8")


_FRAME_SNAPSHOT_JS = "() => ({state: window.__bb_test.renderState()})"


def _wait_frame(page, cond_js, timeout_ms=10000, ctx=None, tag="frame",
                stage="", errors=None, polling="raf"):
    """FRAME-01：等待帧完成标记满足条件（替换固定延时）。

    cond_js 为接收 renderState() 的 JS 函数表达式（如
    "(rs) => rs.tick !== null && rs.tick >= 100"）。超时有限（不无限重跑；
    稳定性抽样=0 次——首个失败保留并诊断，不以重跑绿代替解释）。超时保存：
    阶段耗时、最后帧标识（renderState 快照）、console/pageerror、截图
    （ctx.run_dir 证据目录，不按 scratch 回收），然后抛 _FrameWaitTimeout。
    返回满足条件时的 renderState()（调用方可核对帧标识）。诊断快照与截图各
    有 1s 操作预算；这不承诺浏览器/驱动进程失去响应时的全 runner 硬上界。
    """
    import time as _time
    t0 = _time.monotonic()
    expr = ("() => { const rs = window.__bb_test.renderState(); return "
            f"({cond_js})(rs) ? rs : false; }}")
    try:
        handle = page.wait_for_function(expr, timeout=timeout_ms, polling=polling)
        try:
            return handle.json_value()
        finally:
            handle.dispose()
    except Exception as e:                     # noqa: BLE001 - 超时诊断后重抛
        diag, diag_path = _frame_diag(ctx, tag, stage, timeout_ms,
                                     (_time.monotonic() - t0) * 1000, e, errors)
        try:
            handle = page.wait_for_function(_FRAME_SNAPSHOT_JS, timeout=1000,
                                            polling=50)
            try:
                diag["renderState"] = handle.json_value()["state"]
            finally:
                handle.dispose()
        except Exception as e2:                # noqa: BLE001
            diag["renderState"] = {"evalError": str(e2)}
        _write_frame_diag(diag_path, diag)
        if ctx is not None:
            try:
                shot = ctx.run_dir / f"framediag-{tag}.png"
                page.screenshot(path=str(shot), timeout=1000)
                diag["screenshot"] = str(shot)
            except Exception as shot_error:    # noqa: BLE001
                diag["screenshotError"] = str(shot_error)
            _write_frame_diag(diag_path, diag)
        raise _FrameWaitTimeout(
            f"帧条件等待超时（{timeout_ms}ms）[{tag}]{stage}: "
            f"最后帧={diag['renderState']}；诊断="
            f"{diag_path if diag_path else '（无 ctx，未落盘）'}") from e


async def _wait_frame_async(page, cond_js, timeout_ms=10000, ctx=None,
                            tag="frame", stage="", errors=None):
    """CAM03 的 async Playwright 等价合同，保留独立的失败诊断。"""
    import time as _time
    t0 = _time.monotonic()
    expr = ("() => { const rs = window.__bb_test.renderState(); return "
            f"({cond_js})(rs) ? rs : false; }}")
    try:
        handle = await page.wait_for_function(expr, timeout=timeout_ms, polling=50)
        try:
            return await handle.json_value()
        finally:
            await handle.dispose()
    except Exception as error:
        diag, path = _frame_diag(ctx, tag, stage, timeout_ms,
                                (_time.monotonic() - t0) * 1000, error, errors)
        try:
            handle = await page.wait_for_function(_FRAME_SNAPSHOT_JS,
                                                   timeout=1000, polling=50)
            try:
                diag["renderState"] = (await handle.json_value())["state"]
            finally:
                await handle.dispose()
        except Exception as diagnostic_error:
            diag["renderState"] = {"evalError": str(diagnostic_error)}
        _write_frame_diag(path, diag)
        if ctx is not None:
            try:
                shot = ctx.run_dir / f"framediag-{tag}.png"
                await page.screenshot(path=str(shot), timeout=1000)
                diag["screenshot"] = str(shot)
            except Exception as shot_error:
                diag["screenshotError"] = str(shot_error)
            _write_frame_diag(path, diag)
        raise _FrameWaitTimeout(f"帧条件等待失败 [{tag}]{stage}；诊断={path}") from error


async def _settle_camera_requests(page, timeout_ms=10000, ctx=None,
                                   tag="cam03-settle", errors=None):
    """仅启动 Promise 聚合；完成条件由宿主有界轮询，永不 settle 不会挂住。"""
    import time as _time
    t0 = _time.monotonic()
    await page.evaluate("""() => {
      window.__cam03Settled = null;
      Promise.all(window.__cam03.map(p => p.then(
        v => ({ok: true, v}), e => ({ok: false, e: String(e)}))))
        .then(results => { window.__cam03Settled = results; });
      return true;
    }""")
    # 每次串行等待完成后才发下一组请求，上一组结果不会覆盖本组。
    try:
        handle = await page.wait_for_function("() => window.__cam03Settled",
                                               timeout=timeout_ms, polling=50)
        try:
            return await handle.json_value()
        finally:
            await handle.dispose()
    except Exception as error:
        # 不再等待页内 Promise；基础诊断在任何后续浏览器操作前落盘。
        _frame_diag(ctx, tag, "预设请求 settle", timeout_ms,
                    (_time.monotonic() - t0) * 1000,
                    error, errors)
        raise _FrameWaitTimeout(f"预设请求未完成 [{tag}]（{timeout_ms}ms）") from error


# rAF 延迟注入（FRAME-01 延迟渲染反例 fixture）：包装 requestAnimationFrame，
# 回调延迟 delay_ms 派发。renderFrame 尾部经全局 requestAnimationFrame 续排，
# 注入后新帧周期 ≈ rAF+delay。返回恢复函数句柄（页内 __rAFDelayRestore）。
_RAF_DELAY_JS = """
(delayMs) => {
  if (window.__origRaf) { return false; }
  window.__origRaf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => window.__origRaf(
    (t) => setTimeout(() => cb(t), delayMs));
  return true;
}
"""

_RAF_RESTORE_JS = "() => { if (!window.__origRaf) { return false; }" \
                  " window.requestAnimationFrame = window.__origRaf;" \
                  " delete window.__origRaf; return true; }"


def fr01(ctx):
    """FR01（FRAME-01）：帧完成标记 + 条件等待 + 延迟渲染反例 + 有限超时诊断。

    1) 标记语义：renderState() 在**真实绘制结束后**发布——受控 rAF 延迟下，
       setCameraPreset 完成挂载（请求/挂载时刻）后标记的 presetKey/seq 仍为
       旧值（不在请求开始标完成）；条件等待等到绘制帧后才变新值。
    2) 延迟渲染反例：rAF 延迟 3s——advanceTo 完成后立即（同脚本原子读）读
       renderState/drawLog 得到**旧帧**（tick<目标、新实体未绘制）= 旧固定
       等待策略会误读的证明；条件等待（renderState.tick>=目标）后读到
       正确目标帧（新实体已绘制）。基线包（旧固定等待代码）的红端见
       research/nc_uigate_frame_probe.py 证据。
    3) 有限超时+诊断：fixture 杀死 rAF 链 → 条件等待在有限超时内失败，
       诊断（阶段耗时/最后帧标识/console/pageerror/截图）落 run_dir；
       稳定性抽样=0 次（首个失败保留）。
    历史线索（CAM04 300s→27s 超时，审查 F6）本轮未复现即如实记录，不写根因。
    """
    sync_playwright = _need_playwright()
    url, srv = _serve(ctx.web_out)
    errors = []
    diag_files = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def fresh_page():
                page = browser.new_page(viewport={"width": 1000, "height": 760})
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(
                    f"console.{m.type}: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
                page.goto(f"{url}index.html?test=1&seed={SEED}")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.booted()", timeout=60000)
                page.evaluate("window.__bb_test.startGame('level_02', 2026)")
                page.wait_for_function(
                    "window.__bb_test && window.__bb_test.ready()", timeout=60000)
                # FR01 deliberately tests an overview -> wide frame transition;
                # production now starts near, so establish the old frame via the
                # real camera operation before injecting either rAF fixture.
                _set_camera_and_wait(page, None, ctx, errors,
                                     "fr01-explicit-overview")
                return page

            # ── 1) 标记语义：请求/挂载时刻 ≠ 完成；绘制后才发布 ──────────
            # 1a. 杀死 rAF 链（无任何帧可画）→ setCameraPreset 挂载成功后
            #     标记必须保持旧值（确定性：请求开始不标完成）
            page = fresh_page()
            rs0 = page.evaluate("window.__bb_test.renderState()")
            assert rs0["seq"] >= 1 and rs0["tick"] is not None, \
                f"ready 后无已完成帧: {rs0}"
            page.evaluate("window.requestAnimationFrame = () => 0")
            page.wait_for_timeout(150)   # fixture settle：在排帧落地、链终止
            frozen0 = page.evaluate("window.__bb_test.renderState()")
            check = page.evaluate("""async () => {
              const before = window.__bb_test.renderState();
              const ok = await window.__bb_test.setCameraPreset('wide_cam');
              const after = window.__bb_test.renderState();
              return {ok, before, after};
            }""")
            assert check["ok"] is True, "setCameraPreset 被拒"
            assert check["after"]["presetKey"] is None \
                and check["after"]["seq"] == check["before"]["seq"] \
                == frozen0["seq"], \
                f"标记在请求/挂载时刻就发布（未等真实绘制）: {check}"
            page.close()
            # 1b. 正常节律 + 条件等待：挂载后下一**绘制帧**才发布新值
            page = fresh_page()
            seq0 = page.evaluate("window.__bb_test.renderState().seq")
            assert page.evaluate(
                "window.__bb_test.setCameraPreset('wide_cam')") is True
            rs1 = _wait_frame(
                page, "(rs) => rs.presetKey === 'wide_cam'"
                f" && rs.seq > {seq0}",
                timeout_ms=10000, ctx=ctx, tag="fr01-preset",
                stage="wide_cam 绘制完成", errors=errors)
            assert rs1["presetKey"] == "wide_cam" and rs1["seq"] > seq0, \
                f"条件等待结果异常: {rs1}"
            page.close()

            # ── 2) 延迟渲染反例：旧策略读旧帧 / 条件等待读目标帧 ─────────
            page = fresh_page()
            page.evaluate(_RAF_DELAY_JS, 3000)
            rs_base = page.evaluate("window.__bb_test.renderState()")
            _wait_frame(page, f"(rs) => rs.seq >= {rs_base['seq'] + 2}",
                        timeout_ms=15000, ctx=ctx, tag="fr01-settle2",
                        stage="延迟帧 settle（反例页）", errors=errors,
                        polling=100)
            t_target = page.evaluate("window.__bb_test.currentTick()") + 3
            # 同脚本原子读：advanceTo 完成后立即读标记与 drawLog（模拟旧固定
            # 等待策略在「advance 完成」时刻的读取——读到的是旧帧）
            stale = page.evaluate("""async (t) => {
              await window.__bb_test.buy('ant');
              await window.__bb_test.advanceTo(t);
              const rs = window.__bb_test.renderState();
              const draws = window.__bb_test.drawLog();
              return {rs,
                      antDrawn: draws.some((d) => d.unit === 'ant'
                                           && !d.culled && d.key)};
            }""", t_target)
            assert stale["rs"]["tick"] is None \
                or stale["rs"]["tick"] < t_target, \
                f"advanceTo 完成时刻应仍是旧帧（延迟渲染下）: {stale['rs']}"
            assert stale["antDrawn"] is False, \
                "advanceTo 完成时刻新实体已被绘制——反例前提不成立（延迟未生效?）"
            # 条件等待：等到目标 tick 的帧已绘制（不误读旧帧）
            rs2 = _wait_frame(
                page, f"(rs) => rs.tick !== null && rs.tick >= {t_target}",
                timeout_ms=15000, ctx=ctx, tag="fr01-delay-target",
                stage=f"延迟渲染下等待 tick>={t_target}", errors=errors,
                polling=100)
            assert rs2["tick"] >= t_target, f"条件等待结果异常: {rs2}"
            fresh_draws = page.evaluate("window.__bb_test.drawLog()")
            assert any(d.get("unit") == "ant" and not d.get("culled")
                       and d.get("key") for d in fresh_draws), \
                "条件等待后目标帧仍无新实体绘制"
            page.close()

            # ── 3) 有限超时 + 诊断（fixture 杀死 rAF 链） ─────────────────
            page = fresh_page()
            page.evaluate("window.__bb_test.advanceTo(2)")
            _wait_frame(page, "(rs) => rs.tick !== null && rs.tick >= 2",
                        timeout_ms=10000, ctx=ctx, tag="fr01-pre-kill",
                        stage="杀死 rAF 前基线帧", errors=errors)
            page.evaluate("window.requestAnimationFrame = () => 0")
            page.wait_for_timeout(150)     # fixture settle：在排帧落地、链终止
            frozen = page.evaluate("window.__bb_test.renderState()")
            t2 = frozen["tick"] + 3 if frozen["tick"] is not None else 5
            page.evaluate(f"window.__bb_test.advanceTo({t2})")
            timed_out = False
            try:
                _wait_frame(page, f"(rs) => rs.tick !== null && rs.tick >= {t2}",
                            timeout_ms=3000, ctx=ctx, tag="fr01-raf-kill",
                            stage="rAF 链被杀后的有限超时", errors=errors,
                            polling=100)
            except _FrameWaitTimeout:
                timed_out = True
            assert timed_out, \
                "rAF 链被杀后条件等待不应满足（应有限超时+诊断）"
            after = page.evaluate("window.__bb_test.renderState()")
            assert after["seq"] == frozen["seq"], \
                f"超时期间出现新帧（fixture 失效）: {after} vs {frozen}"
            for suffix in ("json", "png"):
                f = ctx.run_dir / f"framediag-fr01-raf-kill.{suffix}"
                assert f.is_file(), f"超时诊断未落盘: {f}"
                diag_files.append(str(f))
            diag = json.loads(
                (ctx.run_dir / "framediag-fr01-raf-kill.json")
                .read_text(encoding="utf-8"))
            for key in ("tag", "stage", "timeoutMs", "elapsedMs", "renderState",
                        "consolePageErrors", "screenshot"):
                assert key in diag, f"诊断缺字段 {key}: {list(diag)}"
            assert diag["renderState"]["tick"] is None \
                or diag["renderState"]["tick"] < t2, \
                f"诊断最后帧标识异常: {diag['renderState']}"
            assert diag["elapsedMs"] < 10000, \
                f"超时不有限: {diag['elapsedMs']}ms"
            page.close()
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, f"页面错误: {errors[:5]}"
    return CaseResult(
        "PASS",
        f"帧标记绘制后发布（挂载时刻仍旧值）；延迟 3s 反例：advanceTo 完成时刻"
        f"读到旧帧（tick<{t_target}、新实体未绘制）→ 条件等待读到目标帧"
        f"（tick={rs2['tick']}，新实体已绘制）；rAF 杀链有限超时"
        f"（{diag['elapsedMs']}ms）+诊断落盘 {len(diag_files)} 件"
        "（稳定性抽样=0，首失败保留）")


def stage01(ctx):
    """Production default/camera control and independent stage geometry; not DYNAMIC."""
    import time
    import subprocess
    mf = json.loads((ctx.web_out / 'manifest.json').read_text())
    worlds = [('world_02', 'level_02')]
    if any(l['id'] == 'level_09' for l in mf['levels']):
        worlds.append(('world_03', 'level_09'))
    url, server = _serve(ctx.web_out)
    records, errors, artifacts = [], [], []
    began = time.monotonic()
    try:
        with _need_playwright()() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for width, height, dpr in ((1000,760,1),(1000,760,2),(1280,720,1),(1280,720,2),(420,700,1),(420,700,2)):
                    page = browser.new_page(viewport={'width':width,'height':height},device_scale_factor=dpr)
                    page.on('pageerror',lambda e: errors.append(str(e)))
                    try:
                        page.goto(url+'index.html?test=1&seed=2026')
                        page.wait_for_function('window.__bb_test && window.__bb_test.booted()',timeout=60000)
                        # This DOM assertion is a minimal red on the unchanged formal package.
                        assert page.locator('#worldstage').count() == 1, 'STAGE01 missing production #worldstage'
                        for world, level in worlds:
                            if time.monotonic()-began > 220:
                                raise TimeoutError('STAGE01 220s budget exhausted')
                            if records and not page.locator('#overlay').is_visible():
                                _op_click_real(page,'#back-btn')
                            _op_click_real(page,f'#level-list button[data-id="{level}"]')
                            _op_click_real(page,'#start-btn')
                            page.wait_for_function('window.__bb_test.ready()',timeout=60000)
                            assert page.locator('select#camera-mode').count() == 1, 'STAGE01 missing production camera control after start'
                            current_generation=page.evaluate('window.__bb_test.generation()')
                            _wait_frame(page,f"rs => rs.presetKey==='wide_cam' && rs.tick===0 && rs.cameraReady && rs.generation==={current_generation}",ctx=ctx,tag=f'stage01-{world}-{width}-{dpr}-default',errors=errors)
                            m=page.evaluate(_STAGE_MEASURE)
                            aspect=mf['cameraPresets'][world]['wide_cam']['projection']['aspect']
                            assert m['camera']['activePresetKey']=='wide_cam',m
                            oy,scale=_stage_geometry_assert(m,aspect)
                            assert page.locator('#camera-mode').input_value()=='wide_cam'
                            record={'world':world,'level':level,'viewport':[width,height],'dpr':dpr,'default':m,'points':[]}
                            records.append(record)
                            # Noncentral points independently projected by Python authoritative camera.
                            from bugbits.render import billboard
                            consts=billboard.cam_consts(mf['cameraPresets'][world]['wide_cam']['projection'])
                            pr=mf['projection'][world]
                            for fx,fz in ((.35,.4),(.65,.55),(.45,.7),(.7,.3)):
                                x=pr['xmin']+(pr['xmax']-pr['xmin'])*fx
                                z=pr['zmin']+(pr['zmax']-pr['zmin'])*fz
                                lx,ly,cz=billboard.project(consts,x,0,z,640)
                                if cz<=1 or not (2<lx<638 and oy+2<ly<640-oy-2): continue
                                px=m['stage']['l']+lx*scale
                                py=m['stage']['t']+(ly-oy)*scale
                                hit=page.evaluate('p=>window.__bb_test.mapClient(...p)',[px,py])
                                assert hit is not None and abs(hit[0]-x)<1e-5 and abs(hit[1]-z)<1e-5,(hit,(x,z),(px,py))
                                record['points'].append({'world':[x,z],'logical':[lx,ly],'client':[px,py],'hit':hit})
                            assert record['points'],'STAGE01 no noncentral front visible point'
                            # Production near view must support an actual world
                            # lane selection within the existing 200u radius.
                            wd=json.loads((ctx.web_out/'worlds'/f'{world}.json').read_text())
                            starts={s['index']:s['pos'] for s in wd['starts'] if s['sideId']==0}
                            selectable=[]
                            for origin in starts.values():
                                for dx in range(-180,181,20):
                                    for dz in range(-180,181,20):
                                        x,z=origin[0]+dx,origin[2]+dz
                                        distances={lane:(pos[0]-x)**2+(pos[2]-z)**2 for lane,pos in starts.items()}
                                        lane=min(distances,key=distances.get)
                                        e=billboard.project(consts,x,0,z,640)
                                        if distances[lane]<39000 and e[2]>1 and 8<e[0]<632 and oy+8<e[1]<640-oy-8:
                                            selectable.append({'world':[x,z],'logical':e[:2],'lane':lane,'d2':distances[lane]})
                            selectable.sort(key=lambda c:abs(c['logical'][0]-320)+abs(c['logical'][1]-320))
                            selected=[]
                            for candidate in selectable:
                                _op_select_real(page,'#lane','0' if candidate['lane'] else '1')
                                before=page.evaluate(_STAGE_MEASURE)
                                r=before['stage'];scale=r['w']/640
                                px=r['l']+candidate['logical'][0]*scale
                                py=r['t']+(candidate['logical'][1]-oy)*scale
                                if page.evaluate('p=>document.elementFromPoint(...p)?.id',[px,py])!='scene':continue
                                page.mouse.click(px,py)
                                after=page.evaluate(_STAGE_MEASURE)
                                observed=page.locator('#lane').input_value()
                                selected.append(dict(candidate,client=[px,py],rectBefore=before['stage'],rectAfter=after['stage'],observed=observed,status=page.locator('#status').text_content()))
                                assert observed==str(candidate['lane']),('production near valid DOM selection failed',selected[-1])
                                break
                            assert len(selected)>=1,('production near has no actual selectable world point',world,width,dpr,len(selectable))
                            record['selectableCandidates']=len(selectable)
                            record['realWorldSelections']=selected
                            s=m['stage']
                            for px,py in ((s['l']+s['w']/2,s['t']-.25),(s['l']+s['w']/2,s['b']+.25),(s['l']-.25,s['t']+s['h']/2),(s['r']+.25,s['t']+s['h']/2)):
                                assert page.evaluate('p=>window.__bb_test.mapClient(...p)',[px,py]) is None,('stage outside',px,py)
                            backing=ctx.run_dir/f'stage01-{world}-{width}-dpr{dpr}-backing-canvas.png'
                            _save_backing_png(page,backing)
                            artifacts.append(str(backing))
                            r=subprocess.run([sys.executable,str(ROOT/'research/nc_camop_pixel_probe.py'),str(backing),'--input','backing','--aspect',str(aspect)],capture_output=True,text=True)
                            assert r.returncode==0,(r.stdout,r.stderr)
                            record['internalClip']=json.loads(r.stdout)
                            stage_image=ctx.run_dir/f'stage01-{world}-{width}-dpr{dpr}-stage.png'
                            page.locator('#worldstage').screenshot(path=str(stage_image))
                            artifacts.append(str(stage_image))
                            # Synthetic presentation fixture: clone real canvas computed geometry,
                            # draw distinguishable padding/corners, never inject a game snapshot.
                            page.evaluate('''a=>{const c=document.getElementById('scene'),f=c.cloneNode(false),cs=getComputedStyle(c);f.id='stage-fixture';
                            for(const key of ['width','height','transform','position','left','top','margin','border','padding','display'])f.style[key]=cs[key];
                            f.style.position='absolute';f.style.top='0';f.style.left='0';f.style.pointerEvents='none';c.style.visibility='hidden';c.parentElement.appendChild(f);
                            const q=f.getContext('2d'),d=f.width/640,h=640/a,o=(640-h)/2;q.setTransform(d,0,0,d,0,0);
                            q.fillStyle='#ff00ff';q.fillRect(0,0,640,640);q.fillStyle='#2040a0';q.fillRect(0,o,640,h);
                            for(const [x,y,col] of [[0,o,'#ff0000'],[620,o,'#00ff00'],[0,o+h-20,'#0000ff'],[620,o+h-20,'#ffff00']]){q.fillStyle=col;q.fillRect(x,y,20,20);}}
                            ''',aspect)
                            fixture=ctx.run_dir/f'stage01-{world}-{width}-dpr{dpr}-fixture.png'
                            try:
                                page.locator('#worldstage').screenshot(path=str(fixture),style='#hud,#mission,#hud-hives,#buybar {visibility:hidden !important;}')
                            finally:
                                page.evaluate("document.getElementById('stage-fixture').remove();document.getElementById('scene').style.visibility='';")
                            artifacts.append(str(fixture))
                            r=subprocess.run([sys.executable,str(ROOT/'research/nc_camop_pixel_probe.py'),str(fixture),'--input','stage','--aspect',str(aspect),'--fixture'],capture_output=True,text=True)
                            assert r.returncode==0,(r.stdout,r.stderr)
                            record['fixture']=json.loads(r.stdout)
                            # Real production select, ownership hit test, no direct setter fallback.
                            _camera_select_real(page,'overview',ctx,errors,'camera-dom-overview')
                            _wait_frame(page,'rs=>rs.presetKey===null',ctx=ctx,tag='stage01-dom-overview',errors=errors)
                            record['overview']=page.evaluate(_STAGE_MEASURE)
                            _stage_geometry_assert(record['overview'],1)
                            _camera_select_real(page,'wide_cam',ctx,errors,'camera-dom-near')
                            _wait_frame(page,"rs=>rs.presetKey==='wide_cam'",ctx=ctx,tag='stage01-dom-near',errors=errors)
                            _stage_geometry_assert(page.evaluate(_STAGE_MEASURE),aspect)
                            if width==1000 and dpr==1:
                                for w,h in ((420,700),(1000,760)):
                                    page.set_viewport_size({'width':w,'height':h})
                                    resized=page.evaluate(_STAGE_MEASURE)
                                    _stage_geometry_assert(resized,aspect)
                                    record.setdefault('resize',[]).append(resized)
                                    assert page.evaluate('window.scrollY')==0
                    finally:
                        page.close()
            finally:
                browser.close()
        assert not errors,errors
        for world,_ in worlds:
            for width in (1000,1280,420):
                a,b=[r['default'] for r in records if r['world']==world and r['viewport'][0]==width]
                for key in ('l','t','w','h'):
                    assert abs(a['stage'][key]-b['stage'][key])<=.5,(world,width,key,a,b)
        return CaseResult('PASS',f'{len(records)} production default stage groups: independent crop/DPR/noncentral mapping/outside null, backing clip, four-color fixture, real camera control roundtrip; not original DYNAMIC',artifacts=artifacts)
    finally:
        server.shutdown()
        server.server_close()
        (ctx.run_dir/'stage01.json').write_text(json.dumps({'kind':'engineering-stage-regression','originalDynamic':False,'groups':records,'errors':errors,'elapsedSeconds':time.monotonic()-began},ensure_ascii=False,indent=1))


def _gui_top_pixels(page, package, run_dir, tag):
    """Opaque original top-texture samples in the actual composed screenshot.

    DOM existence/z-index alone cannot prove visibility. Source RGBA and CSS
    contain geometry define expected pixels independently; child glyph/icon
    rectangles are excluded rather than hidden to keep production composition.
    """
    from PIL import Image
    bilinear=getattr(Image,'Resampling',Image).BILINEAR
    source_path=package/'assets/gui/main/maingui_top.png'
    with Image.open(source_path) as source: original=source.convert('RGBA')
    m=page.locator('#hud').evaluate("""el=>{const r=el.getBoundingClientRect();
      return {w:r.width,h:r.height,children:[...el.querySelectorAll('*')].map(c=>{const b=c.getBoundingClientRect();return {l:b.left-r.left,t:b.top-r.top,r:b.right-r.left,b:b.bottom-r.top};})};}""")
    width,height=round(m['w']),round(m['h'])
    factor=min(m['w']/original.width,m['h']/original.height)
    scaled=original.resize((round(original.width*factor),round(original.height*factor)),bilinear)
    ox,oy=(m['w']-original.width*factor)/2,(m['h']-original.height*factor)/2
    candidates=[]
    for sy in range(2,scaled.height-2):
        for sx in range(2,scaled.width-2):
            x,y=round(ox+sx),round(oy+sy)
            if any(c['l']-2<=x<=c['r']+2 and c['t']-2<=y<=c['b']+2 for c in m['children']):continue
            want=scaled.getpixel((sx,sy))
            neighborhood=[scaled.getpixel((sx+dx,sy+dy)) for dx in (-1,0,1) for dy in (-1,0,1)]
            if want[3]!=255 or max(want[:3])<50 or not all(v[3]==255 and max(abs(v[k]-want[k]) for k in range(3))<=12 for v in neighborhood):continue
            if any(abs(x-a[0])+abs(y-a[1])<10 for a in candidates):continue
            candidates.append((x,y,want[:3]))
    assert len(candidates)>=4,('top HUD original opaque sample premise',tag,len(candidates))
    path=run_dir/f'gui01-{tag}-top-hud.png'
    page.locator('#hud').screenshot(path=str(path))
    with Image.open(path) as screenshot: actual=screenshot.convert('RGB')
    assert actual.size==(width,height),('GUI01 top pixel fixture must use DPR1',actual.size,(width,height))
    checked=[]
    for x,y,want in candidates[:10]:
        got=actual.getpixel((x,y))
        assert max(abs(a-b) for a,b in zip(got,want))<=18,('top HUD hidden or corrupted in actual composition',tag,(x,y),want,got)
        checked.append({'pixel':[x,y],'sourceRGB':want,'actualRGB':got})
    return {'source':str(source_path),'originalDynamic':False,'screenshot':str(path),'opaqueSamples':checked}
