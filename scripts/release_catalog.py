"""Discover a compatible signed Web delta, without issuing an install request."""

import base64
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from release_delta import checked
from release_signature import verify_release

LIMIT = 16 << 20
CENTER = 'https://xbot.catmi.si'


class FixedOrigin(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(path, limit):
    request = Request(CENTER + path, headers={'User-Agent': 'Xbot-Updater/1.0'})
    with build_opener(FixedOrigin()).open(request, timeout=10) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Release response too large')
    return data


def discover(root, public_key, read=fetch):
    updater = root / 'updater'
    marker = (root / 'release/app/.xbot-release-sha256').read_text().strip()
    approved = updater / 'approved.json'
    previous = json.loads(approved.read_bytes()) if approved.exists() else {}
    current = tuple(map(int, previous['version'].split('.'))) if marker in (previous.get('old'), previous.get('new')) else ()
    catalog = json.loads(read('/api/catalog', 1 << 20))
    bundles = [i for i in catalog if (i.get('Kind'),i.get('Name')) == ('framework','xbot-framework')
               and re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}',i.get('Version',''))]
    if bundles:
        from framework_stage import stage
        if not re.fullmatch('[a-f0-9]{64}',marker):
            raise ValueError('Invalid installed release marker')
        baseline = updater / ('baseline-'+marker+'.json')
        if not baseline.is_file():
            raise ValueError('Trusted full application baseline required')
        item = max(bundles,key=lambda i:tuple(map(int,i['Version'].split('.'))))
        if previous.get('old') == marker and previous.get('payload_digest') == item['Digest']:
            return False
        return stage(root,item,public_key,read,baseline,marker)
    items = [i for i in catalog if
             (i.get('Kind'), i.get('Name')) == ('framework', 'web-from-' + marker)
             and re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}', i.get('Version', ''))]
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key))
    for item in sorted(items, key=lambda i: tuple(map(int, i['Version'].split('.'))), reverse=True)[:12]:
        digest = item['Digest']
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Invalid catalog digest')
        if tuple(map(int, item['Version'].split('.'))) <= current:
            continue
        data = read('/api/download/' + digest, LIMIT)
        verify_release(item, data, key)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = z.infolist()
            if len(entries) > 256 or sum(e.file_size for e in entries) > LIMIT or len(set(z.namelist())) != len(entries):
                raise ValueError('Invalid release archive')
            plan = json.loads(z.read('delta.json'))
            if plan['old'] != marker:
                continue
            if plan['format'] != 'xbot-delta-v1' or plan['version'] != item['Version'] or not re.fullmatch('[a-f0-9]{64}', plan['new']):
                raise ValueError('Invalid release identity')
            changes = plan['changes']
            if not changes or len(changes) > 256 or set(z.namelist()) != {'delta.json', *(p for p,v in changes.items() if v['after'] is not None)}:
                raise ValueError('Invalid archive inventory')
            with tempfile.TemporaryDirectory(dir=updater) as tmp:
                staged = Path(tmp)
                for path, change in changes.items():
                    if not path.startswith('ui/dist/') or not path.endswith(('.html','.js','.css','.svg','.png','.ico','.woff2')):
                        raise ValueError('Unexpected Web release path')
                    destination = checked(staged, path)
                    if change['after'] is not None:
                        content = z.read(path)
                        if hashlib.sha256(content).hexdigest() != change['after']:
                            raise ValueError('Payload digest mismatch')
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
                # Content-addressed staging keeps the previous approval usable on interruption.
                release = updater / ('payload-' + digest)
                if not release.exists():
                    os.rename(staged, release)
                with tempfile.NamedTemporaryFile(dir=updater, delete=False) as handle:
                    handle.write(json.dumps({**plan, 'payload_digest': digest}).encode())
                os.replace(handle.name, approved)
            return True
    return False
