"""HUD01: normal STATIC HP/10 targets, original RGBA material, real reset.

This checks the declared instant-target adaptation, not original HUD easing,
zero-BaseSize sentinels, HP>10 clipping, or original-game DYNAMIC equivalence.
Dependencies are lazy so importing the case cannot initialize the registry.
"""
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
_MATERIALS = {"fill": (255, 192, 96, 255), "track": (96, 96, 96, 128)}
_READ_HUD = """() => {
  const box=e=>{const r=e.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height};};
  const sides={};
  for(const side of ['mine','enemy']) {
    const text=document.getElementById('hud-'+side);
    const fill=document.getElementById('hud-'+side+'-fill');
    const meter=fill.parentElement, track=meter.querySelector('.hive-track');
    sides[side]={text:text.textContent,title:text.title,
      inlineWidth:fill.style.width, fill:box(fill), meter:box(meter),
      panel:box(meter.parentElement),filter:getComputedStyle(fill).filter,
      trackFilter:track?getComputedStyle(track).filter:null,
      track:track?box(track):null,
      texture:getComputedStyle(fill).backgroundImage,
      backgroundSize:getComputedStyle(fill).backgroundSize};
  }
  return {generation:window.__bb_test.generation(),
    ready:window.__bb_test.ready(),sides,
    matrices:Object.fromEntries(['fill','track'].map(kind=>{
      const filter=document.getElementById('hive-'+kind+'-tint');
      const matrix=filter&&filter.querySelector('feColorMatrix');
      return [kind,{space:filter&&filter.getAttribute('color-interpolation-filters'),
        type:matrix&&matrix.getAttribute('type'),
        values:matrix&&matrix.getAttribute('values')}];}))};
}"""


def _original_hp(level_id):
    """Expectations come from original DATA, never rendered DOM or Sim output."""
    path = ROOT / "analyze/extracted/ccdzz/data/scripts/levels" / (level_id + ".vsc")
    data = path.read_bytes()
    text = data.decode("ascii", errors="ignore")
    result = {"path": str(path.relative_to(ROOT)),
              "sha256": hashlib.sha256(data).hexdigest()}
    for side, key in (("mine", "PlayerBaseSize"), ("enemy", "EnemyBaseSize")):
        value = re.search(r"^sp\s+" + key + r"\s+([-+\d.eE]+)\s*$", text, re.M)
        assert value is not None, f"original DATA lacks {key} in {level_id}"
        result[side] = float(value.group(1))
    return result


def _assert_targets(actual, original):
    for side in ("mine", "enemy"):
        hp = original[side]
        assert 0 < hp <= 10, "HUD01 intentionally covers only normal unclipped targets"
        entry = actual["sides"][side]
        expected = f"{int(hp / 10 * 100 + 0.1)}%"
        assert entry["text"] == expected, f"{side}: {entry['text']} != STATIC {expected}"
        ratio = entry["fill"]["w"] / entry["meter"]["w"]
        assert abs(ratio - hp / 10) < 0.002, \
            f"{side}: geometric fill {ratio} != STATIC hp/10 {hp / 10}"


def _assert_materials(actual):
    for kind, rgba in _MATERIALS.items():
        matrix = actual["matrices"][kind]
        assert matrix["space"] == "sRGB" and matrix["type"] == "matrix", \
            f"{kind}: material must multiply encoded texture RGBA in sRGB"
        values = [float(value) for value in matrix["values"].split()]
        expected = [0.0] * 20
        for offset, value in zip((0, 6, 12, 18), rgba):
            expected[offset] = value / 255
        assert len(values) == 20 and all(abs(a - b) < 1e-8
                                        for a, b in zip(values, expected)), \
            f"{kind}: color matrix {values} != original ARGB material {expected}"
    for entry in actual["sides"].values():
        assert "hive-fill-tint" in entry["filter"], "foreground material disconnected"
        assert entry["track"] is not None and "hive-track-tint" in entry["trackFilter"], \
            "original independent grey track layer missing/disconnected"
        assert "maingui_basebar_small.png" in entry["texture"], "original bar texture absent"


def _material_pixels(page, package, run_dir, actual):
    """Check visible multiplication against opaque source texels, not a color label.

    Meter/asset dimensions are mapped through actual CSS geometry. Opaque texels
    avoid unverified scene blending; the track sample is composited over the
    independently sampled original panel using its material alpha of 128/255.
    """
    from PIL import Image
    gui = package / "assets/gui/main"
    bilinear = getattr(Image, "Resampling", Image).BILINEAR
    with Image.open(gui / "maingui_basebar_small.png") as source:
        original_bar = source.convert("RGBA")
    results = {}
    for side, kind in (("mine", "fill"), ("enemy", "track")):
        entry = actual["sides"][side]
        width, height = round(entry["meter"]["w"]), round(entry["meter"]["h"])
        bar = original_bar.resize((width, height), bilinear)
        panel_name = "maingui_base_small" + ("_right" if side == "enemy" else "")
        with Image.open(gui / (panel_name + ".png")) as source:
            panel = source.convert("RGBA").resize(
                (round(entry["panel"]["w"]), round(entry["panel"]["h"])),
                bilinear)
        offset_x = round(entry["meter"]["x"] - entry["panel"]["x"])
        offset_y = round(entry["meter"]["y"] - entry["panel"]["y"])
        # Central region stays outside the enemy's rightmost 30% foreground.
        candidates = []
        for y in range(2, height - 2):
            for x in range(round(width * 0.3), round(width * 0.6)):
                source = bar.getpixel((x, y))
                underneath = panel.getpixel((offset_x + x, offset_y + y))
                if source[3] == 255 and min(source[:3]) >= 160 and underneath[3] == 255:
                    candidates.append((sum(source[:3]), x, y, source, underneath))
        assert candidates, "no independent opaque source texel for material verification"
        _, x, y, source, underneath = max(candidates)
        material = _MATERIALS[kind]
        alpha = source[3] / 255 * material[3] / 255
        expected = [round(source[i] * material[i] / 255 * alpha
                          + underneath[i] * (1 - alpha)) for i in range(3)]
        selector = ".hive-hud" + (".enemy" if side == "enemy" else ":not(.enemy)")
        path = run_dir / f"hud01-{side}-meter.png"
        page.locator(selector + " .hive-meter").screenshot(path=str(path))
        with Image.open(path) as shot:
            rgb = list(shot.convert("RGB").getpixel((x, y)))
        assert max(abs(a - b) for a, b in zip(rgb, expected)) <= 12, \
            f"{kind}: real RGB {rgb} != source × material/composite {expected}"
        if kind == "fill":
            assert rgb[0] - rgb[1] > 25 and rgb[1] - rgb[2] > 40, \
                f"original yellow material rendered white/uncoloured: {rgb}"
        results[kind] = {"sourceRGBA": source, "panelRGBA": underneath,
                         "materialRGBA": material, "pixel": [x, y],
                         "expectedRGB": expected, "actualRGB": rgb,
                         "tolerance": 12, "screenshot": str(path)}
    return results


