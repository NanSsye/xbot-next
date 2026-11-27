import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from framework_manifest import fetch_objects, transfers


@pytest.mark.parametrize("base", [{"a": "v1"}, {"a": "v2", "b": "current"}])
def test_direct_transfer(base):
    target = {"a": "latest", "b": "current", "copy": "latest"}
    current = {**base, "a": "custom", "private": "untouched"}
    changes, conflicts, needed = transfers(base, target, current)
    assert needed == ({"latest"} if "b" in base else {"latest", "current"})
    assert conflicts == {"a": "modified"} and "private" not in changes
    assert current["a"] == "custom"


def test_requires_trusted_baseline():
    with pytest.raises(ValueError):
        transfers(None, {}, {})


def test_corrupt_object_not_stored():
    digest = hashlib.sha256(b"good").hexdigest()
    with pytest.raises(ValueError):
        fetch_objects(
            {"files": {"a": {"sha256": digest, "size": 4}}},
            {digest},
            lambda *_: b"evil",
            lambda *_: pytest.fail("stored corrupt content"),
        )
