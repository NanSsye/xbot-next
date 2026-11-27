"""Run from a host-owned installation: python release_worker.py DEPLOYMENT_ROOT."""

import fcntl
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

from release_delta import apply_delta, inspect_delta
from release_switch import XbotDockerService


def publish(path, data):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def snapshot(tree, roots):
    files = {}
    for name in roots:
        if not name or "/" in name or name in {".", ".."}:
            raise ValueError("Invalid managed root")
        root = tree / name
        if root.is_symlink():
            raise ValueError("Unexpected managed symlink")
        if root.is_file():
            with root.open("rb") as stream:
                files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            continue

        def fail(error):
            raise error

        if not root.exists():
            continue
        if not root.is_dir():
            raise ValueError("Unexpected managed file type")
        for folder, dirs, names, fd in os.fwalk(root, onerror=fail):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            if any(
                stat.S_ISLNK(os.stat(d, dir_fd=fd, follow_symlinks=False).st_mode) for d in dirs
            ):
                raise ValueError("Unexpected managed symlink")
            for entry in names:
                handle = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(handle, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(handle).st_mode):
                        raise ValueError("Unexpected managed file type")
                    files[str((Path(folder) / entry).relative_to(tree))] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
    return files


def tick(root, service, refresh=False):
    release = root / "release"
    state = root / "updater/status"
    inbox = root / "updater/requests"
    planfile = root / "updater/approved.json"  # Never mounted inside Xbot.
    view = state / "preview.json"
    if not planfile.exists():
        publish(view, {"available": False})
        return
    plan = json.loads(planfile.read_text())
    if plan.get('format') != 'xbot-delta-v1':
        raise ValueError('Full-directory plans are disabled')

    pending = json.loads(view.read_text()) if view.exists() else {}
    has_request = pending.get("available") and os.path.lexists(inbox / pending["confirmation"])
    if not view.exists() or (refresh and not has_request):
        if (release/'app/.xbot-release-sha256').read_text().strip() != plan['old']:
            publish(view, {"available": False})
            return
        proposal = inspect_delta(release/'app',plan)
        publish(view, {**proposal, "available": True, "version": plan["version"]})
    data = json.loads(view.read_text())
    if not data.get("available"):
        return
    token = data["confirmation"]
    # Only the existence of this exact name matters. Never open mailbox entries.
    if not os.path.lexists(inbox / token):
        return
    receipt = state / (token + ".json")
    if receipt.exists():
        return
    def report(phase):
        try:
            publish(receipt, {"status": "running", "phase": phase})
        except OSError:
            logging.exception('Could not publish update phase %s', phase)

    publish(receipt, {"status": "running", "phase": "verify"})
    try:
        apply_delta(root,plan,token,service,report)
        result = "succeeded"
    except ValueError:
        result = "stale"
    except Exception as error:
        logging.exception("Framework update failed")
        result = (
            "rolled_back" if str(error) == "Update aborted; previous service verified" else "failed"
        )
    publish(receipt, {"status": result})
    publish(view, {"available": False})


def main(root):
    state = root / "updater/status"
    state.mkdir(parents=True, exist_ok=True)
    (root / "updater/requests").mkdir(exist_ok=True)
    with (root / "updater/worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in state.glob("*.json"):
            if path.name != 'preview.json' and json.loads(path.read_text()).get('status') == 'interrupted':
                raise RuntimeError('An interrupted update needs operator recovery')
            if (
                path.name != "preview.json"
                and json.loads(path.read_text()).get("status") == "running"
            ):
                publish(path, {"status": "interrupted"})
                raise RuntimeError("Inspect interrupted switch before restarting the worker")
        count = 0
        while True:
            try:
                if (root / "updater/approved.json").exists():
                    mounts = json.loads(
                        subprocess.check_output(
                            ["docker", "inspect", "--format", "{{json .Mounts}}", "xbot-pro"],
                            timeout=5,
                        )
                    )
                    if not any(
                        m["Destination"] == "/app"
                        and m["Type"] == "bind"
                        and Path(m["Source"]).resolve() == root / "release/app"
                        for m in mounts
                    ):
                        raise ValueError("Target bind does not match deployment")
                tick(root, XbotDockerService(), refresh=count % 60 == 0)
                (state / "heartbeat").touch()
            except Exception:
                logging.exception("Update worker unavailable")
                publish(state / "preview.json", {"available": False, "error": True})
            count += 1
            time.sleep(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(strict=True))
