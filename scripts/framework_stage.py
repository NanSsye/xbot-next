"""Prepare an authenticated bundle for the existing host install transaction."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from framework_manifest import canonical, decode_manifest, fetch_objects, transfers
from release_delta import checked, digest


def stage(root, item, public_key, read, baseline_path, marker):
    updater = root / "updater"
    prefix = "/api/framework/" + item["Digest"] + "/"
    if not re.fullmatch("[0-9a-f]{64}", item["Digest"]):
        raise ValueError("Invalid bundle identifier")
    old_bytes = baseline_path.read_bytes()
    old_version = json.loads(old_bytes)["manifest"]["version"]
    old = decode_manifest(old_bytes, public_key, old_version)
    before = {p: e['sha256'] for p, e in old['files'].items()}
    if hashlib.sha256(old_bytes).hexdigest() != marker:
        # A private, operator-provisioned historical envelope can bridge Web-only installations.
        web = {p: h for p, h in before.items() if p.startswith('ui/dist/')}
        if ('ui/dist/index.html' not in web or hashlib.sha256(canonical(web)).hexdigest() != marker
                or not {'src/xbot/__init__.py', 'pyproject.toml', 'uv.lock'} <= before.keys()):
            raise ValueError('Installed baseline does not match release marker')
        live = root / 'release/app'
        for name, expected in before.items():
            if name in web:
                continue
            path = live / name
            if (not path.resolve().is_relative_to(live.resolve()) or path.is_symlink()
                    or digest(path) != expected):
                raise ValueError('Historical program files do not match the signed baseline')
    def parse(v):
        return tuple(map(int, v.split(".")))
    if parse(item["Version"]) <= parse(old_version):
        return False
    target_bytes = read(prefix + "manifest", 8 << 20)
    target = decode_manifest(target_bytes, public_key, item["Version"])
    new = hashlib.sha256(target_bytes).hexdigest()
    after = {p: e['sha256'] for p, e in target['files'].items()}
    changed = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
    # checked() rejects out-of-scope changes, including runtime and migrations.
    current = {p: digest(checked(root / "release/app", p)) for p in changed}
    changes, _, needed = transfers(before, after, current)
    if not changes:
        raise ValueError("No applicable program changes")
    with tempfile.TemporaryDirectory(dir=updater) as temp:
        temp = Path(temp)

        def store(h, data):
            for name, c in changes.items():
                if c["after"] == h:
                    out = checked(temp, name)
                    out.parent.mkdir(exist_ok=True, parents=True)
                    out.write_bytes(data)

        fetch_objects(target, needed, lambda h, n: read(prefix + h, n), store)
        payload = updater / ("payload-" + item["Digest"])
        if not payload.exists():
            os.rename(temp, payload)
        elif any(digest(checked(payload, p)) != e["after"] for p, e in changes.items()):
            raise ValueError("Staged files no longer match update")
    for path, content in [
        (updater / ("baseline-" + new + ".json"), target_bytes),
        (
            updater / "approved.json",
            json.dumps(
                dict(
                    format="xbot-delta-v1",
                    old=marker,
                    new=new,
                    version=item["Version"],
                    changes=changes,
                    payload_digest=item["Digest"],
                )
            ).encode(),
        ),
    ]:
        with tempfile.NamedTemporaryFile(dir=updater, delete=False) as handle:
            handle.write(content)
        os.replace(handle.name, path)
    return True
