"""Real selftest CLI: package selection keeps the production provenance gate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SelftestCli(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="selftest-cli-", dir=ROOT / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.fixture = Path(self.temp.name)
        for name in ("src", "harness/web"):
            shutil.copytree(ROOT / name, self.fixture / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        (self.fixture / "tools").mkdir()
        shutil.copy2(ROOT / "tools/web_build.py", self.fixture / "tools/web_build.py")
        shutil.copytree(ROOT / "web", self.fixture / "web")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("BUGBITS_HARNESS_")}
        self.env.update(TMPDIR=str(self.fixture), PYTHONDONTWRITEBYTECODE="1")
        fingerprint = subprocess.run(
            [sys.executable, "-B", "-c",
             "import sys;sys.path.insert(0,sys.argv[1]);"
             "from bugbits.web_build import _code_fingerprint;print(_code_fingerprint())",
             str(self.fixture / "src")], env=self.env, capture_output=True,
            text=True, timeout=30, check=True).stdout.strip()
        for profile, name, build_id in (("slice", "web", "0"), ("full", "web-full", "1")):
            package = self.fixture / "out" / name
            package.mkdir(parents=True)
            files = []
            for filename in ("index.html", "worker.js", "host.js",
                             "NotoSansSC-subset.woff2", "OFL.txt"):
                data = (self.fixture / "web" / filename).read_bytes()
                (package / filename).write_bytes(data)
                files.append({"path": filename, "size": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()})
            manifest = {"profile": profile, "buildId": build_id * 64,
                        "artifactDigest": hashlib.sha256(
                            json.dumps(files, sort_keys=True).encode()).hexdigest(),
                        "runtime": {"simCodeFingerprint": fingerprint}, "files": files}
            (package / "manifest.json").write_text(json.dumps(manifest))
        self.package = self.fixture / "out" / "generation"
        shutil.copytree(self.fixture / "out/web", self.package)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(self.fixture / "harness/web/selftest.py"),
             *map(str, args)], cwd=self.fixture, env=self.env,
            capture_output=True, text=True, timeout=60)

    def test_explicit_package_ignores_stale_default_without_skipping_provenance(self):
        default = self.fixture / "out/web/host.js"
        default.write_text(default.read_text() + "\n// stale default\n")
        old = default.read_bytes()
        result = self.cli("--web-out", self.package,
                          "--scratch-root", self.fixture / "tmp/scratch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("runner 自测全过", result.stdout)
        self.assertIn("manifest-missing BLOCKED 记录", result.stdout)
        self.assertEqual(default.read_bytes(), old)
        reports = [json.loads(p.read_text()) for p in
                   (self.fixture / "out/web-harness").glob("*/report.json")]
        good = next(r for r in reports if any(c["id"] == "selftest-fail" for c in r["cases"]))
        self.assertEqual(good["manifest"]["webOut"], str(self.package))
        self.assertEqual(good["provenance"]["errors"], [])
        self.assertTrue(good["provenance"]["notes"])
        self.assertEqual(good["provenance"]["drift"], {})

    def test_default_selection_still_uses_default_package(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"webOut={self.fixture / 'out/web'} ", result.stdout)

    def test_explicit_stale_package_is_rejected_by_real_gate(self):
        host = self.package / "host.js"
        host.write_text(host.read_text() + "\n// stale selected package\n")
        result = self.cli("--web-out", self.package)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[BLOCKED] package-source-mismatch", result.stdout)
        self.assertNotIn("runner 自测全过", result.stdout)

    def test_paths_outside_project_and_scratch_inside_package_are_rejected(self):
        link = self.fixture / "outside-link"
        link.symlink_to(ROOT, target_is_directory=True)
        for option, path in (("--web-out", ROOT), ("--scratch-root", ROOT),
                             ("--web-out", link)):
            with self.subTest(option=option, path=path):
                result = self.cli(option, path)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("路径必须位于项目内", result.stderr)
        result = self.cli("--scratch-root", self.fixture / "out/web")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("scratch 根目录不得位于受测包或旧正式包内", result.stderr)
        self.assertFalse((self.fixture / "out/web-harness").exists())

    def test_scratch_in_original_material_tree_is_rejected_before_creation(self):
        original = self.fixture / "analyze/extracted/ccdzz"
        result = self.cli("--scratch-root", original)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("scratch 根目录必须位于项目 tmp 内", result.stderr)
        self.assertFalse(original.exists())
        self.assertFalse((self.fixture / "out/web-harness").exists())


if __name__ == "__main__":
    unittest.main()
