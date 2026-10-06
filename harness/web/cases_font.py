"""UI03: real DOM controls must render with the bundled Chinese font."""
import json

from cases import CaseResult


def _font_record(page, cdp, selector):
    element = page.locator(selector)
    element.wait_for(state="visible")
    record = element.evaluate("""e => ({text: e.tagName === 'SELECT'
        ? e.selectedOptions[0].textContent : e.textContent,
        family: getComputedStyle(e).fontFamily,
        size: getComputedStyle(e).fontSize})""")
    root = cdp.send("DOM.getDocument")["root"]["nodeId"]
    node = cdp.send("DOM.querySelector", {
        "nodeId": root, "selector": selector})["nodeId"]
    record["fonts"] = cdp.send("CSS.getPlatformFontsForNode", {
        "nodeId": node})["fonts"]
    return record


def _run_font_ui(ctx, index_override=None):
    """Override is only for the explicitly labelled pre-build research fixture."""
    from cases_browser import _need_playwright, _serve, _camera_select_real
    groups, failures, artifacts = {}, [], []
    url, server = _serve(ctx.web_out)
    try:
        with _need_playwright()() as p:
            browser = p.chromium.launch(headless=True)
            for width, height, dpr in ((1000, 760, 1), (1000, 760, 2),
                                       (420, 700, 1), (420, 700, 2)):
                tag = f"{width}x{height}-dpr{dpr}"
                page = browser.new_page(viewport={"width": width, "height": height},
                                        device_scale_factor=dpr)
                if index_override is not None:
                    page.route("**/index.html?*", lambda route: route.fulfill(
                        status=200, content_type="text/html", body=index_override))
                page.goto(f"{url}index.html?test=1&seed=2026")
                page.wait_for_function("window.__bb_test && window.__bb_test.booted()",
                                       timeout=60000)
                page.evaluate("document.fonts.ready")
                cdp = page.context.new_cdp_session(page)
                cdp.send("DOM.enable")
                cdp.send("CSS.enable")
                level_selector = '#level-list button[data-id="level_02"]'
                records = {selector: _font_record(page, cdp, selector)
                           for selector in ("#start-btn", level_selector)}
                shot = ctx.run_dir / f"ui03-{tag}-start.png"
                page.screenshot(path=str(shot))
                artifacts.append(str(shot))
                page.click(level_selector)
                page.click("#start-btn")
                page.wait_for_function("window.__bb_test.ready()", timeout=60000)
                page.evaluate("document.fonts.ready")
                for selector in ("#buy-littlebeetle .buy-label", "#buy-bee .buy-label",
                                 "#buy-ant .buy-label", "#lane", "#pause-btn",
                                 "#reset-btn", "#mute-btn", "#back-btn",
                                 "#camera-mode", "#diagnostics > summary"):
                    records[selector] = _font_record(page, cdp, selector)
                assert records['#camera-mode']['text'].strip() == '近景', records['#camera-mode']
                assert records['#diagnostics > summary']['text'].strip() == '运行记录', records['#diagnostics > summary']
                # Inspect Chromium's actually used glyphs for both visible camera
                # labels, including the asynchronous production control commit.
                _camera_select_real(page, 'overview', ctx, [], 'ui03-font-overview-'+tag)
                page.evaluate('document.fonts.ready')
                records['#camera-mode (overview)'] = _font_record(page, cdp, '#camera-mode')
                assert records['#camera-mode (overview)']['text'].strip() == '全景'
                _camera_select_real(page, 'wide_cam', ctx, [], 'ui03-font-near-'+tag)
                page.evaluate('document.fonts.ready')
                for selector, record in records.items():
                    if "Noto Sans SC" not in record["family"]:
                        failures.append(f"{tag} {selector}: family={record['family']}")
                    fonts = record["fonts"]
                    if not any(f["isCustomFont"] and f["familyName"] == "Noto Sans SC"
                               and f["glyphCount"] > 0 for f in fonts):
                        failures.append(f"{tag} {selector}: bundled glyphs absent: {fonts}")
                    if any(not f["isCustomFont"] and f["glyphCount"] > 0 for f in fonts):
                        failures.append(f"{tag} {selector}: system fallback glyphs: {fonts}")
                shot = ctx.run_dir / f"ui03-{tag}-controls.png"
                page.screenshot(path=str(shot))
                artifacts.append(str(shot))
                groups[tag] = records
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    evidence = ctx.run_dir / "ui03-fonts.json"
    evidence.write_text(json.dumps({"fixture": index_override is not None,
        "package": str(ctx.web_out), "groups": groups, "failures": failures},
        ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts.append(str(evidence))
    return CaseResult("FAIL" if failures else "PASS",
                      "; ".join(failures) if failures else
                      "bundled Chinese font renders start/buy/lane/controls, both camera labels and diagnostics summary, 4 viewport/DPR groups",
                      artifacts=artifacts)


def font_ui(ctx):
    return _run_font_ui(ctx)
