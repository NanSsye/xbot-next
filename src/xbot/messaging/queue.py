from __future__ import annotations

from abc import ABC, abstractmethod

from xbot.messaging.models import MessageEnvelope


class MessageQueue(ABC):
    @abstractmethod
    async def publish(self, envelope: MessageEnvelope) -> None:
        raise NotImplementedError

    @abstractmethod
    async def consume(self) -> MessageEnvelope:
        raise NotImplementedError

    async def ack(self, envelope: MessageEnvelope) -> None:
        return None

    async def close(self) -> None:
        return None
