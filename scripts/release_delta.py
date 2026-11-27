"""File-level transactions for a trusted, already verified delta."""

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from release_switch import preview


def digest(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Unexpected file type')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(root, name):
    if not (name.startswith('ui/dist/') or name.startswith('src/xbot/')):
        raise ValueError('Unmanaged path')
    p = root
    for part in name.split('/'):
        if part in {'', '.', '..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+', part):
            raise ValueError('Invalid path')
        p = p / part
        if p.is_symlink():
            raise ValueError('Unexpected symlink')
    return p


def inspect_delta(live, plan):
    changes = plan['changes']
    if plan.get('format') != 'xbot-delta-v1' or not changes:
        raise ValueError('Expected incremental release')
    before, current = {}, {}
    for name, entry in changes.items():
        a, b = entry['before'], entry['after']
        if a == b or any(x is not None and not re.fullmatch('[a-f0-9]{64}', x) for x in (a,b)):
            raise ValueError('Invalid delta digest')
        if a is not None:
            before[name] = a
        found = digest(checked(live,name))
        if found is not None:
            current[name] = found
    return preview(before,current,plan['old'],plan['new'])


def replace_file(source, target):
    if source is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source,tmp)
        os.chmod(tmp, source.stat().st_mode & 0o777)
        os.replace(tmp,target)
    finally:
        Path(tmp).unlink(missing_ok=True)


def apply_delta(root, plan, token, service, report=lambda phase: None):
    live = root/'release/app'
    payload = root/'updater/payload'
    if 'payload_digest' in plan:
        if not re.fullmatch('[a-f0-9]{64}', plan['payload_digest']):
            raise ValueError('Invalid payload identity')
        payload = root/'updater'/('payload-' + plan['payload_digest'])
    changes = plan['changes']
    def confirm():
        if inspect_delta(live,plan)['confirmation'] != token:
            raise ValueError('Preview changed')
    confirm()
    for name, entry in changes.items():
        if digest(checked(payload,name)) != entry['after']:
            raise ValueError('Invalid delta payload')
    marker = live/'.xbot-release-sha256'
    if marker.is_symlink() or marker.read_text().strip()!=plan['old'] or not service.healthy(plan['old']):
        raise RuntimeError('Cannot verify current installation')
    backup = Path(tempfile.mkdtemp(prefix='delta-backup-',dir=root/'updater'))
    applied = []
    marker_changed = False
    service.stop()
    try:
        report('apply')
        confirm()
        shutil.copy2(marker,backup/'marker')
        for name, entry in changes.items():
            dst = checked(live,name)
            if dst.exists():
                saved = backup/'files'/name
                saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(dst,saved)
            replace_file(checked(payload,name) if entry['after'] else None,dst)
            applied.append(name)
        next_marker = backup/'next-marker'
        next_marker.write_text(plan['new']+'\n')
        replace_file(next_marker,marker)
        marker_changed = True
        report('restart')
        service.start()
        report('health')
        if not service.healthy(plan['new']):
            raise RuntimeError('New service failed readiness')
    except Exception as error:
        report('restore')
        service.stop()
        for name in reversed(applied):
            saved = backup/'files'/name
            replace_file(saved if saved.exists() else None,checked(live,name))
        if marker_changed:
            replace_file(backup/'marker',marker)
        service.start()
        if not service.healthy(plan['old']):
            raise RuntimeError('Restored service failed readiness') from error
        raise RuntimeError('Update aborted; previous service verified') from error
