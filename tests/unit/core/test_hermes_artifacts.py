from __future__ import annotations

import json

import anyio
import pytest

from xbot.agent.tools.hermes_artifacts import (
    create_artifact,
    reset_artifact_context,
    set_artifact_context,
)
from xbot.agent.tools.hermes_wechat import (
    reset_send_context,
    set_send_context,
)


def test_markdown_artifact_is_created_inside_isolated_output(tmp_path):
    token = set_artifact_context({"output_dir": str(tmp_path), "channel": "wechat"})
    try:
        result = json.loads(create_artifact({
            "format": "md",
            "filename": "../../答辩意见.txt",
            "title": "答辩意见",
            "content": "正文",
            "send": False,
        }))
    finally:
        reset_artifact_context(token)

    assert result["success"] is True
    assert result["filename"] == "答辩意见.md"
    assert (tmp_path / "答辩意见.md").read_text(encoding="utf-8") == "# 答辩意见\n\n正文\n"
    assert result["sent"] is False


@pytest.mark.anyio
async def test_markdown_artifact_is_sent_to_current_wechat_conversation(tmp_path):
    calls = []

    async def sender(**kwargs):
        calls.append(kwargs)

    send_token = set_send_context({
        "loop": __import__("asyncio").get_running_loop(),
        "sender": sender,
        "adapter": "wechat869",
        "conversation_id": "current-user",
    })
    artifact_token = set_artifact_context({"output_dir": str(tmp_path), "channel": "wechat"})
    try:
        raw_result = await anyio.to_thread.run_sync(
            create_artifact,
            {"format": "md", "filename": "法律意见.md", "content": "正文"},
        )
    finally:
        reset_artifact_context(artifact_token)
        reset_send_context(send_token)

    result = json.loads(raw_result)
    assert result["sent"] is True
    assert calls[0]["conversation_id"] == "current-user"
    assert calls[0]["message_type"] == "file"
    assert calls[0]["content"].endswith("法律意见.md")
