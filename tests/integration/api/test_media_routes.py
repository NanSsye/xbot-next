from fastapi import FastAPI
from fastapi.testclient import TestClient

from xbot.app.main import mount_media


def test_only_conversation_media_is_served(tmp_path):
    app = FastAPI()
    mount_media(app, tmp_path)
    private = tmp_path / 'data' / 'private.txt'
    private.write_text('internal fixture')
    media = tmp_path / 'data/wechat869/media'
    (media / 'sample.jpg').write_bytes(b'media fixture')
    (media / 'link').symlink_to(private)
    with TestClient(app) as client:
        response = client.get('/media/wechat869/media/sample.jpg')
        assert response.content == b'media fixture'
        assert 'sandbox' in response.headers['content-security-policy']
        for path in ('/media/private.txt', '/media/wechat869/media/link', '/files/private.txt'):
            assert client.get(path).status_code == 404
