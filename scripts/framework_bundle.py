"""Create one signed ZIP from a clean, curated framework distribution (not a live /app)."""

import argparse
import base64
import hashlib
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from framework_manifest import canonical


def build(distribution, output, key, version):
    allowed = {
        "src",
        "ui",
        "vendor",
        "migrations",
        "scripts",
        "plugins",
        "skills",
        "configs",
        "pyproject.toml",
        "uv.lock",
        "alembic.ini",
        "LICENSE",
        "README.md",
    }
    files, objects = {}, {}
    for path in sorted(distribution.rglob("*")):
        rel = path.relative_to(distribution)
        if (
            path.is_symlink()
            or rel.parts[0] not in allowed
            or any(p in {".git", ".env", "__pycache__", ".venv"} for p in rel.parts)
        ):
            raise ValueError(f"Unexpected distribution path: {rel}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Not a regular file: {rel}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files[rel.as_posix()] = {"sha256": digest, "size": path.stat().st_size}
        objects[digest] = path
    if (
        not {"src/xbot/__init__.py", "ui/dist/index.html", "uv.lock", "pyproject.toml"}
        <= files.keys()
    ):
        raise ValueError("Incomplete distribution")
    plan = {"format": "xbot-framework-v1", "version": version, "files": files}
    signature = key.sign(b"xbot-framework-v1\n" + canonical(plan))
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "release.json",
            canonical({"manifest": plan, "signature": base64.b64encode(signature).decode()}),
        )
        for digest, path in objects.items():
            z.write(path, "objects/" + digest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("distribution", "output", "key"):
        parser.add_argument(arg, type=Path)
    parser.add_argument("version")
    args = parser.parse_args()
    build(
        args.distribution,
        args.output,
        load_pem_private_key(args.key.read_bytes(), None),
        args.version,
    )
