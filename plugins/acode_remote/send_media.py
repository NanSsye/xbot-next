from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from xbot.adapters.telegram.client import TelegramApiError, TelegramBotClient
from xbot.core.config import load_settings

PLUGIN_DIR = Path(__file__).resolve().parent
OUTBOUND_DIR = (PLUGIN_DIR / "data" / "outbound").resolve()
MAX_BYTES = 49 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _decode_text(value: str, limit: int) -> str:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid_base64_text") from exc
    return decoded.strip()[:limit]


def _validated_path(value: str) -> Path:
    try:
        path = Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("file_not_found") from exc
    if not path.is_file() or not path.is_relative_to(OUTBOUND_DIR):
        raise ValueError("file_outside_outbound_directory")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid_file_size")
    return path


def _target_user_ids(settings: Any) -> list[str]:
    users: list[str] = []
    config_path = PLUGIN_DIR / "config.toml"
    try:
        with config_path.open("rb") as stream:
            plugin_config = tomllib.load(stream).get("acode_remote", {})
    except (OSError, tomllib.TOMLDecodeError):
        plugin_config = {}
    configured = plugin_config.get("allowed_user_ids") if isinstance(plugin_config, dict) else None
    source = configured if isinstance(configured, list) and configured else settings.adapters.telegram.admin_user_ids
    for item in source or []:
        value = str(item).strip()
        if value and value not in users:
            users.append(value)
    return users


async def _send(path: Path, caption: str, file_name: str) -> dict[str, Any]:
    settings = load_settings()
    targets = _target_user_ids(settings)
    if len(targets) != 1:
        return {"ok": False, "error": "telegram_target_not_unique"}
    kind = "image" if path.suffix.lower() in IMAGE_SUFFIXES else "file"
    safe_name = re.sub(r"[\x00-\x1f\x7f]", "", Path(file_name).name).strip()[:120]
    client = TelegramBotClient(settings.adapters.telegram)
    try:
        result = await client.send_media(
            kind=kind,
            chat_id=targets[0],
            source=str(path),
            caption=caption,
            file_name=safe_name or path.name,
        )
        return {"ok": bool(result.get("message_id")), "kind": kind}
    except TelegramApiError as exc:
        return {"ok": False, "error": "telegram_api_error", "error_code": exc.error_code}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    finally:
        await client.close()


async def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--path", required=True)
    parser.add_argument("--caption-b64", default="")
    parser.add_argument("--name-b64", required=True)
    args = parser.parse_args()
    path: Path | None = None
    result: dict[str, Any] = {"ok": False, "error": "telegram_send_failed"}
    try:
        path = _validated_path(args.path)
        caption = _decode_text(args.caption_b64, 900) if args.caption_b64 else ""
        file_name = _decode_text(args.name_b64, 120)
        result = await _send(path, caption, file_name)
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__}
    finally:
        if path is not None and result.get("ok") is True:
            path.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
