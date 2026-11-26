"""Prepare the pinned Hermes source for the lockfile's editable dependency."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

from sync_hermes import REPO_ROOT, _safe_extract, _sha256


def prepare(archive: Path | None) -> Path:
    release = json.loads((REPO_ROOT / "configs/hermes-release.json").read_text(encoding="utf-8"))
    cache = REPO_ROOT / ".hermes"
    target = cache / release["tag"]
    stamp = {"commit": release["commit"], "baseVersion": release["tag"][1:],
             "displayVersion": release["tag"][1:], "tag": release["tag"],
             "source": "xbot", "updateMechanism": "external", "payload": "bootstrap"}
    if target.exists():
        if (target / "run_agent.py").is_file() and json.loads(
            (target / "install-stamp.json").read_text(encoding="utf-8")
        ) == stamp:
            return target
        raise RuntimeError(f"Hermes source at {target} does not match the release; move it aside first")

    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=cache) as directory:
        temporary = Path(directory)
        if archive is None:
            archive = temporary / "hermes.zip"
            url = f"https://codeload.github.com/NousResearch/hermes-agent/zip/{release['commit']}"
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        if _sha256(archive) != release["sha256"]:
            raise RuntimeError("Pinned Hermes source archive SHA-256 mismatch")
        source = _safe_extract(archive, temporary / "source")
        (source / "install-stamp.json").write_text(json.dumps(stamp) + "\n", encoding="utf-8")
        source.rename(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    print(prepare(parser.parse_args().archive))
