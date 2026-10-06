#!/usr/bin/env python3
"""Web 线 harness 统一入口（loop-web.md §3；W0 骨架）。

用法:
  python3 harness/web/run.py --suite assets --profile slice
  python3 harness/web/run.py --suite bridge --profile slice
  python3 harness/web/run.py --suite browser --profile slice
  python3 harness/web/run.py --suite all --profile slice
  python3 harness/web/run.py --suite all --profile slice --case <ID>
  python3 harness/web/run.py --list

可选（HARNESS-01 scratch 生命周期）:
  --scratch-root DIR    scratch 根（默认系统临时目录下 bugbits-harness；
                        环境变量 BUGBITS_HARNESS_SCRATCH 同效）
  --keep-scratch        保留本轮 scratch 诊断副本（仍受保留上限约束）

退出码: 0=所选 suite 必需用例全部通过; 1=断言失败; 2=环境/依赖阻塞或
必需 suite/用例缺失（空 suite 不算通过）。

每次 run 产物: out/web-harness/<run-id>/（report.json + 证据级用例产物——
截图/负例说明）。可再生工作副本（det/sens/tamper 等）写 scratch（默认
/tmp/bugbits-harness/bugbits-<run-id>，与项目同根分区时换路径不增加容量）：
PASS 回收、FAIL 有界保留（BUGBITS_HARNESS_KEEP_* 上限）、崩溃残留由下次
run 孤儿恢复（pid 判活，不靠目录年龄）。水位不足 → BLOCKED + 有效报告，
不自动删除任何数据。
report 不进发布包; 重要摘要持久化 docs/web-validation.md（由任务维护）。
用例运行于独立POSIX进程组，父进程监管超时（browser300/bridge300/assets7200秒）。
--case-timeout SECONDS 覆盖预算；--status RUN_DIR 查询实时进度（无需suite）。
边界：内核不可中断状态/主动逃离进程组的后代不在硬实时清理承诺内。
"""
import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "web"))

from cases import REQUIRED_SUITES, BlockedError, CaseResult, cases_for  # noqa: E402
import scratch as scratch_mod  # noqa: E402  (harness/web/scratch.py)
import case_process  # noqa: E402

OUT_ROOT = ROOT / "out" / "web-harness"
WEB_OUT = ROOT / "out" / "web"
LAST_RUN_DIR = None          # 最近一次 main() 的 run 目录（selftest/编排器用）


# ── 环境信息 ─────────────────────────────────────────────────────────
def _sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              check=True, cwd=ROOT).stdout.strip()
    except Exception:                                    # noqa: BLE001
        return None


def source_fingerprint():
    """受测源码内容指纹（src/bugbits + web/ + tools/web_build.py + harness/web）。"""
    paths = []
    for pat in ("src/bugbits/**/*.py", "web/**/*", "harness/web/*.py",
                "tools/web_build.py"):
        paths.extend(p for p in ROOT.glob(pat) if p.is_file())
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def env_info():
    info = {"python": sys.version.split()[0]}
    try:
        import PIL
        info["pillow"] = PIL.__version__
    except ImportError:
        info["pillow"] = None
    info["node"] = _sh(["node", "--version"])
    info["npm"] = _sh(["npm", "--version"])
    try:
        import playwright
        info["playwright"] = getattr(playwright, "__version__", None) or "installed"
    except ImportError:
        info["playwright"] = None
    return info


def manifest_info(profile="slice", web_out=None):
    """按 profile 读取受测构建的 manifest（slice→out/web，full→out/web-full）。

    缺失/不可读时 present=False 并带 error，禁止静默借用另一 profile 的值。
    PROV-03（2026-09-27）：必须**透传 runtime**（含 simCodeFingerprint）——
    loader 丢字段曾使正式 main() 链把实包当 unrecorded，来源绑定门禁失效；
    runtime 一并进入 report 的 manifest 段（来源证据留痕）。
    """
    web_out = Path(web_out) if web_out is not None else WEB_OUT.parent / (
        "web-full" if profile == "full" else "web")
    mf = web_out / "manifest.json"
    info = {"profile": profile, "webOut": str(web_out)}
    if not mf.is_file():
        info.update({"present": False, "buildId": None, "artifactDigest": None,
                     "error": f"manifest 缺失: {mf}"})
        return info
    try:
        manifest_bytes = mf.read_bytes()
        m = json.loads(manifest_bytes)
    except (OSError, ValueError) as e:
        info.update({"present": False, "buildId": None, "artifactDigest": None,
                     "error": f"manifest 不可读: {e}"})
        return info
    info.update({"present": True, "buildId": m.get("buildId"),
                 "manifestHash": hashlib.sha256(manifest_bytes).hexdigest(),
                 "packageProfile": m.get("profile"),
                 "artifactDigest": m.get("artifactDigest"),
                 "schemaVersion": m.get("schemaVersion"),
                 "runtime": m.get("runtime")})
    return info


