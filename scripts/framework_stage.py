"""Prepare an authenticated bundle for the existing host install transaction."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from framework_manifest import decode_manifest, fetch_objects, transfers
from release_delta import checked, digest


def stage(root, item, public_key, read, baseline_path, marker):
    updater = root / "updater"
    prefix = "/api/framework/" + item["Digest"] + "/"
    if not re.fullmatch("[0-9a-f]{64}", item["Digest"]):
        raise ValueError("Invalid bundle identifier")
    old_bytes = baseline_path.read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != marker:
        raise ValueError("Installed baseline does not match release marker")
    old_version = json.loads(old_bytes)["manifest"]["version"]
    def parse(v):
        return tuple(map(int, v.split(".")))
    if parse(item["Version"]) <= parse(old_version):
        return False
    old = decode_manifest(old_bytes, public_key, old_version)
    target_bytes = read(prefix + "manifest", 8 << 20)
    target = decode_manifest(target_bytes, public_key, item["Version"])
    new = hashlib.sha256(target_bytes).hexdigest()
    before, after = [{p: e["sha256"] for p, e in m["files"].items()} for m in (old, target)]
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
