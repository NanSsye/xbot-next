"""Build a UI delta from two trusted dist trees (not from a user's installation)."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Unexpected symlink')
        if path.is_file():
            with path.open('rb') as stream:
                result['ui/dist/'+path.relative_to(root).as_posix()] = hashlib.file_digest(stream,'sha256').hexdigest()
    if 'ui/dist/index.html' not in result:
        raise ValueError('Missing UI entry point')
    return result


def build(old, new, output, version):
    before, after = inventory(old), inventory(new)
    return build_from_inventory(before, after, new, output, version)


def build_from_inventory(before, after, new, output, version):
    identify = lambda files: hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    changes = {k:{'before':before.get(k),'after':after.get(k)} for k in sorted(before.keys() | after.keys()) if before.get(k)!=after.get(k)}
    if not changes:
        raise ValueError('Nothing to release')
    manifest = dict(format='xbot-delta-v1',old=identify(before),new=identify(after),version=version,changes=changes)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('delta.json',json.dumps(manifest,sort_keys=True))
        for name,entry in changes.items():
            if entry['after']:
                archive.write(new/name.removeprefix('ui/dist/'),name)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('old','new','output'):
        parser.add_argument(arg,type=Path)
    parser.add_argument('version')
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)),indent=2))
