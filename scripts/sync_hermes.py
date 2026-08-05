from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import uuid
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "vendor" / "hermes-upstream.json"
VENDOR_DIR = REPO_ROOT / "vendor" / "hermes"


def _load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "repository",
        "tag",
        "version",
        "commit",
        "tree",
        "archiveUrl",
        "archiveSha256",
        "topLevelDirectories",
        "rootFiles",
        "patches",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise RuntimeError(f"Hermes manifest is missing fields: {', '.join(missing)}")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        roots: set[str] = set()
        for info in bundle.infolist():
            parts = Path(info.filename).parts
            if not parts:
                continue
            roots.add(parts[0])
            target = (destination / info.filename).resolve()
            if destination not in target.parents and target != destination:
                raise RuntimeError(f"Archive member escapes staging directory: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError(f"Archive contains unsupported symlink: {info.filename}")
        if len(roots) != 1:
            raise RuntimeError(f"Expected one archive root, found {sorted(roots)}")
        bundle.extractall(destination)
    return destination / next(iter(roots))


def _copy_selected(source: Path, staging: Path, manifest: dict) -> None:
    staging.mkdir(parents=True)
    for name in manifest["topLevelDirectories"]:
        src = source / name
        if not src.is_dir():
            raise RuntimeError(f"Pinned upstream directory is missing: {name}")
        shutil.copytree(src, staging / name)
    for name in manifest["rootFiles"]:
        src = source / name
        if not src.is_file():
            raise RuntimeError(f"Pinned upstream file is missing: {name}")
        shutil.copy2(src, staging / name)


def _apply_patches(staging: Path, manifest_path: Path, manifest: dict) -> None:
    patch_root = manifest_path.parent.parent / "patches" / "hermes"
    for patch_name in manifest["patches"]:
        patch_path = (patch_root / patch_name).resolve()
        if patch_root.resolve() not in patch_path.parents or not patch_path.is_file():
            raise RuntimeError(f"Invalid Hermes patch path: {patch_name}")
        subprocess.run(
            ["git", "apply", "--whitespace=error-all", str(patch_path)],
            cwd=staging,
            check=True,
        )


def _validate_staging(staging: Path, manifest: dict) -> None:
    for required in ("LICENSE", "run_agent.py", "hermes_state.py", "tools/registry.py"):
        if not (staging / required).is_file():
            raise RuntimeError(f"Generated Hermes tree is missing {required}")
    project = tomllib.loads((staging / "pyproject.toml").read_text(encoding="utf-8"))
    actual_version = str(project["project"]["version"])
    if actual_version != manifest["version"]:
        raise RuntimeError(
            f"Hermes version mismatch: expected {manifest['version']}, got {actual_version}"
        )


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        generated_part = any(
            part in {"__pycache__", ".pytest_cache", ".ruff_cache"}
            or part.endswith(".egg-info")
            for part in relative.parts
        )
        if generated_part or path.suffix in {".pyc", ".pyo"}:
            continue
        hashes[relative.as_posix()] = _sha256(path)
    return hashes


def _assert_tree_matches(actual: Path, expected: Path) -> None:
    actual_hashes = _tree_hashes(actual)
    expected_hashes = _tree_hashes(expected)
    missing = sorted(expected_hashes.keys() - actual_hashes.keys())
    extra = sorted(actual_hashes.keys() - expected_hashes.keys())
    changed = sorted(
        path
        for path in actual_hashes.keys() & expected_hashes.keys()
        if actual_hashes[path] != expected_hashes[path]
    )
    if missing or extra or changed:
        details = []
        if missing:
            details.append(f"missing={missing[:10]}")
        if extra:
            details.append(f"extra={extra[:10]}")
        if changed:
            details.append(f"changed={changed[:10]}")
        raise RuntimeError("Hermes vendor differs from the pinned source: " + "; ".join(details))


def _replace_vendor(staging: Path) -> None:
    vendor_parent = VENDOR_DIR.parent.resolve()
    current = VENDOR_DIR.resolve()
    if current.parent != vendor_parent or current.name != "hermes":
        raise RuntimeError(f"Unsafe Hermes destination: {current}")

    backup = vendor_parent / f".hermes-backup-{uuid.uuid4().hex}"
    if backup.exists():
        raise RuntimeError(f"Unexpected Hermes backup collision: {backup}")

    VENDOR_DIR.rename(backup)
    try:
        staging.rename(VENDOR_DIR)
    except Exception:
        if VENDOR_DIR.exists():
            shutil.rmtree(VENDOR_DIR)
        backup.rename(VENDOR_DIR)
        raise
    shutil.rmtree(backup)


def sync(manifest_path: Path, *, verify_only: bool = False) -> None:
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)

    with tempfile.TemporaryDirectory(prefix="xbot-hermes-sync-") as temp_text:
        temp = Path(temp_text)
        archive = temp / "hermes.zip"
        request = urllib.request.Request(
            manifest["archiveUrl"], headers={"User-Agent": "xbot-hermes-sync/1"}
        )
        with urllib.request.urlopen(request, timeout=180) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        actual_hash = _sha256(archive)
        if actual_hash.lower() != str(manifest["archiveSha256"]).lower():
            raise RuntimeError(
                f"Hermes archive hash mismatch: expected {manifest['archiveSha256']}, got {actual_hash}"
            )

        source = _safe_extract(archive, temp / "source")
        staging = VENDOR_DIR.parent / f".hermes-stage-{uuid.uuid4().hex}"
        try:
            _copy_selected(source, staging, manifest)
            _apply_patches(staging, manifest_path, manifest)
            _validate_staging(staging, manifest)
            if verify_only:
                _validate_staging(VENDOR_DIR, manifest)
                _assert_tree_matches(VENDOR_DIR, staging)
            else:
                _replace_vendor(staging)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    action = "Verified" if verify_only else "Synced"
    print(f"{action} Hermes {manifest['version']} from {manifest['tag']} ({manifest['commit'][:12]})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize the vendored Hermes source")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    sync(args.manifest, verify_only=args.verify_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
