import base64
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from framework_bundle import build
from framework_stage import stage
from release_delta import apply_delta, inspect_delta


def packet(tmp, version, files, key):
    tree = tmp / ("distribution-" + version)
    for path, data in files.items():
        dst = tree / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    archive = tmp / (version + ".zip")
    build(tree, archive, key, version)
    return archive


@pytest.mark.parametrize(
    ("old_version", "rollback"), [("0.1.0", False), ("0.1.2", False), ("0.1.2", True)]
)
def test_direct_update_and_rollback(tmp_path, old_version, rollback):
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes_raw())
    files = {
        "src/xbot/__init__.py": b"",
        "ui/dist/index.html": old_version.encode(),
        "pyproject.toml": b"[project]",
        "uv.lock": b"lock",
    }
    old = packet(tmp_path, old_version, files, key)
    new = packet(tmp_path, "0.1.4", {**files, "ui/dist/index.html": b"target"}, key)
    live = tmp_path / "release/app"
    live.parent.mkdir()
    (tmp_path / ("distribution-" + old_version)).rename(live)
    (live / "database").mkdir()
    (live / "database/keep").write_bytes(b"user-data")
    state = tmp_path / "updater"
    state.mkdir()
    with zipfile.ZipFile(old) as z:
        envelope = z.read("release.json")
    marker = hashlib.sha256(envelope).hexdigest()
    baseline = state / ("baseline-" + marker + ".json")
    baseline.write_bytes(envelope)
    (live / ".xbot-release-sha256").write_text(marker)
    (live / "ui/dist/index.html").write_bytes(b"user-edit")
    package = hashlib.sha256(new.read_bytes()).hexdigest()
    prefix = "/api/framework/" + package + "/"
    requests = []
    with zipfile.ZipFile(new) as z:

        def read(url, limit):
            requests.append(url)
            assert url.startswith(prefix)
            obj = url[len(prefix) :]
            data = z.read("release.json" if obj == "manifest" else "objects/" + obj)
            assert len(data) <= limit
            return data

        assert stage(
            tmp_path, {"Digest": package, "Version": "0.1.4"}, public, read, baseline, marker
        )
    assert requests == [prefix + "manifest", prefix + hashlib.sha256(b"target").hexdigest()]
    plan = json.loads((state / "approved.json").read_bytes())
    proposal = inspect_delta(live, plan)
    assert proposal["conflicts"] == {"ui/dist/index.html": "modified"}
    assert (live / "ui/dist/index.html").read_bytes() == b"user-edit"

    class Service:
        def start(self):
            pass

        def stop(self):
            pass

        def healthy(self, h):
            return (live / ".xbot-release-sha256").read_text().strip() == h and (
                not rollback or h == marker
            )

    if rollback:
        with pytest.raises(RuntimeError, match="previous service verified"):
            apply_delta(tmp_path, plan, proposal["confirmation"], Service())
    else:
        apply_delta(tmp_path, plan, proposal["confirmation"], Service())
    assert (live / "ui/dist/index.html").read_bytes() == (b"user-edit" if rollback else b"target")
    assert (live / "database/keep").read_bytes() == b"user-data"
