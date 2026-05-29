from __future__ import annotations

from abc import ABC, abstractmethod

from xbot.messaging.models import Message, Reply


class BaseAdapter(ABC):
    name: str
    platform: str

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send(self, reply: Reply) -> None:
        raise NotImplementedError

    @abstractmethod
    async def normalize(self, raw: dict) -> Message:
        raise NotImplementedError

