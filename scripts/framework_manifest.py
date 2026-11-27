"""Validate signed framework metadata and calculate a source-independent transfer plan."""

import base64
import hashlib
import json
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def decode_manifest(envelope, public_key, version):
    document = json.loads(envelope)
    manifest = document["manifest"]
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key.strip(), validate=True))
    key.verify(
        base64.b64decode(document["signature"], validate=True),
        b"xbot-framework-v1\n" + canonical(manifest),
    )
    if manifest["format"] != "xbot-framework-v1" or manifest["version"] != version:
        raise ValueError("Unexpected framework identity")
    files = manifest["files"]
    if not isinstance(files, dict) or not 0 < len(files) <= 50000:
        raise ValueError("Invalid framework inventory")
    for name, entry in files.items():
        parts = name.split("/")
        if any(p in ("", ".", "..") for p in parts) or any(c in name for c in ("\\", ":", "\0")):
            raise ValueError("Invalid framework path")
        if (
            type(entry["size"]) is not int
            or not 0 <= entry["size"] <= 128 << 20
            or not re.fullmatch("[a-f0-9]{64}", entry["sha256"])
        ):
            raise ValueError("Invalid framework file")
    return manifest


def transfers(baseline, target, current):
    """Inventories map managed paths to hashes; None means no trusted baseline exists."""
    if baseline is None:
        raise ValueError("Trusted baseline required")
    changes, conflicts, needed = {}, {}, set()
    for name in sorted(baseline.keys() | target.keys()):
        before, after, found = baseline.get(name), target.get(name), current.get(name)
        if found == after:
            continue
        if before == after:
            # An unchanged official file with a local edit is not part of this update.
            continue
        changes[name] = {"before": before, "after": after}
        if found != before:
            conflicts[name] = (
                "added" if before is None else "removed" if found is None else "modified"
            )
        if after is not None:
            needed.add(after)
    return changes, conflicts, needed


def fetch_objects(manifest, needed, fetch, store):
    sizes = {entry["sha256"]: entry["size"] for entry in manifest["files"].values()}
    for digest in sorted(needed):
        data = fetch(digest, sizes[digest])
        if len(data) != sizes[digest] or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Invalid framework object")
        store(digest, data)