# ── HARNESS-02：来源一致性（分层指纹 + 包↔源码绑定） ─────────────────
PAGE_FILES = ("index.html", "worker.js", "host.js", "camera_projection.js",
              "mesh_scene.js", "presentation_material.js",
              "NotoSansSC-subset.woff2", "OFL.txt")


def _digest_paths(root, pats):
    h = hashlib.sha256()
    paths = []
    for pat in pats:
        paths.extend(p for p in Path(root).glob(pat) if p.is_file())
    for p in sorted(paths):
        h.update(str(p.relative_to(root)).encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def layered_fingerprints(root=ROOT):
    """分层源码指纹（HARNESS-02）：
    - buildAffecting：web/**（页面源码逐字入包）+ src/bugbits/**/*.py（经
      py-bundle 入包）+ tools/web_build.py（构建器）——任一变化都意味着
      "当前源码 ≠ 产出该包的源码"，旧包报告不得归于当前源码；
    - testCode：harness/web/*.py（测试代码；变化不要求重烤包，仅记录版本）。
    docs/** 不入任一层（纯文档改动不误判、不触发重烤）。"""
    return {
        "buildAffecting": _digest_paths(root, ("web/**/*", "src/bugbits/**/*.py",
                                               "tools/web_build.py")),
        "testCode": _digest_paths(root, ("harness/web/*.py",)),
    }


def page_source_mismatches(web_out, web_src):
    """包内逐字复制的页面源码 ↔ 仓库 web/ 字节比对（便宜且直接）。"""
    errors = []
    for fn in PAGE_FILES:
        pkg = Path(web_out) / fn
        src = Path(web_src) / fn
        if not pkg.is_file():
            continue        # 包内缺失由 files 清单/validate 负责，不在此重复
        if not src.is_file():
            errors.append(f"页面源码绑定失败: 仓库缺 {fn}（包内有、源码无）")
        elif pkg.read_bytes() != src.read_bytes():
            errors.append(f"包与源码不一致: {fn}（源码已改或包为旧版，需重建）")
    return errors


def _is_sha256_hex(value):
    """构建器指纹格式：sha256 十六进制（64 位小写 hex）。"""
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


_NO_RUNTIME_ERROR = (
    "manifest 缺 runtime.simCodeFingerprint（runtime 键缺失或非对象）——"
    "构建器恒写该字段（W1/55c1d5e 起，不存在历史无指纹包类别），"
    "非构建产物或已被篡改/损坏；正式门禁显式拒绝（非零），需重建包")


def sim_code_binding(manifest, current_fp=None):
    """manifest.runtime.simCodeFingerprint（构建期 src/bugbits+tools/web_build.py
    指纹，已入 buildId）↔ 当前重算。

    无指纹包政策（PROV-03，2026-09-27 显式化）：构建器自 W1（55c1d5e，
    SCHEMA_VERSION=1 起）恒写 runtime.simCodeFingerprint——不存在可兼容的
    "历史无指纹包"类别。缺字段/非法格式 = 非构建产物或 manifest 被篡改/损坏
    → 显式拒绝（package-source-mismatch 阻断，非零），不得按 unrecorded
    兼容放行、不得静默把缺证据当完整来源验证。绑定一致时返回核验 note
    （进入 report.provenance.notes，留痕"已核验"而非静默跳过）。
    """
    runtime = (manifest or {}).get("runtime")
    if not isinstance(runtime, dict):
        return ([_NO_RUNTIME_ERROR], None)
    recorded = runtime.get("simCodeFingerprint")
    if not _is_sha256_hex(recorded):
        return ([f"runtime.simCodeFingerprint 非法格式: {recorded!r}——须为 "
                 f"64 位 sha256 hex（构建器恒产此格式）；非构建产物或已被篡改，"
                 f"正式门禁显式拒绝（非零），需重建包"], None)
    if current_fp is None:
        sys.path.insert(0, str(ROOT / "src"))
        from bugbits import web_build      # 同 cases_assets 的导入口径
        current_fp = web_build._code_fingerprint()
    if recorded != current_fp:
        return ([f"包与源码不一致: simCodeFingerprint {recorded[:12]}… ≠ 当前 "
                 f"{current_fp[:12]}…（src/bugbits 或 tools/web_build.py 已改，"
                 f"需重建）"], None)
    return [], (f"simCodeFingerprint 绑定核验一致（{recorded[:12]}…）——"
                "python 源码绑定可用（显式核验，非静默放行）")


def provenance_errors(manifest, web_src, current_fp=None):
    """启动期包↔源码绑定检查（manifest 缺失时交由 manifest-missing 用例阻塞）。"""
    if not manifest or not manifest.get("present"):
        return [], []
    pkg_dir = manifest.get("webOut")
    errs = page_source_mismatches(pkg_dir, web_src)
    if manifest.get("packageProfile") != manifest.get("profile"):
        errs.append("受测包profile与所选profile不一致")
    sim_errs, note = sim_code_binding(manifest, current_fp=current_fp)
    return errs + sim_errs, ([note] if note else [])


def provenance_drift(fp_start, pkg_start, profile, web_out=None):
    """结束期漂移检测：运行中源码（分层）或包（buildId/artifactDigest）变化
    → 不得声称验证了单一版本。"""
    fp_end = layered_fingerprints()
    pkg_end = manifest_info(profile, web_out) if web_out is not None else manifest_info(profile)
    drift = {}
    for layer in ("buildAffecting", "testCode"):
        if fp_end[layer] != fp_start[layer]:
            drift[layer] = True
    for k in ("buildId", "artifactDigest", "manifestHash"):
        if pkg_end.get(k) != pkg_start.get(k):
            drift["package"] = True
    return drift, fp_end, {k: pkg_end.get(k) for k in ("buildId", "artifactDigest", "manifestHash")}


# ── 运行 ─────────────────────────────────────────────────────────────
class Ctx:
    """用例上下文（只读字段 + run_dir 证据目录 + scratch 工作副本）。

    HARNESS-01：证据（截图/负例说明）写 run_dir（保留）；可再生工作副本
    （det/sens/tamper 等）经 work_dir() 写 scratch（PASS 回收）。scratch
    为 None 时（研究驱动器路径）work_dir 显式拒绝，不静默落回 run_dir。
    """

    def __init__(self, profile, run_dir, env, manifest,
                 scratch=None, scratch_dir=None):
        self.profile = profile
        self.run_dir = run_dir
        self.env = env
        self.manifest = manifest
        # 构建目录按 profile：slice→out/web，full→out/web-full（W7）
        self.web_out = WEB_OUT.parent / (
            "web-full" if profile == "full" else "web")
        # HARNESS-01：scratch 管理器与当前用例归属（run_cases 逐用例设置）
        self.scratch = scratch
        self.scratch_dir = scratch_dir
        self.current_case = None
        self.results = []           # run_cases 增量记录（崩溃路径可取部分结果）

    def work_dir(self, name):
        """用例可再生工作子目录（登记归属用例；PASS 回收/FAIL 保留）。"""
        if self.scratch is None or self.scratch_dir is None:
            raise BlockedError(
                "本 Ctx 未配置 scratch（研究驱动器路径）——工作副本不可用；"
                "正式 run 由 harness/web/run.py 提供")
        return self.scratch.register_work(
            self.scratch_dir, name, self.current_case or "unknown")

    def check_budget(self, need_bytes, label=""):
        """大构建前水位检查（HARNESS-01；不足→BlockedError=有效非成功路径）。"""
        if self.scratch is None:
            return                          # 研究驱动器：不设防（无 scratch）
        try:
            self.scratch.budget_check(need_bytes=need_bytes, label=label)
        except scratch_mod.ScratchBudgetError as e:
            raise BlockedError(str(e)) from e


KNOWN_STATUSES = ("PASS", "FAIL", "BLOCKED", "SKIP")


def process_identity(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def write_progress(run_dir, **fields):
    path = Path(run_dir) / "progress.json"
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        record = {"pid": os.getpid(), "processIdentity": process_identity(os.getpid())}
    record.update(fields)
    record["updatedAt"] = time.time()
    scratch_mod.atomic_write_json(path, record)


def write_report(path, report):
    scratch_mod.atomic_write_json(path, report)
    write_progress(path.parent, status="complete", currentCase=None,
                   exitCode=report["exitCode"], summary=report["summary"],
                   completed=report["cases"])


def read_progress(run_dir):
    path = Path(run_dir)
    if (path / "report.json").is_file():
        report = json.loads((path / "report.json").read_text())
        return {"status": "complete", "exitCode": report["exitCode"],
                "summary": report["summary"], "report": str(path / "report.json")}
    record = json.loads((path / "progress.json").read_text())
    pid = record.get("pid")
    live = scratch_mod.pid_alive(pid)
    if record.get("processIdentity") is not None:
        live = live and process_identity(pid) == record["processIdentity"]
    if live and Path("/proc").is_dir():
        try:
            live = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            live = False
    record["processAlive"] = live
    if not live:
        record["status"] = "interrupted"
    return record


def run_cases(selected, ctx):
    results = ctx.results          # 增量记录：崩溃路径可从 ctx 取部分结果
    for case in selected:
        ctx.current_case = case.id
        t0 = time.monotonic()
        supervision = {}
        budget = getattr(ctx, "case_timeout", None) or case_process.DEFAULT_TIMEOUTS[case.suite]
        last_heartbeat = [0.0]
        def heartbeat(meta):
            now = time.monotonic()
            if now - last_heartbeat[0] < 1:
                return
            last_heartbeat[0] = now
            write_progress(ctx.run_dir, status="running", currentCase=case.id,
                           suite=case.suite, supervision=meta,
                           completed=results)
            if ctx.scratch is not None:
                ctx.scratch.touch(ctx.scratch_dir)
        print(f"  [RUNNING] {case.id} budget={budget:g}s", flush=True)
        try:
            res, supervision = case_process.execute(case, ctx, budget, heartbeat)
            if not isinstance(res, CaseResult):
                res = CaseResult("FAIL", f"用例返回非 CaseResult: {res!r}")
            elif res.status not in KNOWN_STATUSES:
                # 未知状态 = 协议错误（如拼写错误的 status）；转 FAIL 非零退出
                res = CaseResult("FAIL", f"未知结果状态 {res.status!r}"
                                 f"（原 detail: {res.detail}）",
                                 expected=res.expected, actual=res.actual)
        except BlockedError as e:
            res = CaseResult("BLOCKED", f"环境阻塞: {e}")
        except AssertionError as e:
            res = CaseResult("FAIL", f"断言失败: {e}")
        except Exception:                                 # noqa: BLE001
            res = CaseResult("FAIL", "异常:\n" + traceback.format_exc())
        entry = {"id": case.id, "suite": case.suite, "required": case.required,
                 "status": res.status, "detail": res.detail,
                 "expected": res.expected, "actual": res.actual,
                 "artifacts": res.artifacts,
                 "durationSec": round(time.monotonic() - t0, 3),
                 "supervision": supervision}
        results.append(entry)
        write_progress(ctx.run_dir, status="running", currentCase=None,
                       completed=results)
        print(f"  [{res.status}] {case.id} ({entry['durationSec']}s)"
              + (f" — {res.detail.splitlines()[0]}" if res.detail else ""), flush=True)
        if ctx.scratch is not None and ctx.scratch_dir is not None:
            ctx.scratch.touch(ctx.scratch_dir)    # 心跳（崩溃恢复佐证）
        if supervision.get("cleanupComplete") is False:
            ctx.cleanup_pending = supervision
        if getattr(ctx, "cleanup_pending", None):
            raise RuntimeError("用例进程组未完成清理；停止后续用例，保留活动scratch")
    return results


def summarize(results, suite):
    """退出码: 1=FAIL(含未知状态); 2=必需 BLOCKED/缺失/SKIP 或空跑; 0=其余全过。

    未知 status（拼写错误等）视为协议错误 → 转 FAIL 非零退出；计数总和必须等于
    结果条数；required 用例必须显式 PASS 才能退出 0（SKIP 不得计通过）。
    """
    unknown = [r for r in results if r["status"] not in KNOWN_STATUSES]
    for r in unknown:
        orig = r["status"]
        r["status"] = "FAIL"
        r["detail"] = f"未知结果状态 {orig!r}" + (
            f"（原 detail: {r['detail']}）" if r.get("detail") else "")
    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in KNOWN_STATUSES}
    if sum(counts.values()) != len(results):
        return 1, counts            # 计数与结果条数不符（防御不变量，应不可达）
    if counts["FAIL"]:
        return 1, counts
    if counts["BLOCKED"]:
        return 2, counts
    if not results:
        return 2, counts            # 空跑 = 缺失, 不算通过
    if any(r["required"] and r["status"] != "PASS" for r in results):
        return 2, counts            # required 必须显式 PASS；SKIP 等不得计通过
    return 0, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite",
                    choices=["assets", "bridge", "browser", "all"])
    ap.add_argument("--profile", default="slice", choices=["slice", "full"])
    ap.add_argument("--case", help="精确重跑指定用例 ID")
    ap.add_argument("--web-out", type=Path,
                    help="只读测试指定正式包目录；来源/profile门禁不变")
    ap.add_argument("--list", action="store_true", help="列出所选用例")
    ap.add_argument("--scratch-root", help="scratch 根目录（默认系统临时目录下 "
                    "bugbits-harness/；环境变量 BUGBITS_HARNESS_SCRATCH 同效）")
    ap.add_argument("--keep-scratch", action="store_true",
                    help="保留本轮 scratch 诊断副本（仍受保留上限约束）")
    ap.add_argument("--case-timeout", type=float,
                    help="每用例监管预算秒数（正有限数；覆盖suite默认值）")
    ap.add_argument("--status", metavar="RUN_DIR", help="只读查询run进度，不执行测试")
    args = ap.parse_args(argv)
    if args.status:
        try:
            print(json.dumps(read_progress(args.status), ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, KeyError) as error:
            print(f"无法读取进度: {error}", file=sys.stderr)
            return 2
    if not args.suite:
        ap.error("执行用例需要 --suite")
    if args.case_timeout is not None and (
            not math.isfinite(args.case_timeout) or args.case_timeout <= 0):
        ap.error("--case-timeout 必须为正有限数")

    selected = cases_for(args.suite, profile=args.profile, case_id=args.case)
    if args.list:
        for c in selected:
            impl = "已实现" if c.run else "未实现"
            print(f"{c.id}\t[{c.suite}]\t{impl}\t{c.description}")
        return 0

    # 必需 suite 缺用例检查（--case 交互选择后仍要求目标存在）
    if args.case and not selected:
        print(f"错误: 用例 {args.case!r} 不在 suite {args.suite!r} (profile {args.profile}) 注册表中",
              file=sys.stderr)
        return 2
    suites = REQUIRED_SUITES if args.suite == "all" else (args.suite,)
    # --case 精确重跑只验证目标用例本身; 不因其他 suite 未实现而 BLOCKED
    # （suite 级运行仍要求全部必需 suite 有已实现用例）
    unimplemented = [] if args.case else [
        s for s in suites
        if not any(c.suite == s and c.run for c in cases_for(s))]
    placeholder = [s for s in unimplemented
                   if not any(c.id == f"{s}-suite-missing" for c in selected)]

    run_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" \
        + hashlib.sha256(str(time.time()).encode()).hexdigest()[:6]
    run_dir = OUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    global LAST_RUN_DIR
    LAST_RUN_DIR = run_dir
    write_progress(run_dir, status="preflight", currentCase=None, completed=[])

    git = {"commit": _sh(["git", "rev-parse", "HEAD"]),
           "dirty": bool(_sh(["git", "status", "--porcelain"]))}
    env = env_info()
    manifest = manifest_info(args.profile, args.web_out) if args.web_out else manifest_info(args.profile)

    # ── HARNESS-01：scratch 生命周期 ────────────────────────────────
    # 崩溃残留恢复（pid 判活，不靠目录年龄）→ 水位检查 → 创建独占 scratch。
    mgr = scratch_mod.ScratchManager(root=args.scratch_root)
    orphans = mgr.collect_orphans()
    scratch_info = {"root": str(mgr.root), "dir": None,
                    "minFreeBytes": mgr.min_free_bytes,
                    "orphansRecycled": orphans}
    try:
        scratch_run = mgr.create(run_id)
    except scratch_mod.ScratchBudgetError as e:
        # 水位不足：不跑用例、不删任何数据；仍写有效 BLOCKED 报告（原子写）。
        entry = {"id": "disk-budget", "suite": "assets", "required": True,
                 "status": "BLOCKED", "detail": str(e),
                 "expected": "scratch 根分区可用空间 ≥ 需求 + 保底水位",
                 "actual": "不足", "artifacts": [], "durationSec": 0.0}
        report = {"runId": run_id, "timestamp": _dt.datetime.now().isoformat(),
                  "suite": args.suite, "profile": args.profile, "git": git,
                  "sourceFingerprint": source_fingerprint(),
                  "manifest": manifest, "env": env, "cases": [entry],
                  "summary": {"PASS": 0, "FAIL": 0, "BLOCKED": 1, "SKIP": 0},
                  "exitCode": 2,
                  "scratch": {**scratch_info,
                              "disposition": {"status": "not-created"}}}
        write_report(run_dir / "report.json", report)
        print(f"  [BLOCKED] disk-budget — {e}")
        print("  汇总: PASS=0 FAIL=0 BLOCKED=1 SKIP=0 → exit 2")
        print(f"  报告: {run_dir / 'report.json'}")
        return 2
    scratch_info["dir"] = str(scratch_run)
    scratch_info["freeBytesStart"] = mgr.free_bytes()

    ctx = Ctx(args.profile, run_dir, env, manifest,
              scratch=mgr, scratch_dir=scratch_run)
    if args.web_out is not None:
        ctx.web_out = args.web_out
    ctx.case_timeout = args.case_timeout

    # ── HARNESS-02：启动期包↔源码绑定（旧包不得测新源码；研究驱动器
    # research/nc_camop_run_case.py 不经 main()，不设此门——迭代路径与
    # 归属级门禁分离，冻结门禁必须走本入口）。 ─────────────────────────
    prov = {"errors": [], "notes": []}
    prov_errors, prov_notes = provenance_errors(manifest, ROOT / "web")
    if prov_errors:
        entry = {"id": "package-source-mismatch", "suite": "assets",
                 "required": True, "status": "BLOCKED",
                 "detail": "; ".join(prov_errors),
                 "expected": "包内页面源码/simCodeFingerprint 与当前源码一致",
                 "actual": f"{len(prov_errors)} 项不一致", "artifacts": [],
                 "durationSec": 0.0}
        disp = mgr.finish(scratch_run, keep_case_ids=set(),
                          keep_all=False)     # 空 scratch：直接回收
        scratch_info["disposition"] = disp
        report = {"runId": run_id, "timestamp": _dt.datetime.now().isoformat(),
                  "suite": args.suite, "profile": args.profile, "git": git,
                  "sourceFingerprint": source_fingerprint(),
                  "manifest": manifest, "env": env, "cases": [entry],
                  "summary": {"PASS": 0, "FAIL": 0, "BLOCKED": 1, "SKIP": 0},
                  "exitCode": 2, "scratch": scratch_info,
                  "provenance": {"errors": prov_errors, "notes": prov_notes}}
        write_report(run_dir / "report.json", report)
        print(f"  [BLOCKED] package-source-mismatch — {prov_errors[0]}"
              + (f"（共 {len(prov_errors)} 项）" if len(prov_errors) > 1 else ""))
        print("  汇总: PASS=0 FAIL=0 BLOCKED=1 SKIP=0 → exit 2")
        print(f"  报告: {run_dir / 'report.json'}")
        return 2
    prov["notes"] = prov_notes
    prov["fingerprintsStart"] = layered_fingerprints()
    prov["packageStart"] = {"buildId": manifest.get("buildId"),
                            "artifactDigest": manifest.get("artifactDigest"),
                            "manifestHash": manifest.get("manifestHash")}

    print(f"[web-harness] run={run_id} suite={args.suite} profile={args.profile}")
    print(f"  commit={git['commit']} dirty={git['dirty']} "
          f"webOut={manifest.get('webOut')} buildId={manifest.get('buildId')} "
          f"artifactDigest={str(manifest.get('artifactDigest'))[:16]}…")
    print(f"  scratch={scratch_run}"
          + (f"（孤儿回收: {', '.join(orphans)}）" if orphans else ""))

    crash = None
    try:
        results = run_cases(selected, ctx)
        for s in placeholder:
            results.append({"id": f"{s}-suite-missing", "suite": s, "required": True,
                            "status": "BLOCKED",
                            "detail": f"必需 suite {s!r} 无已实现用例（W0 骨架预期状态）",
                            "expected": "≥1 个已实现用例", "actual": "0",
                            "artifacts": [], "durationSec": 0.0})
            print(f"  [BLOCKED] {s}-suite-missing — 必需 suite 无已实现用例")
        # 受测构建 manifest 缺失/不可读 → 明确阻塞，不静默借用另一 profile
        if not manifest.get("present"):
            results.append({"id": "manifest-missing", "suite": "assets",
                            "required": True, "status": "BLOCKED",
                            "detail": manifest.get("error"),
                            "expected": f"{manifest.get('webOut')}/manifest.json 存在且可读",
                            "actual": "缺失或不可读", "artifacts": [],
                            "durationSec": 0.0})
            print(f"  [BLOCKED] manifest-missing — {manifest.get('error')}")
        code, counts = summarize(results, args.suite)
    except Exception:                                       # noqa: BLE001
        # 未预期崩溃：仍写有效非成功报告（含部分结果与 traceback）。无法捕获
        # 的硬终止（SIGKILL 等）由下次 run 的孤儿恢复识别——不假称已执行 finally。
        crash = traceback.format_exc()
        results = ctx.results
        results.append({"id": "run-crash", "suite": args.suite, "required": True,
                        "status": "FAIL", "detail": "运行器异常:\n" + crash,
                        "expected": "—", "actual": "异常", "artifacts": [],
                        "durationSec": 0.0})
        code = 1
        counts = {s: sum(1 for r in results if r["status"] == s)
                  for s in KNOWN_STATUSES}

    # ── HARNESS-02：结束期漂移检测（运行中源码/包变化 → 不产出单版本声明） ──
    try:
        drift, fp_end, pkg_end = provenance_drift(
            prov["fingerprintsStart"], prov["packageStart"], args.profile,
            web_out=args.web_out)
        prov["fingerprintsEnd"] = fp_end
        prov["packageEnd"] = pkg_end
        prov["drift"] = drift
    except Exception:                                       # noqa: BLE001
        prov["drift"] = {"checkError": True}
        drift = prov["drift"]
    if drift:
        results.append({"id": "provenance-drift", "suite": args.suite,
                        "required": True, "status": "BLOCKED",
                        "detail": f"运行中来源漂移: {sorted(drift)}——"
                                  "不得声称验证单一版本",
                        "expected": "运行期间源码与包指纹稳定",
                        "actual": f"漂移层: {sorted(drift)}", "artifacts": [],
                        "durationSec": 0.0})
        print(f"  [BLOCKED] provenance-drift — 漂移层: {sorted(drift)}")
        code, counts = summarize(results, args.suite)

    # 处置：PASS→回收全部 scratch；FAIL/BLOCKED/crash→仅保留非 PASS 用例的
    # 工作副本（--keep-scratch 全保留），受 bytes/count/age 上限约束。
    keep_ids = {r["id"] for r in results if r["status"] != "PASS"}
    try:
        if getattr(ctx, "cleanup_pending", None):
            disp = {"status": "cleanup-pending", "dir": str(scratch_run),
                    "supervision": ctx.cleanup_pending}
        else:
            disp = mgr.finish(scratch_run, keep_case_ids=keep_ids,
                              keep_all=args.keep_scratch)
    except Exception:                                       # noqa: BLE001
        disp = {"status": "error", "error": traceback.format_exc()}
    scratch_info["disposition"] = disp
    scratch_info["freeBytesEnd"] = mgr.free_bytes()

    report = {
        "runId": run_id,
        "timestamp": _dt.datetime.now().isoformat(),
        "suite": args.suite, "profile": args.profile,
        "git": git, "sourceFingerprint": source_fingerprint(),
        "manifest": manifest, "env": env, "cases": results,
        "summary": counts, "exitCode": code,
        "scratch": scratch_info,
        "provenance": prov,
    }
    write_report(run_dir / "report.json", report)
    print(f"  汇总: PASS={counts['PASS']} FAIL={counts['FAIL']} "
          f"BLOCKED={counts['BLOCKED']} SKIP={counts['SKIP']} → exit {code}")
    print(f"  scratch: {disp.get('status')}"
          + (f"（保留 {', '.join(disp.get('keptSubdirs', []))}）"
             if disp.get("keptSubdirs") else ""))
    print(f"  报告: {run_dir / 'report.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
