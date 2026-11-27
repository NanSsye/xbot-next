"""Publish direct deltas from every archived official UI inventory to one target."""

import argparse
import base64
import getpass
import hashlib
import json
import tempfile
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from build_web_delta import build_from_inventory, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('baselines', 'dist', 'key'):
        parser.add_argument(arg, type=Path)
    parser.add_argument('version')
    parser.add_argument('user')
    args = parser.parse_args()
    after = inventory(args.dist)
    key = load_pem_private_key(args.key.read_bytes(), None)
    origin = 'https://xbot.catmi.si'
    with httpx.Client(base_url=origin, timeout=30, headers={'Origin': origin}) as client:
        client.post('/api/login', json={'User': args.user, 'Password': getpass.getpass()}).raise_for_status()
        existing = {(i['Name'],i['Version']):i for i in client.get('/api/catalog').json() if i['Kind']=='framework'}
        sources = list(args.baselines.glob('*.json'))
        if not sources:
            raise ValueError('No archived baselines')
        for baseline in sorted(sources):
            before = json.loads(baseline.read_bytes())
            if before == after:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                packet = Path(tmp) / 'delta.zip'
                plan = build_from_inventory(before, after, args.dist, packet, args.version)
                name = 'web-from-' + plan['old']
                data = packet.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            signature = key.sign('\n'.join(['xbot-release-v1','framework',name,args.version,digest]).encode())
            if (name,args.version) not in existing:
                client.post('/api/publish', params={'kind':'framework','name':name,'version':args.version,
                            'notes':f'首页布局优化；从 {baseline.stem} 直接更新，无须安装中间版本。'},
                            headers={'X-Xbot-Signature':base64.b64encode(signature).decode()},content=data).raise_for_status()
            print(baseline.stem, '→', args.version, name)


if __name__ == '__main__':
    main()
