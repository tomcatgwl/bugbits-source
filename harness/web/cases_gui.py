"""Real long buy-rail regression; separate from the three-card UI01 contract."""
import json
import time

from cases import BlockedError, CaseResult


_METRICS = """unit => {
  const rail = document.getElementById('buybar');
  const button = document.getElementById('buy-' + unit);
  const price = button.querySelector('.buy-price-bar');
  const rect = e => { const r = e.getBoundingClientRect();
    return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}; };
  const rr = rect(rail);
  const br = rect(button);
  const pr = rect(price);
  const hit = document.elementFromPoint((br.l+br.r)/2, (br.t+br.b)/2);
  const priceHit = document.elementFromPoint((pr.l+pr.r)/2, (pr.t+pr.b)/2);
  const controls = {};
  for (const id of ['lane','pause-btn']) {
    const element = document.getElementById(id);
    const r = rect(element);
    const h = document.elementFromPoint((r.l+r.r)/2,(r.t+r.b)/2);
    controls[id] = {rect:r,hitSelf:!!h && element.contains(h)};
  }
  return {unit,rail:rr,visible:{l:rr.l+rail.clientLeft,t:rr.t+rail.clientTop,
    r:rr.l+rail.clientLeft+rail.clientWidth,
    b:rr.t+rail.clientTop+rail.clientHeight},
    scroll:{x:rail.scrollLeft,y:rail.scrollTop,w:rail.scrollWidth,h:rail.scrollHeight,
      clientW:rail.clientWidth,clientH:rail.clientHeight},
    button:br,price:pr,hitSelf:!!hit && button.contains(hit),
    priceHitInRail:!!priceHit && rail.contains(priceHit),
    shell:rect(document.getElementById('scene-shell')),
    scene:rect(document.getElementById('worldstage')),canvas:rect(document.getElementById('scene')),
    hives:rect(document.getElementById('hud-hives')),controls,
    viewport:{w:innerWidth,h:innerHeight},
    documentWidth:document.documentElement.scrollWidth,
    dpr:window.__bb_test.dprInfo()};
}"""


def _within(inner, outer, tolerance=1):
    return (inner["l"] >= outer["l"] - tolerance
            and inner["t"] >= outer["t"] - tolerance
            and inner["r"] <= outer["r"] + tolerance
            and inner["b"] <= outer["b"] + tolerance)


def _assert_metrics(m, wide, dpr):
    tag = m["unit"]
    viewport = {"l": 0, "t": 0, "r": m["viewport"]["w"], "b": m["viewport"]["h"]}
    assert _within(m["rail"], viewport), f"{tag}: rail outside first screen: {m}"
    assert _within(m["button"], m["visible"]), f"{tag}: button clipped by rail client viewport: {m}"
    assert _within(m["price"], m["visible"]), f"{tag}: price clipped by rail client viewport: {m}"
    assert m["button"]["w"] >= 88 and m["button"]["h"] >= 88, f"{tag}: card shrunk: {m}"
    assert m["hitSelf"], f"{tag}: actual button center obstructed: {m}"
    assert m["priceHitInRail"], f"{tag}: price falls outside the visible rail hit area: {m}"
    assert m["documentWidth"] <= m["viewport"]["w"], f"{tag}: page horizontally overflows: {m}"
    assert abs(m["hives"]["b"] - (m["shell"]["b"] - 1)) <= 1, f"{tag}: hive HUD detached from scene-shell bottom: {m}"
    assert abs(m["scene"]["b"] - m["shell"]["b"]) <= 1, f"{tag}: scene shell includes flowing cards: {m}"
    assert abs(m["canvas"]["w"]-m["canvas"]["h"]) <= .55, f"{tag}: square logical canvas distorted: {m}"
    assert abs(m["canvas"]["w"]-m["scene"]["w"]) <= .55, f"{tag}: canvas/stage CSS scale differs: {m}"
    assert m["dpr"]["logical"] == 640 and m["dpr"]["backing"] == 640 * dpr, f"{tag}: DPR changed logical canvas: {m}"
    for name, control in m["controls"].items():
        assert _within(control["rect"], viewport) and control["hitSelf"], f"{tag}: {name} offscreen or obstructed: {m}"
    scroll = m["scroll"]
    if wide:
        assert scroll["h"] > scroll["clientH"], f"{tag}: long vertical rail has no bounded scrolling: {m}"
        assert _within(m["rail"], m["scene"]), f"{tag}: desktop rail outside battlefield: {m}"
        assert m["rail"]["b"] <= m["hives"]["t"] + 1, f"{tag}: rail overlaps bottom hive HUD: {m}"
    else:
        assert scroll["w"] > scroll["clientW"], f"{tag}: long horizontal rail has no bounded scrolling: {m}"
        assert m["rail"]["h"] <= 180, f"{tag}: mobile rail expands with card count: {m}"


