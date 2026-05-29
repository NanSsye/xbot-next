from __future__ import annotations

from xbot.messaging.models import Message


class ContextWindow:
    def __init__(self, recent_messages: int = 20, max_chars: int = 16000) -> None:
        self.recent_messages = recent_messages
        self.max_chars = max_chars

    def trim(self, messages: list[Message]) -> list[Message]:
        selected = messages if self.recent_messages <= 0 else messages[-self.recent_messages :]
        total = 0
        trimmed: list[Message] = []
        for message in reversed(selected):
            total += len(message.content or "")
            if total > self.max_chars:
                break
            trimmed.append(message)
        return list(reversed(trimmed))
