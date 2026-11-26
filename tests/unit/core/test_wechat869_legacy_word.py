from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xbot.adapters.wechat869 import legacy_word


@pytest.mark.anyio
async def test_convert_legacy_word_uses_isolated_libreoffice_profile(tmp_path, monkeypatch):
    source = tmp_path / "工程说明.doc"
    source.write_bytes(b"legacy-word")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        output_dir = Path(command[command.index("--outdir") + 1])
        (output_dir / "工程说明.docx").write_bytes(b"converted-docx")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(legacy_word.shutil, "which", lambda command: "/usr/bin/soffice")
    monkeypatch.setattr(legacy_word.subprocess, "run", fake_run)

    result = await legacy_word.convert_legacy_word(source)

    assert result is not None
    filename, converted, digest, size = result
    assert filename == "工程说明.docx"
    assert converted.read_bytes() == b"converted-docx"
    assert len(digest) == 64
    assert size == len(b"converted-docx")
    assert calls[0][1].startswith("-env:UserInstallation=file:")
    assert calls[0][2:5] == ["--headless", "--convert-to", "docx"]


@pytest.mark.anyio
async def test_convert_legacy_word_returns_none_without_libreoffice(tmp_path, monkeypatch):
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy-word")
    monkeypatch.setattr(legacy_word.shutil, "which", lambda command: None)

    assert await legacy_word.convert_legacy_word(source) is None


@pytest.mark.anyio
async def test_convert_legacy_word_ignores_modern_docx(tmp_path):
    source = tmp_path / "modern.docx"
    source.write_bytes(b"modern-word")

    assert await legacy_word.convert_legacy_word(source) is None