def gui02(ctx):
    """Four viewport/DPR groups, real level_24 long rail and DOM purchase."""
    # Import only when called, after the registry has finished initialization.
    from cases_browser import _need_playwright, _serve
    manifest = json.loads((ctx.web_out / "manifest.json").read_text(encoding="utf-8"))
    level = next((item for item in manifest["levels"] if item["id"] == "level_24"), None)
    if manifest["profile"] != "full" or level is None:
        raise BlockedError("GUI02 requires full package with level_24")
    assert len(level["buyable"]) == 14, f"level_24 independent long-list fixture changed: {level['buyable']}"
    units = json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8"))
    assert "ant" in level["buyable"], "level_24 must retain the explicitly buyable ant"
    price = units["ant"]["price"]
    assert isinstance(price, (int, float)) and price >= 0, f"invalid ant price: {price}"
    evidence = ctx.run_dir / "gui02-long-rail.json"
    groups, errors, artifacts = {}, [], [str(evidence)]
    began = time.monotonic()
    url, server = _serve(ctx.web_out)
    try:
        with _need_playwright()() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height, dpr in ((1000, 760, 1), (1000, 760, 2), (420, 700, 1), (420, 700, 2)):
                    if time.monotonic() - began > 220:
                        raise TimeoutError("GUI02 budget exhausted before next group")
                    tag = f"{width}x{height}-dpr{dpr}"
                    group = groups[tag] = {"cards": [], "level": "level_24"}
                    page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=dpr)
                    page.set_default_timeout(10000)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    try:
                        page.goto(url + "index.html?test=1&seed=2026", timeout=30000)
                        page.wait_for_function("window.__bb_test && window.__bb_test.booted()", timeout=45000)
                        page.locator('#level-list button[data-id="level_24"]').click()
                        page.locator("#start-btn").click()
                        page.wait_for_function("window.__bb_test.ready()", timeout=45000)
                        page.evaluate("window.__bb_test.advanceTo(0)")
                        page.wait_for_function("dpr => {const f=window.__bb_test.renderState(); const p=window.__bb_test.dprInfo(); return f.seq>0 && f.tick===0 && p.backing===640*dpr;}", arg=dpr, timeout=10000)
                        page.evaluate("document.fonts.ready")
                        identifiers = page.locator("#buybar button.buy").evaluate_all("buttons => buttons.map(button => button.dataset.unit)")
                        assert len(identifiers) == 14 and set(identifiers) == set(level["buyable"]), f"{tag}: actual cards do not match level buyable set: {identifiers}"
                        for unit in (identifiers[0], identifiers[-1]):
                            button = page.locator("#buy-" + unit)
                            button.scroll_into_view_if_needed()
                            button.locator(".buy-price-bar").scroll_into_view_if_needed()
                            page.evaluate("window.scrollTo(0, 0)")
                            metrics = page.evaluate(_METRICS, unit)
                            group["cards"].append(metrics)
                            _assert_metrics(metrics, width >= 900, dpr)
                        first, last = group["cards"]
                        assert abs(first["hives"]["b"] - last["hives"]["b"]) <= 1, f"{tag}: hive HUD drifts with rail scrolling"
                        group["before"] = page.evaluate("window.__bb_test.snapshot()")
                        assert group["before"]["nectar"][0] >= price, f"{tag}: ant is unaffordable in initial fixture"
                        receipts = page.evaluate("window.__bb_test.receipts()")
                        page.locator("#lane").select_option("0")
                        button = page.locator("#buy-ant")
                        button.scroll_into_view_if_needed()
                        button.locator(".buy-price-bar").scroll_into_view_if_needed()
                        button.click()
                        page.wait_for_function("count => window.__bb_test.receipts().length === count + 1", arg=len(receipts), timeout=10000)
                        receipt = page.evaluate("window.__bb_test.receipts().slice(-1)[0]")
                        group["receipt"] = receipt
                        assert receipt["queued"] is True and receipt["unit"] == "ant" and receipt["lane"] == 0, f"{tag}: real long-rail click did not queue requested purchase: {receipt}"
                        assert receipt["commandId"] not in {item["commandId"] for item in receipts}, f"{tag}: stale purchase receipt"
                        page.evaluate("window.__bb_test.advanceTo(2)")
                        events = page.evaluate("window.__bb_test.events()")
                        event = next((item for item in events["events"] if item["type"] == "buy_ok" and item["data"].get("commandId") == receipt["commandId"]), None)
                        assert event is not None, f"{tag}: queued purchase has no matching execution event: {events}"
                        group["buyEvent"] = event
                        assert event["data"]["price"] == price, f"{tag}: execution price differs from units data"
                        after = group["after"] = page.evaluate("window.__bb_test.snapshot()")
                        assert after["nectar"][0] == group["before"]["nectar"][0] - price, f"{tag}: nectar does not reflect actual purchase"
                        prior_ids = {bug["id"] for bug in group["before"]["bugs"]}
                        assert event["data"]["bugId"] not in prior_ids, f"{tag}: purchase reused an existing entity"
                        assert any(bug["id"] == event["data"]["bugId"] and bug["unit"] == "ant" and bug["side"] == 0 for bug in after["bugs"]), f"{tag}: purchased ant is absent from simulation"
                        feedback = page.locator("#buy-feedback")
                        assert feedback.is_visible() and "已购买" in feedback.inner_text(), f"{tag}: successful purchase has no visible feedback"
                        group["feedback"] = feedback.inner_text()
                        screenshot = ctx.run_dir / f"gui02-{tag}.png"
                        page.screenshot(path=str(screenshot))
                        artifacts.append(str(screenshot))
                    finally:
                        page.close()
            finally:
                browser.close()
        assert not errors, f"GUI02 page errors: {errors}"
    finally:
        server.shutdown()
        server.server_close()
        evidence.write_text(json.dumps({"kind": "long-rail-dom-regression", "originalDynamic": False,
            "package": str(ctx.web_out), "buildId": manifest["buildId"], "artifactDigest": manifest["artifactDigest"],
            "groups": groups, "errors": errors, "elapsedSeconds": round(time.monotonic() - began, 3)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return CaseResult("PASS", "level_24真实14卡：4视口/DPR首尾滚动及完整价格、底HUD锚定、首屏控制、实际ant购买；不等于原作DYNAMIC", artifacts=artifacts)
