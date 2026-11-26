from __future__ import annotations

import re

_WECHAT_GROUP_EVENT_SUFFIX = re.compile(
    r"^(?P<name>.+?)在群聊中(?:@了你|发(?:了|来|送了).+|发送了?.+|回复了?.+|分享了?.+)$"
)


def clean_sender_name(value: object, *, sender_id: str = "") -> str | None:
    """Return a stable display name without WeChat push-event descriptions."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _WECHAT_GROUP_EVENT_SUFFIX.fullmatch(text)
    if match:
        text = match.group("name").strip()
    if not text or text == str(sender_id or "").strip():
        return None
    return text
