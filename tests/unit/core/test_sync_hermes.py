from pathlib import Path

import pytest

from scripts.sync_hermes import _assert_tree_matches, _load_manifest, _safe_extract


def test_hermes_manifest_pins_immutable_upstream_source():
    root = Path(__file__).resolve().parents[3]
    manifest = _load_manifest(root / "vendor" / "hermes-upstream.json")

    assert manifest["tag"].startswith("v2026.")
    assert len(manifest["commit"]) == 40
    assert len(manifest["tree"]) == 40
    assert len(manifest["archiveSha256"]) == 64
    assert manifest["patches"] == []


def test_safe_extract_rejects_path_traversal(tmp_path):
    import zipfile

    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("hermes/../../outside.txt", "unsafe")

    try:
        _safe_extract(archive, tmp_path / "extract")
    except RuntimeError as exc:
        assert "escapes staging directory" in str(exc)
    else:
        raise AssertionError("path traversal archive was accepted")


def test_tree_verification_detects_changed_missing_and_extra_files(tmp_path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "same.txt").write_text("same", encoding="utf-8")
    (actual / "same.txt").write_text("same", encoding="utf-8")
    _assert_tree_matches(actual, expected)

    (actual / "same.txt").write_text("changed", encoding="utf-8")
    (actual / "extra.txt").write_text("extra", encoding="utf-8")
    (expected / "missing.txt").write_text("missing", encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        _assert_tree_matches(actual, expected)

    message = str(exc_info.value)
    assert "changed=['same.txt']" in message
    assert "extra=['extra.txt']" in message
    assert "missing=['missing.txt']" in message
