"""Public preparation seam: real historical resources paired with their source.

The fixed historical fixture checks preview source binding and page overlays.
It does not validate the current terrain shader or complete terrain provenance.
Current web pages are copied separately; no manifest or source gate is altered.
"""
import ast
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_FIXTURE_REVISION = "f813eb5f39c8e5744279da424b2774a48a2a31b9"
sys.path.insert(0, str(ROOT / "src"))


class PreviewTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="preview-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # out/web is a real resource package from this fixed historical source.
        # HEAD/current src may change after a renderer fix or handoff commit.
        archive_bytes = subprocess.run(
            ["git", "archive", RESOURCE_FIXTURE_REVISION, "src/bugbits", "tools/web_build.py"],
            cwd=ROOT, check=True, capture_output=True, timeout=30).stdout
        with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                self.assertFalse(relative.is_absolute() or ".." in relative.parts)
                self.assertTrue(member.isdir() or member.isfile(), "archive links/special files forbidden")
                if member.isdir():
                    continue
                self.assertTrue(relative.is_relative_to(PurePosixPath("src/bugbits"))
                                or relative == PurePosixPath("tools/web_build.py"))
                target = self.root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
        shutil.copytree(ROOT / "web", self.root / "web")
        self.base = self.root / "out/base"
        shutil.copytree(ROOT / "out/web", self.base)
        mf = json.loads((self.base / "manifest.json").read_text())
        for rel in mf["inputs"]:
            target = self.root / "analyze/extracted/ccdzz/data" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "analyze/extracted/ccdzz/data" / rel, target)
        spec = importlib.util.spec_from_file_location("preview_fixture", ROOT / "tools/web_preview.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source_fingerprint = module._source_state(self.root)[0]
        self.assertEqual(source_fingerprint, mf["runtime"]["simCodeFingerprint"],
                         "historical resource fixture must match its actual creator source")
        assignments = ast.parse((self.root / "src/bugbits/web_build.py").read_text()).body
        vendor_hash = next(ast.literal_eval(node.value) for node in assignments
                           if isinstance(node, ast.Assign) and any(
                               isinstance(target, ast.Name) and target.id == "PYODIDE_SHA256"
                               for target in node.targets))
        inputs = sorted((rel, hashlib.sha256(
            (self.root / "analyze/extracted/ccdzz/data" / rel).read_bytes()).hexdigest())
                        for rel in mf["inputs"])
        actual_build_id = hashlib.sha256(json.dumps({
            "schemaVersion": mf["schemaVersion"], "profile": mf["profile"], "config": mf["config"],
            "inputs": inputs, "pyodide": [mf["runtime"]["pyodideVersion"], vendor_hash],
            "code": source_fingerprint}, sort_keys=True).encode()).hexdigest()
        self.assertEqual(actual_build_id, mf["buildId"],
                         "historical resources must retain their real input/build identity")
        self.output = self.root / "out/preview"

    def prepare(self, *, formal_pages_only=False):
        spec = importlib.util.spec_from_file_location("preview", ROOT / "tools/web_preview.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.prepare(self.base, self.output, root=self.root, formal_pages_only=formal_pages_only)

    def assert_historical_package_valid(self, package):
        # This real fixture belongs to the archived schema/source, not current
        # production. Retain the current schema rejection and validate with its
        # actual creator in a separate process, without mutating the package.
        from bugbits.web_build import validate
        historical_schema = json.loads((self.base / "manifest.json").read_text())["schemaVersion"]
        self.assertEqual(validate(str(package)),
                         [f"schemaVersion 不符: {historical_schema}"])
        result = subprocess.run(
            [sys.executable, "-B", "-c",
             "import json, sys; from bugbits.web_build import validate; "
             "print(json.dumps(validate(sys.argv[1])))", str(package)],
            cwd=self.root, env=dict(os.environ, PYTHONPATH=str(self.root / "src")),
            check=True, capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), [])

    def test_formal_pages_only_preserves_bundle_and_passes_existing_source_binding(self):
        self.output = self.root / "out/linux-continuation/builds/pages"
        result = self.prepare(formal_pages_only=True)
        package = Path(result["packagePath"])
        manifest = json.loads((package / "manifest.json").read_text())
        original = json.loads((self.base / "manifest.json").read_text())
        self.assertNotIn("development", manifest)
        self.assertEqual(manifest["runtime"], original["runtime"])
        self.assertEqual(manifest["buildId"], original["buildId"])
        self.assertEqual((package / "py-bundle.json").read_bytes(), (self.base / "py-bundle.json").read_bytes())
        self.assertEqual((package / "index.html").read_bytes(), (self.root / "web/index.html").read_bytes())
        self.assertEqual((package / "atlas_0.png").read_bytes(), (self.base / "atlas_0.png").read_bytes())
        self.assertTrue(result["formalPagesOnly"])
        self.assertFalse(result["development"])
        sys.path.insert(0, str(ROOT / "harness/web"))
        import run as runner
        checked = runner.manifest_info(original["profile"], package)
        errors, notes = runner.provenance_errors(checked, self.root / "web", current_fp=original["runtime"]["simCodeFingerprint"])
        self.assertEqual(errors, [])
        self.assertTrue(notes)
        self.assert_historical_package_valid(package)

    def test_formal_page_update_changes_digest_without_changing_resource_build_or_bundle(self):
        self.output = self.root / "out/linux-continuation/builds/pages"
        first = self.prepare(formal_pages_only=True)
        page = self.root / "web/index.html"
        page.write_text(page.read_text() + "\n<!-- FORMAL PAGE UPDATE -->\n")
        second = self.prepare(formal_pages_only=True)
        package = Path(second["packagePath"])
        self.assertNotEqual(first["artifactDigest"], second["artifactDigest"])
        self.assertEqual(first["baseBuildId"], second["baseBuildId"])
        self.assertIn("FORMAL PAGE UPDATE", (package / "index.html").read_text())
        self.assertEqual((package / "py-bundle.json").read_bytes(), (self.base / "py-bundle.json").read_bytes())
        self.assertTrue(Path(first["packagePath"]).is_dir())

    def test_formal_runtime_change_rejected_but_sealed_development_can_refresh(self):
        dev_out = self.output
        self.prepare()
        self.output = self.root / "out/linux-continuation/builds/pages"
        self.prepare(formal_pages_only=True)
        previous = (self.output / "current.json").read_bytes()
        source = self.root / "src/bugbits/sim/sim.py"
        source.write_text(source.read_text() + "\n# runtime revised\n")
        with self.assertRaisesRegex(ValueError, "unchanged Python"):
            self.prepare(formal_pages_only=True)
        self.assertEqual(previous, (self.output / "current.json").read_bytes())
        self.output = dev_out
        result = self.prepare()
        bundle = json.loads((Path(result["packagePath"]) / "py-bundle.json").read_text())
        self.assertIn("runtime revised", bundle["bugbits/sim/sim.py"])

    def test_formal_and_development_containers_cannot_be_mixed(self):
        self.output = self.root / "out/linux-continuation/builds/formal"
        self.prepare(formal_pages_only=True)
        with self.assertRaisesRegex(ValueError, "mode"):
            self.prepare()
        self.output = self.root / "out/linux-continuation/builds/development"
        self.prepare()
        with self.assertRaisesRegex(ValueError, "mode"):
            self.prepare(formal_pages_only=True)

    def test_formal_output_restricted_to_builds_directory(self):
        with self.assertRaisesRegex(ValueError, "inside out/linux-continuation/builds"):
            self.prepare(formal_pages_only=True)
        self.assertFalse(self.output.exists())

    def test_development_package_cannot_be_used_as_formal_base(self):
        development = self.prepare()
        self.base = Path(development["packagePath"])
        self.output = self.root / "out/linux-continuation/builds/pages"
        with self.assertRaisesRegex(ValueError, "formal resource package"):
            self.prepare(formal_pages_only=True)

    def test_formal_rejects_changed_resource_input_and_preserves_previous_pointer(self):
        self.output = self.root / "out/linux-continuation/builds/pages"
        self.prepare(formal_pages_only=True)
        previous = (self.output / "current.json").read_bytes()
        mf = json.loads((self.base / "manifest.json").read_text())
        source = self.root / "analyze/extracted/ccdzz/data" / mf["inputs"][0]
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "inputs"):
            self.prepare(formal_pages_only=True)
        self.assertEqual(previous, (self.output / "current.json").read_bytes())

    def test_formal_rejects_asset_source_change_even_with_prior_seal(self):
        self.output = self.root / "out/linux-continuation/builds/pages"
        self.prepare(formal_pages_only=True)
        source = self.root / "src/bugbits/render/camera.py"
        source.write_text(source.read_text() + "\n# asset change\n")
        with self.assertRaisesRegex(ValueError, "unchanged Python"):
            self.prepare(formal_pages_only=True)

    def test_formal_rejects_polluted_base(self):
        self.output = self.root / "out/linux-continuation/builds/pages"
        (self.base / "atlas_0.png").write_bytes(b"polluted")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.prepare(formal_pages_only=True)

    def test_page_update_uses_original_assets_and_records_real_delivery(self):
        first = self.prepare()
        page = self.root / "web/index.html"
        page.write_text(page.read_text() + "\n<!-- NEW PREVIEW -->\n")
        second = self.prepare()
        package = Path(second["packagePath"])
        self.assertIn("NEW PREVIEW", (package / "index.html").read_text())
        self.assertEqual((package / "atlas_0.png").read_bytes(), (self.base / "atlas_0.png").read_bytes())
        self.assertNotEqual(first["artifactDigest"], second["artifactDigest"])
        self.assertEqual(first["baseBuildId"], second["baseBuildId"])
        self.assertTrue(Path(first["packagePath"]).is_dir())
        manifest = json.loads((package / "manifest.json").read_text())
        self.assertEqual(manifest["development"]["kind"], "resource-overlay")
        self.assertEqual(manifest["runtime"]["simCodeFingerprint"], "development-overlay-requires-explicit-review")
        self.assert_historical_package_valid(package)

    def test_first_preparation_rejects_changed_original_input(self):
        mf = json.loads((self.base / "manifest.json").read_text())
        source = self.root / "analyze/extracted/ccdzz/data" / mf["inputs"][0]
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "input"):
            self.prepare()

    def test_runtime_refresh_keeps_asset_creator_and_is_not_formal_gate_eligible(self):
        first = self.prepare()
        source = self.root / "src/bugbits/sim/sim.py"
        source.write_text(source.read_text() + "\n# runtime update\n")
        result = self.prepare()
        mf = json.loads((Path(result["packagePath"]) / "manifest.json").read_text())
        bundle = json.loads((Path(result["packagePath"]) / "py-bundle.json").read_text())
        self.assertIn("runtime update", bundle["bugbits/sim/sim.py"])
        self.assertFalse(mf["development"]["formalGateEligible"])
        self.assertEqual(first["baseBuildId"], result["baseBuildId"])
        self.assertNotEqual(mf["development"]["baseAssetCreatorFingerprint"], mf["development"]["runtimeSourceFingerprint"])

    def test_renderer_change_rejects_reuse_and_preserves_current(self):
        self.prepare()
        current = (self.output / "current.json").read_bytes()
        renderer = self.root / "src/bugbits/render/camera.py"
        renderer.write_text(renderer.read_text() + "\n# changed camera\n")
        with self.assertRaisesRegex(ValueError, "renderer"):
            self.prepare()
        self.assertEqual(current, (self.output / "current.json").read_bytes())

    def test_resource_input_change_after_seal_rejects_reuse(self):
        self.prepare()
        mf = json.loads((self.base / "manifest.json").read_text())
        source = self.root / "analyze/extracted/ccdzz/data" / mf["inputs"][0]
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "inputs"):
            self.prepare()

    def test_base_pollution_is_rejected(self):
        (self.base / "unlisted.txt").write_text("polluted")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            self.prepare()

    def test_existing_preview_pollution_preserves_pointer(self):
        result = self.prepare()
        current = (self.output / "current.json").read_bytes()
        (Path(result["packagePath"]) / "atlas_0.png").write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.prepare()
        self.assertEqual(current, (self.output / "current.json").read_bytes())

    def test_illegal_manifest_path_rejected_before_copy(self):
        path = self.base / "manifest.json"
        mf = json.loads(path.read_text())
        mf["files"][0]["path"] = "../outside"
        path.write_text(json.dumps(mf))
        with self.assertRaisesRegex(ValueError, "invalid manifest path"):
            self.prepare()

    def test_symlink_output_rejected(self):
        self.output.parent.mkdir(exist_ok=True)
        self.output.symlink_to(self.root / "web", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare()

    def test_source_symlink_rejected_without_following(self):
        source = self.root / "web/host.js"
        source.unlink()
        source.symlink_to(ROOT / "web/host.js")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare()

    def test_unowned_output_directory_is_never_overwritten(self):
        self.output.mkdir()
        keep = self.output / "user.txt"
        keep.write_text("keep")
        with self.assertRaisesRegex(ValueError, "ownership"):
            self.prepare()
        self.assertEqual(keep.read_text(), "keep")

    def test_interrupted_pointer_publication_keeps_prior_usable_generation(self):
        first = self.prepare()
        current = (self.output / "current.json").read_bytes()
        with patch("os.replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.prepare()
        self.assertEqual(current, (self.output / "current.json").read_bytes())
        self.assertTrue((Path(first["packagePath"]) / "index.html").is_file())
        self.assertFalse(list(self.output.glob(".staging-*")))
        self.assertFalse(list(self.output.glob(".current-*")))

    def test_cli_returns_nonzero_for_protected_output_without_changing_base(self):
        spec = importlib.util.spec_from_file_location("preview", ROOT / "tools/web_preview.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = (self.base / "manifest.json").read_bytes()
        self.assertEqual(module.main(["--base", str(self.base), "--out", str(self.base)]), 2)
        self.assertEqual(original, (self.base / "manifest.json").read_bytes())

    def test_bundle_can_import_the_package_requested_by_worker(self):
        result = self.prepare()
        bundle = json.loads((Path(result["packagePath"]) / "py-bundle.json").read_text())
        runtime = self.root / "runtime-unpacked"
        for relative, content in bundle.items():
            target = runtime / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        completed = subprocess.run([sys.executable, "-B", "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from bugbits.web_bridge import WebBridge; print(WebBridge.__name__)", str(runtime)],
            cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "WebBridge")

    def test_formal_output_descendant_is_rejected(self):
        self.output = self.root / "out/web/preview"
        with self.assertRaisesRegex(ValueError, "protected"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_base_mutation_while_copying_cannot_be_sealed_as_valid_resources(self):
        self.prepare()
        current = (self.output / "current.json").read_bytes()
        copytree = shutil.copytree

        def concurrent_resource_mutation(source, destination, *args, **kwargs):
            if Path(source) == self.base:
                (self.base / "atlas_0.png").write_bytes(b"concurrently corrupted asset")
            return copytree(source, destination, *args, **kwargs)

        with patch("shutil.copytree", side_effect=concurrent_resource_mutation):
            with self.assertRaisesRegex(ValueError, "modified"):
                self.prepare()
        self.assertEqual(current, (self.output / "current.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
