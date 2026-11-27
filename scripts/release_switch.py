"""Host-side primitives for already authenticated, privately staged releases.

No network listener or CLI: only a trusted host coordinator may supply the
baseline, candidate directory and service controls. Never run inside /app.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path


class XbotDockerService:
    """Fixed production target. Docker access stays with the host process."""

    def stop(self):
        subprocess.run(['docker', 'stop', '-t', '30', 'xbot-pro'], check=True, timeout=45)

    def start(self):
        subprocess.run(['docker', 'start', 'xbot-pro'], check=True, timeout=30)

    def healthy(self, expected):
        probe = (
            'import urllib.request; '
            'c=urllib.request.build_opener(urllib.request.ProxyHandler({})); '
            'r=c.open("http://127.0.0.1:8548/api/v1/system/readiness",timeout=4); '
            'print(r.read(512).decode())'
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(['docker', 'exec', 'xbot-pro', '/app/.venv/bin/python', '-I', '-c', probe],
                                        capture_output=True, timeout=6, check=True)
                if json.loads(result.stdout) == {'ready': True, 'release': expected}:
                    return True
            except (subprocess.SubprocessError, ValueError):
                pass  # A starting container may not yet accept requests.
            time.sleep(1)
        return False


def preview(baseline: dict[str, str], snapshot: dict[str, str], old: str, new: str) -> dict:
    if old == new or not all(re.fullmatch('[0-9a-f]{64}', value) for value in (old, new)):
        raise ValueError('Invalid release identity')
    changes = {path: 'added' if path not in baseline else 'removed' if path not in snapshot else 'modified'
               for path in sorted(baseline.keys() | snapshot.keys()) if baseline.get(path) != snapshot.get(path)}
    encoded = json.dumps([old, new, baseline, snapshot], sort_keys=True, separators=(',', ':')).encode()
    return {'confirmation': hashlib.sha256(encoded).hexdigest(), 'conflicts': changes}


def switch(parent: Path, baseline, snapshot, old, new, confirmation, service):
    """Both app and candidate are complete trees on the same host filesystem.

    Caller owns candidate validation, dependency compatibility, private state
    handoff and excludes concurrent host edits while taking the final snapshot.
    The previous tree is retained; leftover trees block future transactions.
    """
    live, candidate, previous, rejected = (parent / name for name in ('app', 'candidate', 'previous', 'rejected'))
    with (parent / '.switch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not all(p.is_dir() and not p.is_symlink() for p in (live, candidate)) or any(
            os.path.lexists(p) for p in (previous, rejected)
        ):
            raise RuntimeError('Installation requires recovery or a fresh staging directory')

        def check_confirmation():
            if preview(baseline, snapshot(live), old, new)['confirmation'] != confirmation:
                raise ValueError('Local code changed; review the complete update again')

        check_confirmation()
        if not service.healthy(old):
            raise RuntimeError('Cannot verify current installation')
        try:
            service.stop()
            check_confirmation()
            live.rename(previous)
            candidate.rename(live)
            service.start()
            if not service.healthy(new):
                raise RuntimeError('New service failed readiness')
        except Exception as failure:
            if previous.exists():
                service.stop()
                if live.exists():
                    live.rename(rejected)
                previous.rename(live)
            service.start()
            if not service.healthy(old):
                raise RuntimeError('Restored service failed readiness; operator intervention required') from failure
            raise RuntimeError('Update aborted; previous service verified') from failure
