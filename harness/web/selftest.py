#!/usr/bin/env python3
"""Web harness runner 自测（W0）：用合成用例验证 runner 机制本身。

验证项（非游戏断言——只测 harness 骨架）:
  1. PASS+FAIL 用例 → report 结构完整 + exit 1
  2. 空注册表（必需 suite 无已实现用例）→ 占位 BLOCKED + exit 2
  3. --case 精确过滤（存在/不存在）
  4. BlockedError → BLOCKED → exit 2
  5. 必需用例 SKIP 不得计通过 → exit 2

用法: python3 -B harness/web/selftest.py [--web-out DIR] [--scratch-root DIR]
--web-out 只读选择项目内包；scratch 和临时目录限于真实项目 tmp 内。
显式包仍经过真实来源门禁，退出码 0=自测全过。
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "web"))

import cases as cases_mod        # noqa: E402
import run as run_mod            # noqa: E402
from cases import Case, CaseResult  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _last_report():
    """读 runner 记录的最近 run 目录（run_mod.LAST_RUN_DIR, 无 fs 时序猜测）。"""
    d = run_mod.LAST_RUN_DIR
    if d is None:
        return None
    p = d / "report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _inject(case_list):
    cases_mod.CASES.clear()
    cases_mod.CASES.extend(case_list)


def _run_checks(gate, web_out, tmp_root):
    # 1) PASS + FAIL → exit 1, report 结构完整
    _inject([
        Case("selftest-ok", "assets", "合成通过用例",
             run=lambda ctx: CaseResult("PASS", "合成")),
        Case("selftest-fail", "assets", "合成失败用例",
             run=lambda ctx: CaseResult("FAIL", "合成断言失败",
                                        expected="A", actual="B")),
    ])
    code = gate(["--suite", "assets", "--profile", "slice"])
    rep = _last_report()
    check("pass+fail → exit 1", code == 1, f"exit={code}")
    check("report 结构完整", rep is not None and all(
        k in rep for k in ("runId", "git", "sourceFingerprint", "manifest",
                           "env", "cases", "summary", "exitCode")))
    if rep:
        by_id = {c["id"]: c for c in rep["cases"]}
        check("状态记录正确",
              by_id.get("selftest-ok", {}).get("status") == "PASS"
              and by_id.get("selftest-fail", {}).get("status") == "FAIL")
        check("期望/实测入 report",
              by_id.get("selftest-fail", {}).get("expected") == "A"
              and by_id.get("selftest-fail", {}).get("actual") == "B")
        check("summary 与 exitCode", rep["summary"]["FAIL"] == 1
              and rep["exitCode"] == 1)

    # 2) 空注册表 → 必需 suite 缺失 → exit 2
    _inject([])
    code = gate(["--suite", "assets", "--profile", "slice"])
    rep = _last_report()
    check("空 suite → exit 2", code == 2, f"exit={code}")
    check("占位 BLOCKED 记录", rep is not None and any(
        c["id"] == "assets-suite-missing" and c["status"] == "BLOCKED"
        for c in rep["cases"]))

    # 3a) --case 不存在 → exit 2
    _inject([Case("selftest-ok", "assets", "合成通过用例",
                  run=lambda ctx: CaseResult("PASS"))])
    code = gate(["--suite", "assets", "--case", "nope"])
    check("--case 不存在 → exit 2", code == 2, f"exit={code}")
    # 3b) --case 命中 → 只跑该用例且 exit 0
    _inject([
        Case("selftest-a", "assets", "A", run=lambda ctx: CaseResult("PASS")),
        Case("selftest-b", "bridge", "B", run=lambda ctx: CaseResult("PASS")),
    ])
    code = gate(["--suite", "all", "--case", "selftest-a"])
    rep = _last_report()
    check("--case 命中 → exit 0", code == 0, f"exit={code}")
    check("--case 只跑目标", rep is not None
          and [c["id"] for c in rep["cases"]] == ["selftest-a"])

    # 4) BlockedError → BLOCKED → exit 2
    def _blocked(ctx):
        raise cases_mod.BlockedError("playwright 未安装")
    _inject([Case("selftest-blocked", "browser", "环境阻塞",
                  run=_blocked)])
    code = gate(["--suite", "browser"])
    rep = _last_report()
    check("BlockedError → exit 2", code == 2, f"exit={code}")
    check("BLOCKED 状态记录", rep is not None
          and rep["cases"][0]["status"] == "BLOCKED")

    # 5) 必需用例 SKIP → exit 2
    _inject([Case("selftest-skip", "assets", "必需 SKIP",
                  run=lambda ctx: CaseResult("SKIP", "补充跳过"))])
    code = gate(["--suite", "assets"])
    check("必需 SKIP → exit 2", code == 2, f"exit={code}")

    # 6) 未实现注册项（run=None）→ BLOCKED
    _inject([Case("selftest-unimpl", "assets", "占位注册")])
    code = gate(["--suite", "assets"])
    check("未实现注册项 → exit 2", code == 2, f"exit={code}")

    # 7) manifest_info 按 profile 读正确服务目录（不借用另一 profile）
    info_s = run_mod.manifest_info("slice")
    info_f = run_mod.manifest_info("full")
    check("manifest_info slice→out/web", info_s.get("present")
          and info_s["webOut"].endswith("/out/web"))
    check("manifest_info full→out/web-full", info_f.get("present")
          and info_f["webOut"].endswith("/out/web-full"))
    check("slice/full buildId 不同",
          info_s.get("buildId") != info_f.get("buildId"))
    check("artifactDigest 键入报告",
          "artifactDigest" in info_s and "artifactDigest" in info_f)
    if web_out is not None:
        selected = run_mod.manifest_info("slice", web_out)
        check("显式包目录/profile一致", selected.get("present")
              and selected["webOut"] == str(web_out)
              and selected.get("packageProfile") == "slice")

    # 8) 缺失 manifest → 报告 present=False + runner exit 2（不静默借用）
    with tempfile.TemporaryDirectory(prefix="selftest-missing-", dir=tmp_root) as directory:
        missing = Path(directory) / "web"
        info_missing = run_mod.manifest_info("slice", missing)
        check("缺失 manifest → present=False",
              info_missing.get("present") is False
              and "缺失" in info_missing.get("error", ""))
        _inject([Case("selftest-ok", "assets", "合成通过",
                      run=lambda ctx: CaseResult("PASS"))])
        code = gate(["--suite", "assets", "--profile", "slice"], package=missing)
        rep = _last_report()
        check("缺失 manifest → exit 2", code == 2, f"exit={code}")
        check("manifest-missing BLOCKED 记录",
              rep is not None and any(
                  c["id"] == "manifest-missing" and c["status"] == "BLOCKED"
                  for c in rep["cases"]))

    # 9) 未知结果状态（PBA-08）→ 枚举校验转 FAIL + exit 1；计数总和=结果条数
    for bad in ("PAS", "ERROR", ""):
        tag = bad or "empty"
        _inject([Case(f"selftest-unknown-{tag}", "assets", "合成未知状态",
                      run=lambda ctx, s=bad: CaseResult(s))])
        code = gate(["--suite", "assets"])
        rep = _last_report()
        check(f"未知状态 {bad!r} → exit 1", code == 1, f"exit={code}")
        check(f"未知状态 {bad!r} 转 FAIL", rep is not None
              and rep["cases"][0]["status"] == "FAIL")
        if rep is not None:
            tot = sum(rep["summary"].values())
            check(f"未知状态 {bad!r} 计数总和=条数",
                  tot == len(rep["cases"]), f"{tot} vs {len(rep['cases'])}")

    # 9) 用例 ID 重复注册 → validate_registry 报错（PBA-07 冲突负例）
    _inject([Case("dup-id", "assets", "A", run=lambda ctx: CaseResult("PASS")),
             Case("dup-id", "bridge", "B", run=lambda ctx: CaseResult("PASS"))])
    errs = cases_mod.validate_registry()
    check("重复 ID 注册报错", len(errs) == 1 and "dup-id" in errs[0],
          f"errors={errs}")

    if FAILURES:
        print(f"\n自测失败 {len(FAILURES)}: {FAILURES}")
        return 1
    print("\nrunner 自测全过")
    return 0


def _project_path(value, parser):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        parser.error(f"路径必须位于项目内: {value}")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-out", help="只读选择项目内正式 slice 包；不改变来源门禁")
    parser.add_argument("--scratch-root", default=str(ROOT / "tmp/harness-selftest-scratch"),
                        help="真实项目 tmp 内的 scratch 根目录")
    args = parser.parse_args(argv)
    web_out = _project_path(args.web_out, parser) if args.web_out is not None else None
    scratch_root = _project_path(args.scratch_root, parser)
    tmp_root = _project_path(ROOT / "tmp", parser)
    if tmp_root != ROOT.resolve() / "tmp":
        parser.error("项目 tmp 不得通过符号链接重定向")
    # scratch must never add files to an existing delivery package.
    packages = [ROOT / "out/web", ROOT / "out/web-full"]
    if web_out is not None:
        packages.append(web_out)
    if any(scratch_root.is_relative_to(package.resolve()) for package in packages):
        parser.error("scratch 根目录不得位于受测包或旧正式包内")
    if not scratch_root.is_relative_to(tmp_root):
        parser.error("scratch 根目录必须位于项目 tmp 内")
    tmp_root.mkdir(parents=True, exist_ok=True)

    def gate(arguments, *, package=None):
        selected = package if package is not None else web_out
        forwarded = [*arguments, "--scratch-root", str(scratch_root)]
        if selected is not None:
            forwarded += ["--web-out", str(selected)]
        return run_mod.main(forwarded)

    original_cases = list(cases_mod.CASES)
    FAILURES.clear()
    try:
        return _run_checks(gate, web_out, tmp_root)
    finally:
        _inject(original_cases)


if __name__ == "__main__":
    sys.exit(main())
