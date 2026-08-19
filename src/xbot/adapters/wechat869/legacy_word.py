from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from xbot.core.logging import logger


async def convert_legacy_word(path: Path) -> tuple[str, Path, str, int] | None:
    """Convert a downloaded legacy Word file to DOCX for Hermes extraction."""
    if path.suffix.casefold() != ".doc":
        return None
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        logger.warning("Wechat869 legacy Word conversion unavailable: filename={}", path.name)
        return None
    try:
        converted = await asyncio.to_thread(_convert, path, soffice)
    except Exception as exc:
        logger.warning(
            "Wechat869 legacy Word conversion failed: filename={} error_type={}",
            path.name,
            type(exc).__name__,
        )
        return None
    logger.info(
        "Wechat869 legacy Word converted: source={} target={} size={}",
        path.name,
        converted.name,
        converted.stat().st_size,
    )
    return converted.name, converted, _sha256(converted), converted.stat().st_size


def _convert(path: Path, soffice: str) -> Path:
    target = path.with_suffix(".docx")
    if target.is_file() and target.stat().st_mtime_ns >= path.stat().st_mtime_ns:
        return target
    with tempfile.TemporaryDirectory(prefix=".xbot-doc-", dir=path.parent) as temp:
        temp_dir = Path(temp)
        output_dir = temp_dir / "output"
        profile_dir = temp_dir / "profile"
        output_dir.mkdir()
        result = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(output_dir),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = output_dir / f"{path.stem}.docx"
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("LibreOffice did not produce a DOCX file")
        output.replace(target)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
