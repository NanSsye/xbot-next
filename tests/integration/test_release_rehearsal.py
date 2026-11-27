import base64
import hashlib
from io import BytesIO
import zipfile

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from xbot.plugins.loader import PluginLoader
from xbot.skills.loader import SkillLoader
from xbot.services.release_stage import staged_release
from xbot.api.v1 import skills as endpoint
from xbot.app.deps import get_context
from xbot.core.config import PluginConfig, SkillConfig
from xbot.plugins.manager import PluginManager
from xbot.skills.manager import SkillManager


def signed(kind, files):
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    payload = buf.getvalue()
    key = Ed25519PrivateKey.generate()
    digest = hashlib.sha256(payload).hexdigest()
    signature = key.sign(f'xbot-release-v1\n{kind}\nfixture\n1\n{digest}'.encode())
    return dict(Kind=kind, Name='fixture', Version='1', Digest=digest,
                Signature=base64.b64encode(signature).decode()), payload, key.public_key()


@pytest.mark.parametrize('kind', ['plugin', 'skill'])
def test_signed_extension_load(tmp_path, kind):
    manifest = 'name="fixture"\nversion="1"\n'
    files = ({'plugin.toml': manifest + 'entry="main:Fixture"', 'main.py': 'class Fixture: ready=True'}
             if kind == 'plugin' else {'skill.toml': manifest, 'SKILL.md': 'fixture instructions'})
    with staged_release(*signed(kind, files), tmp_path) as stage:
        target = tmp_path / 'installed'
        stage.rename(target)
        if kind == 'plugin':
            loader = PluginLoader()
            assert loader.load_instance(target, loader.load_manifest(target)).ready
        else:
            loader = SkillLoader()
            assert loader.load_manifest(target).name == 'fixture'
            assert loader.load_instructions(target) == 'fixture instructions'


def test_invalid_signed_archive_leaves_no_files(tmp_path):
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        with staged_release(*signed('framework', {'../outside': 'invalid'}), tmp_path):
            pytest.fail('invalid package was staged')
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize('kind,broken', [('plugin', False), ('skill', False), ('plugin', True)])
def test_install_route(tmp_path, monkeypatch, kind, broken):
    monkeypatch.chdir(tmp_path)
    name_version = 'name="fixture"\nversion="1"\n'
    files = ({'plugin.toml': name_version+'entry="main:Fixture"',
              'main.py': 'from xbot.plugins.base import PluginBase\nclass Fixture(PluginBase): pass'}
             if kind == 'plugin' else {'skill.toml': name_version, 'SKILL.md': 'instructions'})
    if broken:
        files['main.py'] = 'raise RuntimeError("fixture")'
    item, archive, pub = signed(kind, files)
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs/release-signing.pub').write_bytes(base64.b64encode(pub.public_bytes_raw()))
    app = FastAPI()
    app.include_router(endpoint.router, prefix='/skills')
    ctx = SimpleNamespace(plugins=PluginManager(PluginConfig(directory=str(tmp_path/'plugins'))),
                          skills=SkillManager(SkillConfig(directory=str(tmp_path/'skills'))))
    app.dependency_overrides[get_context] = lambda: ctx
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda r: httpx.Response(200,json=[item]) if r.url.path == '/api/catalog'
                                    else httpx.Response(200,content=archive))
    monkeypatch.setattr(endpoint.httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
    client = TestClient(app)
    path = '/skills/catalog/'+item['Digest']+'/install'
    headers = {'Origin': 'http://testserver', 'x-xbot-action':'install'}
    assert client.post(path).status_code == 403
    response = client.post(path, headers=headers)
    assert response.status_code == (422 if broken else 200), response.text
    if broken:
        assert not (tmp_path/'plugins/fixture').exists()
    else:
        installed = ctx.plugins.list_plugins() if kind == 'plugin' else ctx.skills.list_skills()
        assert any(i['name']=='fixture' and i['enabled'] for i in installed)
        assert client.post(path, headers=headers).status_code == 409
