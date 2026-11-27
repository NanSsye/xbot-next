import hashlib
import os
import shutil
import subprocess
import sys
import time
from importlib import import_module
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts.release_switch import preview, switch
from xbot.app.main import create_app


@pytest.mark.parametrize('case', ['success', 'decline', 'stale', 'bad', 'rollback_failure'])
def test_switch(tmp_path, case):
    live = tmp_path / 'app'
    candidate = tmp_path / 'candidate'
    old, new = 'a' * 64, 'b' * 64
    for path, version in [(live, old), (candidate, new)]:
        path.mkdir()
        (path / 'identity').write_text(version)

    def snapshot(root):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}

    baseline = snapshot(live)
    (live / 'custom').write_text('local change')
    proposal = preview(baseline, snapshot(live), old, new)
    assert proposal['conflicts'] == {'custom': 'added'}
    probes = []

    class Service:
        def start(self): pass
        def stop(self): pass

        def healthy(self, expected):
            probes.append(expected)
            return (live / 'identity').read_text() == expected and (
                len(probes) == 1 or case == 'success' or (case == 'bad' and expected == old)
            )

    def confirm():
        switch(tmp_path, baseline, snapshot, old, new, proposal['confirmation'], Service())

    if case == 'success':
        confirm()
        assert probes == [old, new] and not (live / 'custom').exists()
        assert (tmp_path / 'previous/custom').read_text() == 'local change'
    elif case == 'stale':
        (live / 'custom').write_text('later')
        with pytest.raises(ValueError, match='review'):
            confirm()
        assert not probes and (live / 'custom').read_text() == 'later'
    elif case == 'decline':
        assert not (tmp_path / 'previous').exists() and (live / 'custom').read_text() == 'local change'
    else:
        message = 'previous service verified' if case == 'bad' else 'operator intervention'
        with pytest.raises(RuntimeError, match=message):
            confirm()
        assert probes == [old, new, old] and (live / 'custom').read_text() == 'local change'


def test_real_app_readiness(tmp_path, monkeypatch):
    config = tmp_path / 'xbot.toml'
    config.write_text(f'[storage]\ntype="sqlite"\nurl="sqlite+aiosqlite:///{tmp_path}/test.db"\n'
                      '[queue]\ntype="memory"\n[api]\nauth_enabled=false\n')
    monkeypatch.setenv('XBOT_CONFIG_FILE', str(config))
    monkeypatch.setenv('XBOT_RUNTIME_CONFIG_FILE', str(tmp_path / 'runtime.json'))
    monkeypatch.setattr(import_module('xbot.app.lifespan'), '__file__', str(tmp_path / 'src/xbot/app/lifespan.py'))
    marker = tmp_path / '.xbot-release-sha256'
    app = create_app()
    with TestClient(app) as client:
        assert client.get('/api/v1/system/readiness').status_code == 503
    marker.write_text('a' * 64)
    with TestClient(app) as client:
        marker.write_text('b' * 64)
        response = client.get('/api/v1/system/readiness')
        assert response.status_code == 200 and response.json() == {'ready': True, 'release': 'a' * 64}


@pytest.mark.parametrize('broken', [False, True])
def test_switch_running_xbot(tmp_path, broken):
    repo = Path(__file__).resolve().parents[2]
    live = tmp_path / 'app'
    old, new = 'a' * 64, 'b' * 64
    for name, digest in [('app', old), ('candidate', new)]:
        root = tmp_path / name
        shutil.copytree(repo / 'src/xbot', root / 'src/xbot', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(repo / 'migrations', root / 'migrations')
        shutil.copy2(repo / 'alembic.ini', root / 'alembic.ini')
        (root / '.xbot-release-sha256').write_text(digest)
        if broken and name == 'candidate':
            (root / 'src/xbot/app/main.py').write_text('raise RuntimeError("failed startup fixture")\n')

    config = tmp_path / 'test.toml'
    config.write_text(f'[storage]\ntype="sqlite"\nurl="sqlite+aiosqlite:///{tmp_path}/test.db"\n'
                      '[queue]\ntype="memory"\n[api]\nauth_enabled=false\n'
                      f'[plugins]\ndirectory="{tmp_path}/plugins"\n[skills]\ndirectory="{tmp_path}/skills"\n')
    # UDS path lengths are limited on macOS; use a short private directory.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(dir='/tmp') as private:
        sock = Path(private) / 'app.sock'

        class Process:
            child = None

            def start(self):
                sock.unlink(missing_ok=True)
                self.child = subprocess.Popen(
                    [sys.executable, '-m', 'uvicorn', 'xbot.app.main:app', '--uds', str(sock)],
                    cwd=repo, env={**os.environ, 'PYTHONPATH': str(live / 'src'), 'XBOT_CONFIG_FILE': str(config),
                                   'XBOT_RUNTIME_CONFIG_FILE': str(tmp_path / 'runtime.json')},
                    stdout=subprocess.DEVNULL,
                )

            def stop(self):
                if self.child and self.child.poll() is None:
                    self.child.terminate()
                    self.child.wait(timeout=10)

            def healthy(self, expected):
                with httpx.Client(transport=httpx.HTTPTransport(uds=str(sock)), timeout=2) as client:
                    for _ in range(100):
                        if self.child.poll() is not None:
                            return False
                        try:
                            r = client.get('http://localhost/api/v1/system/readiness')
                            if r.status_code == 200 and r.json() == {'ready': True, 'release': expected}:
                                return True
                        except httpx.TransportError:
                            pass
                        time.sleep(.1)
                return False

        def snapshot(tree):
            return {'marker': (tree / '.xbot-release-sha256').read_text()}

        service = Process()
        service.start()
        try:
            baseline = snapshot(live)
            confirmation = preview(baseline, baseline, old, new)['confirmation']
            if broken:
                with pytest.raises(RuntimeError, match='previous service verified'):
                    switch(tmp_path, baseline, snapshot, old, new, confirmation, service)
            else:
                switch(tmp_path, baseline, snapshot, old, new, confirmation, service)
            assert service.healthy(old if broken else new)
        finally:
            service.stop()
