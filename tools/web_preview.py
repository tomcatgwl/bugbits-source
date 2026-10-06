#!/usr/bin/env python3
"""Safe development overlays, never a formal resource build.

First preparation seals a source-matching formal base. Later preparations may
refresh pages/runtime but reject asset or builder changes. Immutable generation
directories plus an atomic current.json preserve the previous usable preview.
Usage: python3 -B tools/web_preview.py --base out/web --out out/dev-preview
Strict page-only delivery: add --formal-pages-only and use an independent
out/linux-continuation/builds/ container. Python/resource changes are rejected;
the original bundle and runtime fingerprint remain byte-for-byte unchanged.
Serve the returned packagePath, not the preview container. Old generations are
retained deliberately; this tool does not delete prior evidence or formal packs.
"""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("index.html", "host.js", "worker.js", "camera_projection.js", "presentation_material.js", "flower_pose.js", "mesh_scene.js", "NotoSansSC-subset.woff2", "OFL.txt")
RUNTIME_ONLY = {"bot.py", "scriptvm.py", "web_bridge.py", "nav.py", "cli.py"}
MARKER = {"kind": "bugbits-development-preview", "version": 1}
FORMAL_MARKER = {"kind": "bugbits-formal-page-overlay", "version": 1}


def _hash(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"expected regular file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _path(path, root):
    raw = Path(os.path.abspath(path))
    if not raw.is_relative_to(root):
        raise ValueError(f"path outside project: {raw}")
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise ValueError(f"symlink forbidden: {component}")
        if component == root:
            break
    return raw


def _relative(parent, rel, root):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ValueError(f"invalid manifest path: {rel!r}")
    target = _path(parent / rel, root)
    if not target.is_relative_to(parent):
        raise ValueError(f"path escaped package: {rel}")
    return target


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")


def _source_state(root):
    paths = sorted((root / "src/bugbits").rglob("*.py"))
    paths.append(root / "tools/web_build.py")
    paths = sorted(paths)
    all_sources, assets = {}, {}
    h = hashlib.sha256()
    for path in paths:
        path = _path(path, root)
        rel = path.relative_to(root).as_posix()
        digest = _hash(path)
        all_sources[rel] = digest
        h.update(rel.encode())
        h.update(bytes.fromhex(digest))
        module = path.relative_to(root / "src/bugbits").as_posix() if path.is_relative_to(root / "src/bugbits") else None
        if not module or not (module.startswith("sim/") or module in RUNTIME_ONLY):
            assets[rel] = digest
    return h.hexdigest(), all_sources, assets


def _inventory(directory, root):
    entries = []
    for path in sorted(directory.rglob("*")):
        _path(path, root)
        if path.is_file() and path.relative_to(directory).as_posix() != "manifest.json":
            entries.append({"path": path.relative_to(directory).as_posix(), "size": path.stat().st_size, "sha256": _hash(path)})
    return entries


def _check_package(directory, manifest, root):
    for entry in manifest["files"]:
        _relative(directory, entry["path"], root)
    actual = _inventory(directory, root)
    if actual != manifest["files"]:
        raise ValueError("package files missing, modified, duplicated or unregistered")
    digest = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
    if digest != manifest["artifactDigest"]:
        raise ValueError("package artifactDigest mismatch")


def prepare(base, out, *, root=ROOT, formal_pages_only=False):
    """Publish an explicit development or strictly page-only generation."""
    root = Path(root).absolute()
    _path(root, ROOT)
    base, out = _path(base, root), _path(out, root)
    if base == out or base.is_relative_to(out) or out.is_relative_to(base):
        raise ValueError("base and preview must be separate, non-nested directories")
    forbidden = (root, root / "src", root / "web", root / "analyze", root / "out/web", root / "out/web-full")
    if out in forbidden or any(out.is_relative_to(p) for p in (root / "src", root / "web", root / "analyze", root / "out/web", root / "out/web-full")):
        raise ValueError("output is a protected project path")
    if formal_pages_only and not out.is_relative_to(root / "out/linux-continuation/builds"):
        raise ValueError("formal pages-only output must be inside out/linux-continuation/builds")
    manifest_bytes = _path(base / "manifest.json", root).read_bytes()
    manifest = json.loads(manifest_bytes)
    if "development" in manifest:
        raise ValueError("base must be a formal resource package")
    _check_package(base, manifest, root)
    fingerprint, sources, asset_sources = _source_state(root)
    if formal_pages_only and manifest.get("runtime", {}).get("simCodeFingerprint") != fingerprint:
        raise ValueError("formal pages-only requires unchanged Python runtime, assets and builder source")
    data = _path(root / "analyze/extracted/ccdzz/data", root)
    inputs = {rel: _hash(_relative(data, rel, root)) for rel in manifest["inputs"]}
    binding = {"path": str(base), "buildId": manifest["buildId"], "artifactDigest": manifest["artifactDigest"], "manifestHash": hashlib.sha256(manifest_bytes).hexdigest()}
    marker = FORMAL_MARKER if formal_pages_only else MARKER
    metadata_key = "pageOverlay" if formal_pages_only else "development"
    if out.exists():
        if not (out / "preview.json").is_file() or _json(_path(out / "preview.json", root)) != marker:
            raise ValueError("output mode or ownership marker mismatch; containers cannot be mixed")
    else:
        out.mkdir(parents=True)
        _write(out / "preview.json", marker)
    lock_path = _path(out / "prepare.lock", root)
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = out / "current.json"
        if current.exists():
            previous = _json(_path(current, root))
            package = _relative(out, previous["generation"], root)
            old_manifest = _json(_path(package / "manifest.json", root))
            _check_package(package, old_manifest, root)
            if metadata_key not in old_manifest or (formal_pages_only and "development" in old_manifest):
                raise ValueError("current generation mode mismatch")
            seal = old_manifest[metadata_key]["resourceSeal"]
            if seal != {"base": binding, "inputs": inputs, "assetSources": asset_sources}:
                raise ValueError("resource inputs, renderer or builder changed; a fresh resource build is required")
        else:
            if manifest.get("runtime", {}).get("simCodeFingerprint") != fingerprint:
                raise ValueError("first preview requires a source-matching formal base; cannot prove old asset provenance")
            assignments = ast.parse((root / "src/bugbits/web_build.py").read_text()).body
            vendor_hash = next(ast.literal_eval(node.value) for node in assignments
                               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PYODIDE_SHA256" for target in node.targets))
            base_id = hashlib.sha256(json.dumps({"schemaVersion": manifest["schemaVersion"],
                "profile": manifest["profile"], "config": manifest["config"],
                "inputs": sorted(inputs.items()), "pyodide": [manifest["runtime"]["pyodideVersion"], vendor_hash],
                "code": fingerprint}, sort_keys=True).encode()).hexdigest()
            if base_id != manifest["buildId"]:
                raise ValueError("base input provenance mismatch; current originals do not match the resource build")
            seal = {"base": binding, "inputs": inputs, "assetSources": asset_sources}
        generation = "generation-" + uuid.uuid4().hex
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=out))
        pointer = out / (".current-" + uuid.uuid4().hex + ".json")
        try:
            shutil.copytree(base, staging, dirs_exist_ok=True)
            _check_package(staging, manifest, root)
            for name in PAGES:
                shutil.copyfile(_path(root / "web" / name, root), staging / name)
            if not formal_pages_only:
                bundle = {}
                for path in sorted((root / "src/bugbits").rglob("*.py")):
                    rel = path.relative_to(root / "src/bugbits").as_posix()
                    if rel.split("/")[0] == "render" or rel in {"cli.py", "web_build.py"}:
                        continue
                    content = _path(path, root).read_bytes()
                    if hashlib.sha256(content).hexdigest() != sources[path.relative_to(root).as_posix()]:
                        raise ValueError("runtime source changed during preparation")
                    bundle["bugbits/" + rel] = content.decode("utf-8")
                _write(staging / "py-bundle.json", bundle)
                manifest.pop("pageOverlay", None)
                manifest["runtime"]["pyBundleModules"] = len(bundle)
            manifest[metadata_key] = {"kind": "formal-pages-only" if formal_pages_only else "resource-overlay",
                "formalGateEligible": bool(formal_pages_only),
                "resourceSeal": seal, "runtimeSourceFingerprint": fingerprint,
                "generatorFingerprint": _hash(Path(__file__)),
                "runtimeSources": sources, "pages": {name: _hash(staging / name) for name in PAGES},
                "baseAssetCreatorFingerprint": manifest["runtime"]["simCodeFingerprint"]}
            if not formal_pages_only:
                manifest["runtime"]["simCodeFingerprint"] = "development-overlay-requires-explicit-review"
            manifest["files"] = _inventory(staging, root)
            manifest["artifactDigest"] = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
            _write(staging / "manifest.json", manifest)
            _check_package(staging, manifest, root)
            # Check source/base races before publishing a single-source generation.
            if _source_state(root)[0] != fingerprint or _hash(base / "manifest.json") != binding["manifestHash"]:
                raise ValueError("source or base changed during preparation")
            if any(_hash(_relative(data, rel, root)) != digest for rel, digest in inputs.items()):
                raise ValueError("resource input changed during preparation")
            if any(_hash(_path(root / "web" / name, root)) != manifest[metadata_key]["pages"][name] for name in PAGES):
                raise ValueError("page source changed during preparation")
            package = out / generation
            staging.rename(package)
            result = {"generation": generation, "packagePath": str(package), "baseBuildId": manifest["buildId"], "artifactDigest": manifest["artifactDigest"], "development": not formal_pages_only,
                "formalPagesOnly": bool(formal_pages_only)}
            _write(pointer, result)
            os.replace(pointer, current)
            return result
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            if pointer.exists():
                pointer.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--formal-pages-only", action="store_true",
                        help="strict source-matched page delivery; do not refresh Python bundle")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.base, args.out, formal_pages_only=args.formal_pages_only)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"preview rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
