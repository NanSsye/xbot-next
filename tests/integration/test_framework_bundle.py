import base64
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/xbot/services'))
from framework_bundle import build
from framework_manifest import canonical
from release_catalog import discover
from release_worker import tick


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
    (state / 'requests').mkdir(parents=True)
    (state / 'status').mkdir()
    with zipfile.ZipFile(old) as z:
        envelope = z.read("release.json")
    marker = hashlib.sha256(envelope).hexdigest()
    if old_version == '0.1.0':
        web = {'ui/dist/index.html': hashlib.sha256(old_version.encode()).hexdigest()}
        marker = hashlib.sha256(canonical(web)).hexdigest()
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
            if url == '/api/catalog':
                return json.dumps([{'Kind':'framework','Name':'xbot-framework','Digest':package,'Version':'0.1.4'}]).encode()
            assert url.startswith(prefix)
            obj = url[len(prefix) :]
            data = z.read("release.json" if obj == "manifest" else "objects/" + obj)
            assert len(data) <= limit
            return data

        if old_version == '0.1.0':
            (live / 'uv.lock').write_bytes(b'unknown runtime')
            with pytest.raises(ValueError, match='Historical program'):
                discover(tmp_path, public, read)
            assert not (state / 'approved.json').exists()
            assert requests == ['/api/catalog']
            requests.clear()
            (live / 'uv.lock').write_bytes(files['uv.lock'])
        assert discover(tmp_path, public, read)
    assert requests == ['/api/catalog', prefix + "manifest", prefix + hashlib.sha256(b"target").hexdigest()]

    class Service:
        def start(self):
            pass

        def stop(self):
            pass

        def healthy(self, h):
            return (live / ".xbot-release-sha256").read_text().strip() == h and (
                not rollback or h == marker
            )

    tick(tmp_path, Service(), refresh=True)
    proposal = json.loads((state / 'status/preview.json').read_bytes())
    assert proposal['available'] and proposal['version'] == '0.1.4'
    assert proposal['conflicts'] == {'ui/dist/index.html': 'modified'}
    assert (live / 'ui/dist/index.html').read_bytes() == b'user-edit'
    token = proposal['confirmation']
    (state / 'requests' / token).touch()
    tick(tmp_path, Service())
    receipt = json.loads((state / 'status' / (token + '.json')).read_bytes())
    assert receipt['status'] == ('rolled_back' if rollback else 'succeeded')
    assert (live / "ui/dist/index.html").read_bytes() == (b"user-edit" if rollback else b"target")
    assert (live / "database/keep").read_bytes() == b"user-data"
