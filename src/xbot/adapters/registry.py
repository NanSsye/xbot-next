from __future__ import annotations

from xbot.adapters.base import BaseAdapter
from xbot.adapters.wechat869 import Wechat869Adapter
from xbot.adapters.wechat_ilink import WechatIlinkAdapter
from xbot.adapters.web.adapter import WebAdapter
from xbot.core.config import AdapterConfig
from xbot.messaging.models import Reply


class AdapterRegistry:
    def __init__(self, config: AdapterConfig, queue=None, repository_provider=None) -> None:
        self.config = config
        self._adapters: dict[str, BaseAdapter] = {}
        if config.web.enabled:
            self.register(WebAdapter())
        if config.wechat869.enabled:
            self.register(Wechat869Adapter(config.wechat869, queue=queue))
        if config.wechat_ilink.enabled:
            self.register(
                WechatIlinkAdapter(
                    config.wechat_ilink,
                    queue=queue,
                    repository_provider=repository_provider,
                )
            )

    def register(self, adapter: BaseAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> BaseAdapter | None:
        return self._adapters.get(name)

    def list_adapters(self) -> list[dict]:
        return [
            {"name": adapter.name, "platform": adapter.platform}
            for adapter in self._adapters.values()
        ]

    async def start_enabled(self) -> None:
        for adapter in self._adapters.values():
            await adapter.start()

    async def stop_all(self) -> None:
        for adapter in self._adapters.values():
            await adapter.stop()

    async def send(self, reply: Reply) -> None:
        adapter = self._adapters.get(reply.adapter)
        if adapter:
            await adapter.send(reply)
