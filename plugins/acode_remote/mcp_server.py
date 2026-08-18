from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shlex
import tomllib
import uuid
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

PLUGIN_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PLUGIN_DIR / "mcp_sender.toml"
SERVER_HELPER = "/app/plugins/acode_remote/send_media.py"
CONTAINER_OUTBOUND_DIR = "/app/plugins/acode_remote/data/outbound"


class SenderError(RuntimeError):
    pass


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
    except OSError as exc:
        raise SenderError("telegram_sender_not_configured") from exc
    config = payload.get("telegram_sender")
    if not isinstance(config, dict):
        raise SenderError("telegram_sender_not_configured")
    ssh_target = str(config.get("ssh_target") or "").strip()
    remote_project_dir = str(config.get("remote_project_dir") or "").strip().rstrip("/")
    container_name = str(config.get("container_name") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.:-]+", ssh_target):
        raise SenderError("invalid_ssh_target")
    if not remote_project_dir.startswith("/") or any(char in remote_project_dir for char in "\r\n\0"):
        raise SenderError("invalid_remote_project_dir")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", container_name):
        raise SenderError("invalid_container_name")
    return {
        "ssh_target": ssh_target,
        "remote_project_dir": remote_project_dir,
        "container_name": container_name,
        "max_bytes": _bounded_int(config.get("max_file_mb"), 49, 1, 49) * 1024 * 1024,
        "timeout": float(_bounded_int(config.get("timeout_seconds"), 120, 10, 300)),
    }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _prepare_local_file(file_path: str, max_bytes: int) -> Path:
    try:
        path = Path(file_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SenderError("file_not_found") from exc
    if not path.is_file():
        raise SenderError("path_is_not_a_file")
    size = path.stat().st_size
    if size <= 0:
        raise SenderError("file_is_empty")
    if size > max_bytes:
        raise SenderError("file_exceeds_49_mb")
    return path


async def _run_process(*args: str, timeout_seconds: float) -> tuple[int, str, str]:
    flags = 0x08000000 if os.name == "nt" else 0
    child_env = dict(os.environ)
    if os.name == "nt":
        child_env.setdefault(
            "PROGRAMDATA",
            f"{child_env.get('SYSTEMDRIVE', 'C:')}\\ProgramData",
        )
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=flags,
        env=child_env,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return 124, "", "timeout"
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        _.decode("utf-8", errors="replace"),
    )


def _process_error(stderr: str, default: str) -> str:
    lowered = stderr.casefold()
    if "permission denied" in lowered:
        return "ssh_auth_failed"
    if "host key verification failed" in lowered or "remote host identification has changed" in lowered:
        return "ssh_host_key_failed"
    if "not recognized" in lowered or "no such file or directory" in lowered:
        return "command_missing"
    if "timeout" in lowered:
        return "command_timeout"
    return default


async def _send_file(file_path: str, caption: str = "") -> dict[str, Any]:
    config = _load_config()
    try:
        local_path = _prepare_local_file(file_path, int(config["max_bytes"]))
    except SenderError as exc:
        return {"ok": False, "error": str(exc)}
    caption = str(caption or "").strip()[:900]
    suffix = local_path.suffix.lower()
    suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""
    temporary_name = f"{uuid.uuid4().hex}{suffix}"
    remote_dir = f"{config['remote_project_dir']}/plugins/acode_remote/data/outbound"
    remote_path = f"{remote_dir}/{temporary_name}"
    container_path = f"{CONTAINER_OUTBOUND_DIR}/{temporary_name}"
    timeout = float(config["timeout"])
    target = str(config["ssh_target"])
    sent = False
    try:
        code, _, error = await _run_process(
            "ssh",
            target,
            f"mkdir -p -- {shlex.quote(remote_dir)}",
            timeout_seconds=timeout,
        )
        if code != 0:
            raise SenderError(_process_error(error, f"remote_directory_failed_{code}"))
        code, _, error = await _run_process(
            "scp",
            "--",
            str(local_path),
            f"{target}:{remote_path}",
            timeout_seconds=timeout,
        )
        if code != 0:
            raise SenderError(_process_error(error, f"upload_failed_{code}"))
        caption_b64 = base64.urlsafe_b64encode(caption.encode("utf-8")).decode("ascii")
        name_b64 = base64.urlsafe_b64encode(local_path.name.encode("utf-8")).decode("ascii")
        code, output, error = await _run_process(
            "ssh",
            target,
            "docker",
            "exec",
            "-e",
            "PYTHONPATH=/app/src",
            str(config["container_name"]),
            "python",
            SERVER_HELPER,
            "--path",
            container_path,
            "--caption-b64",
            caption_b64,
            "--name-b64",
            name_b64,
            timeout_seconds=timeout,
        )
        if code != 0:
            raise SenderError(_process_error(error, f"telegram_send_failed_{code}"))
        try:
            result = json.loads(output.strip().splitlines()[-1])
        except (IndexError, TypeError, ValueError) as exc:
            raise SenderError("invalid_server_response") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise SenderError("telegram_send_failed")
        sent = True
        return {
            "ok": True,
            "kind": str(result.get("kind") or "file"),
            "file_name": local_path.name,
        }
    except SenderError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "file_name": local_path.name,
            "retryable": True,
        }
    finally:
        if sent:
            await _run_process(
                "ssh",
                target,
                f"rm -f -- {shlex.quote(remote_path)}",
                timeout_seconds=min(timeout, 30.0),
            )


server = MCPServer(
    name="telegram_sender",
    title="Telegram 文件发送",
    description="把当前电脑上的单个图片或文件发送到已配置的 Telegram 管理员私聊。",
    instructions=(
        "仅当用户明确要求把指定文件发送到 Telegram 时调用。"
        "必须传入明确的本机文件路径，不要尝试发送密钥、配置、聊天记录或未指定文件。"
    ),
)


@server.tool(
    name="send_to_telegram",
    description=(
        "将一个明确指定的本机文件发送到当前 Telegram 管理员私聊。"
        "图片自动按图片发送，其余格式按文件发送；不会返回 Bot Token。"
    ),
    annotations=ToolAnnotations(
        title="发送文件到 Telegram",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    structured_output=True,
)
async def send_to_telegram(file_path: str, caption: str = "") -> dict[str, Any]:
    return await _send_file(file_path, caption)


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
