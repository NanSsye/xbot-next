from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_module(file_name: str, module_name: str):
    path = Path(__file__).resolve().parents[3] / "plugins" / "acode_remote" / file_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sender_config_and_local_file_validation(tmp_path: Path) -> None:
    module = load_module("mcp_server.py", "xbot_acode_sender_test")
    config_path = tmp_path / "mcp_sender.toml"
    config_path.write_text(
        """
[telegram_sender]
ssh_target = "root@192.168.31.19"
remote_project_dir = "/srv/xbot-next"
container_name = "xbot-next-app"
max_file_mb = 2
timeout_seconds = 30
""".strip(),
        encoding="utf-8",
    )
    config = module._load_config(config_path)
    assert config["max_bytes"] == 2 * 1024 * 1024
    file_path = tmp_path / "result.png"
    file_path.write_bytes(b"png")
    assert module._prepare_local_file(str(file_path), config["max_bytes"]) == file_path.resolve()
    with pytest.raises(module.SenderError, match="file_exceeds_49_mb"):
        module._prepare_local_file(str(file_path), 1)


@pytest.mark.asyncio
async def test_sender_uploads_one_file_without_exposing_caption(tmp_path: Path) -> None:
    module = load_module("mcp_server.py", "xbot_acode_sender_send_test")
    file_path = tmp_path / "测试图片.png"
    file_path.write_bytes(b"safe-image")
    module._load_config = lambda: {
        "ssh_target": "root@192.168.31.19",
        "remote_project_dir": "/srv/xbot-next",
        "container_name": "xbot-next-app",
        "max_bytes": 1024,
        "timeout": 30.0,
    }
    calls: list[tuple[str, ...]] = []

    async def run_process(*args: str, timeout_seconds: float):
        calls.append(args)
        if "docker" in args:
            return 0, json.dumps({"ok": True, "kind": "image"}), ""
        return 0, "", ""

    module._run_process = run_process
    result = await module._send_file(str(file_path), "只用于测试")

    assert result == {"ok": True, "kind": "image", "file_name": "测试图片.png"}
    assert any(call[0] == "scp" for call in calls)
    rendered = " ".join(" ".join(call) for call in calls)
    assert "只用于测试" not in rendered
    assert "rm -f" in rendered


@pytest.mark.asyncio
async def test_sender_preserves_remote_file_when_telegram_send_fails(tmp_path: Path) -> None:
    module = load_module("mcp_server.py", "xbot_acode_sender_retry_test")
    file_path = tmp_path / "result.txt"
    file_path.write_text("retry", encoding="utf-8")
    module._load_config = lambda: {
        "ssh_target": "root@192.168.31.19",
        "remote_project_dir": "/srv/xbot-next",
        "container_name": "xbot-next-app",
        "max_bytes": 1024,
        "timeout": 30.0,
    }
    calls: list[tuple[str, ...]] = []

    async def run_process(*args: str, timeout_seconds: float):
        calls.append(args)
        if "docker" in args:
            return 1, "", "telegram failed"
        return 0, "", ""

    module._run_process = run_process
    result = await module._send_file(str(file_path))

    assert result["ok"] is False
    assert result["retryable"] is True
    assert not any("rm -f" in " ".join(call) for call in calls)


def test_server_helper_only_accepts_outbound_directory(tmp_path: Path) -> None:
    module = load_module("send_media.py", "xbot_acode_send_media_test")
    outbound = tmp_path / "outbound"
    outbound.mkdir()
    module.OUTBOUND_DIR = outbound.resolve()
    inside = outbound / "file.txt"
    inside.write_text("ok", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")

    assert module._validated_path(str(inside)) == inside.resolve()
    with pytest.raises(ValueError, match="file_outside_outbound_directory"):
        module._validated_path(str(outside))
    encoded = base64.urlsafe_b64encode("中文说明".encode()).decode()
    assert module._decode_text(encoded, 20) == "中文说明"


def test_server_helper_requires_one_telegram_target(tmp_path: Path) -> None:
    module = load_module("send_media.py", "xbot_acode_send_target_test")
    module.PLUGIN_DIR = tmp_path
    settings = SimpleNamespace(
        adapters=SimpleNamespace(
            telegram=SimpleNamespace(admin_user_ids=["42"]),
        )
    )

    assert module._target_user_ids(settings) == ["42"]