def hud01(ctx):
    from cases import CaseResult
    from cases_browser import _need_playwright, _serve
    report = {"scope": "normal STATIC HP/10 targets and original RGBA materials",
              "originalDynamic": False, "displayEasing": "not reproduced",
              "package": str(ctx.web_out), "viewport": [1000, 760], "dpr": 1,
              "errors": []}
    report_path = ctx.run_dir / "hud01.json"
    url, server = _serve(ctx.web_out)
    browser = None
    try:
        with _need_playwright()() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 760},
                                        device_scale_factor=1)
                page.set_default_timeout(10000)
                page.on("pageerror", lambda error: report["errors"].append(str(error)))
                page.goto(url + "index.html?test=1&seed=2026")
                page.wait_for_function("window.__bb_test && window.__bb_test.booted()",
                                       timeout=60000)
                page.locator('#level-list button[data-id="level_02"]').click()
                page.locator("#start-btn").click()
                page.wait_for_function("window.__bb_test.ready() && "
                    "document.getElementById('hud-mine').textContent==='100%' && "
                    "document.getElementById('hud-enemy').textContent==='30%'", timeout=60000)
                original = _original_hp("level_02")
                assert (original["mine"], original["enemy"]) == (10, 3)
                actual = page.evaluate(_READ_HUD)
                _assert_targets(actual, original)
                _assert_materials(actual)
                report.update(original=original, initial=actual,
                              materials=_material_pixels(page, ctx.web_out, ctx.run_dir, actual))
                # Observe the actual request emitted by the real reset button.
                # There is no hook replacing state, no fake snapshot, and no fixed sleep.
                loading = []
                def observe_loading(route):
                    try:
                        loading.append(page.evaluate(_READ_HUD))
                    finally:
                        route.continue_()
                page.route("**/levels/level_02.json", observe_loading)
                previous = actual["generation"]
                page.locator("#reset-btn").click()
                page.wait_for_function("previous => window.__bb_test.generation()>previous && "
                    "window.__bb_test.ready() && "
                    "document.getElementById('hud-mine').textContent==='100%' && "
                    "document.getElementById('hud-enemy').textContent==='30%'",
                    arg=previous, timeout=60000)
                assert loading, "actual newgame level request was not observed"
                for pending in loading:
                    assert pending["generation"] > previous and not pending["ready"], \
                        "request observation did not cover a real in-progress reset"
                    for entry in pending["sides"].values():
                        assert entry["text"] == "" and entry["title"] == "" \
                            and entry["inlineWidth"] == "0%" and entry["fill"]["w"] == 0, \
                            f"newgame retained the previous HUD: {entry}"
                after = page.evaluate(_READ_HUD)
                _assert_targets(after, original)
                report.update(resetLoading=loading, afterReset=after)
                page.screenshot(path=str(ctx.run_dir / "hud01-level02.png"))
                manifest = json.loads((ctx.web_out / "manifest.json").read_text())
                if any(level["id"] == "level_03" for level in manifest["levels"]):
                    original03 = _original_hp("level_03")
                    assert original03["enemy"] == 5, "original level_03 DATA changed"
                    page.locator("#back-btn").click()
                    page.locator('#level-list button[data-id="level_03"]').click()
                    page.locator("#start-btn").click()
                    page.wait_for_function("window.__bb_test.ready() && "
                        "document.getElementById('hud-enemy').textContent==='50%'", timeout=60000)
                    actual03 = page.evaluate(_READ_HUD)
                    _assert_targets(actual03, original03)
                    report["optional50Percent"] = {"original": original03, "actual": actual03}
                else:
                    report["optional50Percent"] = "not included in this package; no synthetic state"
                assert not report["errors"], report["errors"]
                report["status"] = "PASS"
            finally:
                browser.close()
    except Exception as error:
        report["status"] = "FAIL"
        report["failure"] = repr(error)
        raise
    finally:
        server.shutdown()
        server.server_close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    return CaseResult("PASS", "normal DATA10/3→STATIC100%/30%; original yellow/grey RGBA "
                      "materials visible; real async reset clears widths/titles; no DYNAMIC claim",
                      artifacts=[str(report_path), str(ctx.run_dir / "hud01-level02.png"),
                                 str(ctx.run_dir / "hud01-mine-meter.png"),
                                 str(ctx.run_dir / "hud01-enemy-meter.png")])
