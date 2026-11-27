import importlib
import json
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from xbot.api.v1 import framework


def test_confirm_survives_web_restart(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    worker = importlib.import_module("release_worker")
    mail = tmp_path / "updater"
    for directory in ["status", "requests"]:
        (mail / directory).mkdir(parents=True)
    old, new = "a" * 64, "b" * 64
    for folder, digest in [("release/app", old), ("updater/payload", new)]:
        target = tmp_path / folder
        (target/'ui/dist').mkdir(parents=True)
        (target / "ui/dist/program").write_text(digest)
        (target / ".xbot-release-sha256").write_text(digest)
    live = tmp_path / "release/app"
    plan = {
        "old": old,
        "new": new,
        "version": "2",
        'format':'xbot-delta-v1',
        'changes':{'ui/dist/program':{'before':worker.snapshot(live,['ui'])['ui/dist/program'], 'after':worker.snapshot(mail/'payload',['ui'])['ui/dist/program']}},
    }
    (mail / "approved.json").write_text(json.dumps(plan))
    (live / "ui/dist/program").write_text("user change")
    unrelated = live / 'ui/dist/custom'
    unrelated.write_text('keep my changes')
    original = unrelated.stat()
    monkeypatch.setattr(framework, "MAIL", mail)
    starts = []

    class Service:
        def start(self):
            starts.append(True)

        def stop(self):
            pass

        def healthy(self, digest):
            return (live / ".xbot-release-sha256").read_text().strip() == digest

    @contextmanager
    def web():
        app = FastAPI()
        app.include_router(framework.router, prefix="/update")
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client

    worker.tick(tmp_path, Service(), True)
    (mail / "status/heartbeat").touch()
    if os.getenv("XBOT_TEST_PLAYWRIGHT"):
        browser_app = FastAPI()
        browser_app.include_router(framework.router, prefix="/api/v1/framework-update")
        browser_app.mount(
            "/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "ui/dist", html=True)
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(browser_app, log_level="error"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
            thread.start()
            try:
                browser = subprocess.Popen(
                    [
                        "node",
                        "-e",
                        """
const {chromium}=require(process.env.XBOT_TEST_PLAYWRIGHT);
(async()=>{const b=await chromium.launch({executablePath:process.env.XBOT_TEST_CHROME});try{
const p=await b.newPage();await p.goto(process.argv[1]);const open=p.getByRole('button',{name:/检查更新/});await open.click();
await p.getByText('修改：ui/dist/program').waitFor();await p.getByRole('button',{name:'取消',exact:true}).click();
await open.click();await p.getByRole('button',{name:'应用本次更新'}).click();await p.reload();
await open.click();await p.getByText('已更新，新版服务正常').waitFor({timeout:12000});
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});""",
                        f"http://127.0.0.1:{sock.getsockname()[1]}",
                    ]
                )
                try:
                    for _ in range(200):
                        worker.tick(tmp_path, Service())
                        if browser.poll() is not None:
                            break
                        time.sleep(0.1)
                    assert browser.wait(timeout=2) == 0
                finally:
                    if browser.poll() is None:
                        browser.kill()
                        browser.wait()
            finally:
                server.should_exit = True
                thread.join(5)
        assert len(starts) == 1
        return
    with web() as client:
        proposal = client.get("/update").json()["data"]
        assert proposal["conflicts"] == {"ui/dist/program": "modified"}
        endpoint = "/update/" + proposal["confirmation"]
        assert client.post(endpoint).status_code == 403
        for _ in range(2):
            assert (
                client.post(
                    endpoint,
                    headers={"origin": "http://127.0.0.1", "x-xbot-action": "framework-update"},
                ).status_code
                == 202
            )
    # No web process while the host consumes the pending request.
    for _ in range(2):
        worker.tick(tmp_path, Service())
    with web() as client:
        assert client.get(endpoint).json()["data"] == {"status": "succeeded"}
    assert len(starts) == 1
    assert unrelated.stat().st_mtime_ns == original.st_mtime_ns and unrelated.read_text() == 'keep my changes'


def test_failed_delta_restores_only_changed_paths(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts'))
    delta = importlib.import_module('release_delta')
    live = tmp_path/'release/app'
    payload = tmp_path/'updater/payload'
    for root in (live,payload):
        (root/'ui/dist').mkdir(parents=True)
    for name in ('index','old','custom'):
        (live/'ui/dist'/name).write_text(name)
    for name in ('index','new'):
        (payload/'ui/dist'/name).write_text('updated')
    untouched = (live/'ui/dist/custom').stat()
    old,new='a'*64,'b'*64
    (live/'.xbot-release-sha256').write_text(old)
    plan={'format':'xbot-delta-v1','old':old,'new':new,'changes':{}}
    for name in ('ui/dist/index','ui/dist/old','ui/dist/new'):
        plan['changes'][name]={'before':delta.digest(live/name),'after':delta.digest(payload/name)}
    (live/'ui/dist/index').write_text('my local index')
    class Service:
        def stop(self): pass
        def start(self): pass
        def healthy(self, expected): return expected == old
    token = delta.inspect_delta(live,plan)['confirmation']
    with pytest.raises(RuntimeError,match='previous service verified'):
        delta.apply_delta(tmp_path,plan,token,Service())
    assert (live/'ui/dist/index').read_text()=='my local index'
    assert (live/'ui/dist/old').read_text()=='old'
    assert not (live/'ui/dist/new').exists()
    assert (live/'ui/dist/custom').stat().st_mtime_ns==untouched.st_mtime_ns


def test_proxy_origin_includes_external_port(tmp_path, monkeypatch):
    monkeypatch.setattr(framework, 'MAIL', tmp_path)
    monkeypatch.setenv('XBOT_UPDATE_ORIGIN', 'http://127.0.0.1:18549')
    app = FastAPI()
    app.include_router(framework.router, prefix='/update')
    with TestClient(app, base_url='http://127.0.0.1') as client:
        path = '/update/' + '0' * 64
        for origin, expected in [('http://127.0.0.1:18549', 503), ('http://127.0.0.1:18550', 403)]:
            response = client.post(path, headers={'origin': origin, 'x-xbot-action': 'framework-update'})
            assert response.status_code == expected
