"""HARNESS-02 + PROV-03：构建来源一致性绑定单测。

PROV-03（2026-09-27 审查，ai/bug/2026-09-27-ui-provenance-review.md）修复后口径：
- 全部经 loader（manifest_info）读**盘上** manifest——旧测试手造含 runtime 的
  字典绕过 loader，正是漏检「loader 丢 runtime 字段」的原因；
- manifest_info 必须透传 runtime（loader→provenance_errors→sim_code_binding
  贯通）；真实 main()（子进程真实 CLI，隔离 fixture 仓库，run.py 字节等同真实
  入口）对「包指纹≠当前源码」非零阻断（exit 2 + package-source-mismatch +
  后续用例被阻塞），匹配包放行（用例实际执行）；
- 无指纹包政策显式（git 证据：55c1d5e 起 SCHEMA_VERSION=1 与
  runtime.simCodeFingerprint 同时引入——不存在历史无指纹包类别）：缺字段/
  非法格式 = 非构建产物或被篡改 → 显式拒绝，不按 unrecorded 兼容放行，
  不得静默把缺证据当完整来源验证；
- 既有语义保持：纯 docs 不入分层指纹、testCode 独立层、页面字节绑定、
  运行前后漂移检测（fingerprintsStart/End、packageStart/End）不变。

真实构建（builder→包→CLI 全链，slice/full × 匹配/不匹配 × 缺字段/非 hex）
矩阵证据脚本：research/prov03_integration_matrix.py →
out/nc-uigate/evidence/PROV-03/。本文件的子进程用例用合成包（同一 main 代码
路径的接线级回归），不跑 3 分钟级真实构建。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness" / "web"))

import run as R  # noqa: E402  (harness/web/run.py)


def _mk_tree(root):
    """合成源码树：web/ 页面 + src/bugbits + tools + harness/web + docs。"""
    (root / "web").mkdir(parents=True)
    for fn in R.PAGE_FILES:
        (root / "web" / fn).write_text(f"content-of-{fn}\n", encoding="utf-8")
    (root / "src" / "bugbits").mkdir(parents=True)
    (root / "src" / "bugbits" / "sim.py").write_text("print('sim')\n")
    (root / "tools").mkdir()
    (root / "tools" / "web_build.py").write_text("print('builder')\n")
    (root / "harness" / "web").mkdir(parents=True)
    (root / "harness" / "web" / "run.py").write_text("# test code\n")
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("doc\n")
    return root


def _mk_pkg(web_src, dest):
    """合成包：页面源码逐字拷贝（模拟 _copy_pages）。"""
    dest.mkdir(parents=True, exist_ok=True)
    for fn in R.PAGE_FILES:
        shutil.copyfile(web_src / fn, dest / fn)
    return dest


# ── loader 路径基类（PROV-03：不再手造含 runtime 的字典） ─────────────
class LoaderPathBase(unittest.TestCase):
    """manifest 从盘上经 manifest_info 读入（WEB_OUT 指向临时目录）。"""

    def setUp(self):
        self.src_root = Path(tempfile.mkdtemp(prefix="bb-prov-src-"))
        _mk_tree(self.src_root)
        self.out_base = Path(tempfile.mkdtemp(prefix="bb-prov-out-"))
        self.pkg = _mk_pkg(self.src_root / "web", self.out_base / "web")
        self._old_web_out = R.WEB_OUT
        R.WEB_OUT = self.pkg                 # manifest_info: parent/"web"|.../"web-full"
        self.addCleanup(self._restore)
        self.addCleanup(shutil.rmtree, self.src_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.out_base, ignore_errors=True)

    def _restore(self):
        R.WEB_OUT = self._old_web_out

    def write_manifest(self, subdir="web", runtime="a" * 64, profile="slice",
                       schema=1):
        """把 manifest 写到盘上（模拟构建器输出形状），再由 loader 读回。"""
        pkg = self.out_base / subdir
        pkg.mkdir(parents=True, exist_ok=True)
        _mk_pkg(self.src_root / "web", pkg)
        m = {"schemaVersion": schema, "profile": profile,
             "buildId": "b" * 64, "artifactDigest": "d" * 64}
        if runtime is not None:
            m["runtime"] = runtime if not isinstance(runtime, str) \
                else {"simCodeFingerprint": runtime}
        (pkg / "manifest.json").write_text(
            json.dumps(m, ensure_ascii=False), encoding="utf-8")
        return pkg


class TestManifestInfoLoader(LoaderPathBase):
    def test_loader_carries_runtime(self):
        """PROV-03 回归：manifest_info 必须透传 runtime（旧代码丢字段→红）。"""
        self.write_manifest(runtime="a" * 64)
        loaded = R.manifest_info("slice")
        self.assertTrue(loaded["present"])
        self.assertEqual(
            (loaded.get("runtime") or {}).get("simCodeFingerprint"), "a" * 64)

    def test_loader_missing_manifest(self):
        loaded = R.manifest_info("slice")
        self.assertFalse(loaded["present"])
        self.assertIn("缺失", loaded["error"])
        self.assertIsNone(loaded["buildId"])

    def test_loader_unreadable_manifest(self):
        (self.pkg / "manifest.json").write_text("{not json", encoding="utf-8")
        loaded = R.manifest_info("slice")
        self.assertFalse(loaded["present"])
        self.assertIn("不可读", loaded["error"])

    def test_loader_full_profile_does_not_borrow_slice(self):
        """RF-B01 语义：full 读 web-full，缺 manifest 时显式 present=False。"""
        self.write_manifest(runtime="a" * 64)            # 只有 web/
        loaded = R.manifest_info("full")
        self.assertFalse(loaded["present"])
        self.assertIn("web-full", loaded["webOut"])


class TestProvenanceChain(LoaderPathBase):
    """manifest_info → provenance_errors → sim_code_binding 贯通（经 loader）。"""

    def test_match_clean_through_loader(self):
        self.write_manifest(runtime="a" * 64)
        loaded = R.manifest_info("slice")
        errs, notes = R.provenance_errors(loaded, self.src_root / "web",
                                          current_fp="a" * 64)
        self.assertEqual(errs, [])

    def test_python_source_drift_blocked_through_loader(self):
        """PROV-03 核心负例（经 loader）：包指纹≠当前源码 → 显式不一致。

        旧代码：manifest_info 丢 runtime → sim_code_binding 视为 unrecorded
        → errs=[]（正式门禁漏检 Python 源码漂移）——本用例红。
        """
        self.write_manifest(runtime="a" * 64)
        loaded = R.manifest_info("slice")
        errs, notes = R.provenance_errors(loaded, self.src_root / "web",
                                          current_fp="b" * 64)
        self.assertEqual(len(errs), 1)
        self.assertIn("simCodeFingerprint", errs[0])
        self.assertIn("需重建", errs[0])

    def test_missing_runtime_rejected_not_compat(self):
        """无指纹包政策（显式）：缺 runtime = 非构建产物/篡改 → 显式错误。

        构建器自 55c1d5e（SCHEMA_VERSION=1 起）恒写 runtime.simCodeFingerprint，
        不存在历史无指纹包类别——不得按 unrecorded 兼容放行。
        """
        self.write_manifest(runtime=None)
        loaded = R.manifest_info("slice")
        errs, notes = R.provenance_errors(loaded, self.src_root / "web",
                                          current_fp="b" * 64)
        self.assertEqual(len(errs), 1)
        self.assertIn("runtime", errs[0])
        self.assertIn("显式拒绝", errs[0])

    def test_runtime_not_dict_rejected(self):
        self.write_manifest(runtime="oops-not-an-object")
        loaded = R.manifest_info("slice")
        errs, _ = R.provenance_errors(loaded, self.src_root / "web",
                                      current_fp="b" * 64)
        self.assertEqual(len(errs), 1)
        self.assertIn("runtime", errs[0])

    def test_non_hex_fingerprint_rejected(self):
        self.write_manifest(runtime="zz-not-hex")
        loaded = R.manifest_info("slice")
        errs, _ = R.provenance_errors(loaded, self.src_root / "web",
                                      current_fp="b" * 64)
        self.assertEqual(len(errs), 1)
        self.assertIn("非法格式", errs[0])

    def test_empty_fingerprint_rejected(self):
        self.write_manifest(runtime="")
        loaded = R.manifest_info("slice")
        errs, _ = R.provenance_errors(loaded, self.src_root / "web",
                                      current_fp="b" * 64)
        self.assertEqual(len(errs), 1)
        self.assertIn("非法格式", errs[0])

    def test_binding_match_records_verified_note(self):
        """绑定一致时报告显式记录已核验（不静默）。"""
        self.write_manifest(runtime="a" * 64)
        loaded = R.manifest_info("slice")
        _errs, notes = R.provenance_errors(loaded, self.src_root / "web",
                                           current_fp="a" * 64)
        self.assertTrue(any("simCodeFingerprint" in n for n in notes))

    def test_absent_manifest_skipped(self):
        """manifest 缺失交由 manifest-missing 用例阻塞，绑定检查跳过。"""
        loaded = R.manifest_info("slice")            # 未写 manifest
        self.assertFalse(loaded["present"])
        errs, notes = R.provenance_errors(loaded, self.src_root / "web")
        self.assertEqual((errs, notes), ([], []))


class TestExplicitManifestDrift(LoaderPathBase):
    def test_actual_generation_metadata_is_in_end_binding(self):
        package = self.write_manifest(subdir="generation")
        loaded = R.manifest_info("slice", package)
        start = {k: loaded.get(k) for k in ("buildId", "artifactDigest", "manifestHash")}
        fingerprint = R.layered_fingerprints()
        drift, _, _ = R.provenance_drift(fingerprint, start, "slice", web_out=package)
        self.assertEqual(drift, {})
        path = package / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["runtime"]["simCodeFingerprint"] = "b" * 64
        path.write_text(json.dumps(manifest))
        drift, _, _ = R.provenance_drift(fingerprint, start, "slice", web_out=package)
        self.assertEqual(drift, {"package": True})


class TestPageSourceBinding(LoaderPathBase):
    def test_identical_pages_clean(self):
        self.assertEqual(
            R.page_source_mismatches(self.pkg, self.src_root / "web"), [])

    def test_stale_package_detected(self):
        """只改源码保留旧包（负例核心）：源码 host.js 改、包不动 → 检出。"""
        (self.src_root / "web" / "host.js").write_text(
            "content-of-host.js\n// camera fix\n", encoding="utf-8")
        errs = R.page_source_mismatches(self.pkg, self.src_root / "web")
        self.assertEqual(len(errs), 1)
        self.assertIn("host.js", errs[0])
        self.assertIn("包与源码不一致", errs[0])

    def test_tampered_package_detected(self):
        (self.pkg / "worker.js").write_text("tampered\n", encoding="utf-8")
        errs = R.page_source_mismatches(self.pkg, self.src_root / "web")
        self.assertEqual(len(errs), 1)
        self.assertIn("worker.js", errs[0])

    def test_missing_source_file_reported(self):
        (self.src_root / "web" / "OFL.txt").unlink()
        errs = R.page_source_mismatches(self.pkg, self.src_root / "web")
        self.assertEqual(len(errs), 1)
        self.assertIn("OFL.txt", errs[0])
        self.assertIn("绑定失败", errs[0])

    def test_missing_package_file_ignored_here(self):
        """包内缺文件由 files 清单/validate 用例负责，不在此重复报。"""
        (self.pkg / "host.js").unlink()
        self.assertEqual(
            R.page_source_mismatches(self.pkg, self.src_root / "web"), [])

    def test_stale_pages_via_provenance_errors_through_loader(self):
        """集成：只改页面源码保留旧包 → provenance_errors（经 loader）非空。"""
        self.write_manifest(runtime="a" * 64)
        (self.src_root / "web" / "host.js").write_text(
            "content-of-host.js\n// camera fix\n", encoding="utf-8")
        loaded = R.manifest_info("slice")
        errs, _notes = R.provenance_errors(loaded, self.src_root / "web",
                                           current_fp="a" * 64)
        self.assertEqual(len(errs), 1)
        self.assertIn("host.js", errs[0])


class TestLayeredFingerprints(LoaderPathBase):
    def test_layers_isolated(self):
        fp0 = R.layered_fingerprints(self.src_root)
        # docs 变化：两层都不变（纯文档不误判、不触发重烤）
        (self.src_root / "docs" / "note.md").write_text("doc2\n")
        self.assertEqual(R.layered_fingerprints(self.src_root), fp0)
        # 测试代码变化：仅 testCode 变
        (self.src_root / "harness" / "web" / "run.py").write_text("# v2\n")
        fp1 = R.layered_fingerprints(self.src_root)
        self.assertEqual(fp1["buildAffecting"], fp0["buildAffecting"])
        self.assertNotEqual(fp1["testCode"], fp0["testCode"])
        # 页面源码变化：仅 buildAffecting 变
        (self.src_root / "web" / "host.js").write_text("v2\n", encoding="utf-8")
        fp2 = R.layered_fingerprints(self.src_root)
        self.assertNotEqual(fp2["buildAffecting"], fp1["buildAffecting"])
        self.assertEqual(fp2["testCode"], fp1["testCode"])
        # src/bugbits 变化：buildAffecting 变
        (self.src_root / "src" / "bugbits" / "sim.py").write_text("v2\n")
        fp3 = R.layered_fingerprints(self.src_root)
        self.assertNotEqual(fp3["buildAffecting"], fp2["buildAffecting"])
        # 构建器（tools/web_build.py）变化：buildAffecting 变（构建器=构建来源）
        (self.src_root / "tools" / "web_build.py").write_text("print('b2')\n")
        fp4 = R.layered_fingerprints(self.src_root)
        self.assertNotEqual(fp4["buildAffecting"], fp3["buildAffecting"])


# ── 真实 main() 子进程（隔离 fixture 仓库） ───────────────────────────
def _copy_tree(src, dst, skip_pycache=True):
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(Path(src).iterdir()):
        if skip_pycache and p.name == "__pycache__":
            continue
        if p.is_dir():
            _copy_tree(p, dst / p.name, skip_pycache)
        else:
            shutil.copy2(p, dst / p.name)


def _fixture_code_fingerprint(fixture):
    """fixture 源码指纹：真实 _code_fingerprint 对 fixture 树执行（与门禁
    子进程同一算法同一输入，非平行实现）。"""
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); from bugbits import web_build; "
         "print(web_build._code_fingerprint())" % str(fixture / "src")],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"指纹 oracle 失败: {r.stderr}"
    return r.stdout.strip()


def _write_synthetic_package(fixture, profile, fp):
    """合成包：PAGE_FILES 逐字拷贝 + manifest（runtime.simCodeFingerprint=fp，
    files 清单含页面文件——A01 可执行）。真实构建版见矩阵证据脚本。"""
    pkg = fixture / "out" / ("web-full" if profile == "full" else "web")
    pkg.mkdir(parents=True, exist_ok=True)
    files = []
    for fn in R.PAGE_FILES:
        data = (fixture / "web" / fn).read_bytes()
        (pkg / fn).write_bytes(data)
        files.append({"path": fn, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {
        "schemaVersion": 1, "profile": profile, "buildId": "0" * 64,
        "artifactDigest": hashlib.sha256(
            json.dumps(files, sort_keys=True).encode()).hexdigest(),
        "runtime": {"simCodeFingerprint": fp, "pyodideVersion": "synthetic"},
        "config": {}, "levels": [], "capabilities": {}, "fallbacks": [],
        "projection": {}, "spriteStats": {}, "missingTextKeys": [],
        "atlasPages": [], "terrainFiles": [], "audioFiles": [],
        "inputs": [], "icons": {}, "gui": {}, "files": files,
    }
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return pkg


def _run_gate(fixture, profile, case_id="A01", web_out=None):
    """真实 CLI 子进程：fixture 的 harness/web/run.py（字节等同真实入口）。"""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("BUGBITS_HARNESS_")}
    cmd = [sys.executable, str(fixture / "harness" / "web" / "run.py"),
           "--suite", "assets", "--profile", profile,
           "--scratch-root", str(fixture / "scratch")]
    if case_id:
        cmd += ["--case", case_id]
    if web_out is not None:
        cmd += ["--web-out", str(web_out)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          env=env)


def _report_from_stdout(stdout):
    path = None
    for line in stdout.splitlines():
        if line.startswith("  报告: "):
            path = line.split("  报告: ", 1)[1].strip()
    assert path, f"stdout 未含报告路径:\n{stdout}"
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestMainGateIntegration(unittest.TestCase):
    """真实 main() 门禁接线（子进程真实 CLI + 隔离 fixture 仓库）。

    fixture = web/ + src/ + tools/web_build.py + harness/web/*.py 的工作树快照
    （run.py 与真实入口字节一致，setUpClass 断言）+ 合成双 profile 包。
    """

    @classmethod
    def setUpClass(cls):
        cls.fx = Path(tempfile.mkdtemp(prefix="bb-prov-fx-"))
        for sub in ("web", "src", "tools", "harness"):
            _copy_tree(ROOT / sub, cls.fx / sub)
        # 同一 main 代码路径（非平行实现）：fixture run.py == 真实 run.py
        fx_runpy = (cls.fx / "harness" / "web" / "run.py").read_bytes()
        real_runpy = (ROOT / "harness" / "web" / "run.py").read_bytes()
        assert fx_runpy == real_runpy, \
            "fixture run.py 必须与真实入口字节一致（同一 main 代码路径）"
        cls.fp = _fixture_code_fingerprint(cls.fx)
        _write_synthetic_package(cls.fx, "slice", cls.fp)
        _write_synthetic_package(cls.fx, "full", cls.fp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fx, ignore_errors=True)

    def setUp(self):
        self._pristine = {}

    def _stash(self, rel):
        p = self.fx / rel
        self._pristine[rel] = p.read_bytes()

    def _restore_all(self):
        for rel, data in self._pristine.items():
            (self.fx / rel).write_bytes(data)

    def _mutate_append(self, rel, line):
        p = self.fx / rel
        self._stash(rel)
        with p.open("a", encoding="utf-8") as f:
            f.write(line)

    def _rewrite_manifest(self, profile, transform):
        pkg = self.fx / "out" / ("web-full" if profile == "full" else "web")
        rel = str(pkg.relative_to(self.fx) / "manifest.json")
        self._stash(rel)
        m = json.loads((self.fx / rel).read_text(encoding="utf-8"))
        transform(m)
        (self.fx / rel).write_text(
            json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

    def test_match_package_allowed_and_case_runs(self):
        """正向：包指纹==当前源码 → 门禁放行，用例实际执行（A01 PASS，exit 0）。"""
        r = _run_gate(self.fx, "slice")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = _report_from_stdout(r.stdout)
        self.assertEqual(report["exitCode"], 0)
        self.assertEqual(report["provenance"]["errors"], [])
        self.assertEqual([c["id"] for c in report["cases"]], ["A01"])
        self.assertEqual(report["cases"][0]["status"], "PASS")
        # 报告的 manifest 段透传 runtime（loader 贯通到 report）
        self.assertEqual(report["manifest"]["runtime"]["simCodeFingerprint"],
                         self.fp)

    def test_explicit_generation_runs_without_using_stale_default(self):
        target = self.fx / "out/custom-generation"
        shutil.copytree(self.fx / "out/web", target)
        try:
            self._mutate_append("out/web/host.js", "// stale default\n")
            self._rewrite_manifest("slice", lambda m: m.update(buildId="1" * 64))
            result = _run_gate(self.fx, "slice", web_out=target)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = _report_from_stdout(result.stdout)
            self.assertEqual(report["manifest"]["webOut"], str(target))
            self.assertEqual(report["provenance"]["drift"], {})
            self.assertEqual(report["cases"][0]["status"], "PASS")
        finally:
            self._restore_all()
            shutil.rmtree(target)

    def test_explicit_generation_cannot_bypass_profile_or_source(self):
        target = self.fx / "out/custom-generation"
        shutil.copytree(self.fx / "out/web-full", target)
        try:
            result = _run_gate(self.fx, "slice", web_out=target)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            report = _report_from_stdout(result.stdout)
            self.assertIn("profile", ";".join(report["provenance"]["errors"]))
            manifest = target / "manifest.json"
            data = json.loads(manifest.read_text())
            data["profile"] = "slice"
            data["runtime"]["simCodeFingerprint"] = "development-overlay-requires-explicit-review"
            manifest.write_text(json.dumps(data))
            result = _run_gate(self.fx, "slice", web_out=target)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            report = _report_from_stdout(result.stdout)
            self.assertEqual(report["cases"][0]["id"], "package-source-mismatch")
        finally:
            shutil.rmtree(target)

    def test_src_mutation_blocks_main(self):
        """负例：只改 src/bugbits（包不动）→ exit 2 + package-source-mismatch
        + 后续用例被阻塞（report 只有该 BLOCKED entry）。"""
        try:
            self._mutate_append(
                "src/bugbits/sim/__init__.py" if
                (self.fx / "src" / "bugbits" / "sim").is_dir()
                else "src/bugbits/sim.py",
                "# PROV-03: simulated python source drift\n")
            r = _run_gate(self.fx, "slice")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            report = _report_from_stdout(r.stdout)
            self.assertEqual(report["exitCode"], 2)
            self.assertEqual(len(report["cases"]), 1)
            entry = report["cases"][0]
            self.assertEqual(entry["id"], "package-source-mismatch")
            self.assertEqual(entry["status"], "BLOCKED")
            errs = report["provenance"]["errors"]
            self.assertEqual(len(errs), 1)
            self.assertIn("simCodeFingerprint", errs[0])
        finally:
            self._restore_all()

    def test_tools_mutation_blocks_main_full_profile(self):
        """负例（full profile + tools 输入）：只改 tools/web_build.py → 阻断。"""
        try:
            self._mutate_append("tools/web_build.py",
                                "# PROV-03: simulated builder drift\n")
            r = _run_gate(self.fx, "full")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            report = _report_from_stdout(r.stdout)
            self.assertEqual([c["id"] for c in report["cases"]],
                             ["package-source-mismatch"])
            self.assertIn("simCodeFingerprint",
                          report["provenance"]["errors"][0])
        finally:
            self._restore_all()

    def test_missing_runtime_rejected_by_main(self):
        """政策：manifest 丢 runtime → 显式拒绝（非零），不按兼容放行。"""
        try:
            self._rewrite_manifest("slice", lambda m: m.pop("runtime"))
            r = _run_gate(self.fx, "slice")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            report = _report_from_stdout(r.stdout)
            self.assertEqual([c["id"] for c in report["cases"]],
                             ["package-source-mismatch"])
            self.assertIn("runtime", report["provenance"]["errors"][0])
        finally:
            self._restore_all()

    def test_non_hex_fingerprint_rejected_by_main(self):
        """政策：simCodeFingerprint 非 hex → 显式拒绝（非零）。"""
        try:
            def _bad(m):
                m["runtime"]["simCodeFingerprint"] = "not-hex-!!"
            self._rewrite_manifest("full", _bad)
            r = _run_gate(self.fx, "full")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            report = _report_from_stdout(r.stdout)
            self.assertIn("非法格式",
                          report["provenance"]["errors"][0])
        finally:
            self._restore_all()


if __name__ == "__main__":
    unittest.main()
