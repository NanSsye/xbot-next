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
        self.queue = queue
        self.repository_provider = repository_provider
        self._adapters: dict[str, BaseAdapter] = {}
        self._enabled_overrides: dict[str, bool] = {}
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

    def _configured_adapters(self) -> dict[str, tuple[str, bool]]:
        return {
            "web": ("web", self.config.web.enabled),
            "wechat869": ("wechat", self.config.wechat869.enabled),
            "wechat_ilink": ("wechat", self.config.wechat_ilink.enabled),
        }

    def register(self, adapter: BaseAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> BaseAdapter | None:
        return self._adapters.get(name)

    def list_adapters(self) -> list[dict]:
        items = []
        for name, (platform, configured_enabled) in self._configured_adapters().items():
            adapter = self._adapters.get(name)
            effective_enabled = self._effective_enabled(name)
            items.append(
                {
                    "name": name,
                    "platform": adapter.platform if adapter else platform,
                    "enabled": adapter is not None,
                    "configured_enabled": configured_enabled,
                    "persistent_enabled": self._enabled_overrides.get(name),
                    "effective_enabled": effective_enabled,
                    "started": bool(getattr(adapter, "started", False)) if adapter else False,
                    "status": "started" if bool(getattr(adapter, "started", False)) else ("stopped" if adapter else "disabled"),
                }
            )
        for adapter in self._adapters.values():
            if adapter.name in {item["name"] for item in items}:
                continue
            items.append(
                {
                    "name": adapter.name,
                    "platform": adapter.platform,
                    "enabled": True,
                    "configured_enabled": True,
                    "started": bool(getattr(adapter, "started", False)),
                    "status": "started" if bool(getattr(adapter, "started", False)) else "stopped",
                }
            )
        return items

    async def enable(self, name: str) -> BaseAdapter | None:
        adapter = self._adapters.get(name)
        if adapter is None:
            adapter = self._create_adapter(name)
            if adapter is None:
                return None
            self.register(adapter)
        await adapter.start()
        self._enabled_overrides[name] = True
        await self._persist_enabled(name, True)
        return adapter

    async def disable(self, name: str) -> bool:
        adapter = self._adapters.pop(name, None)
        if adapter is None:
            exists = name in self._configured_adapters()
            if exists:
                self._enabled_overrides[name] = False
                await self._persist_enabled(name, False)
            return exists
        await adapter.stop()
        self._enabled_overrides[name] = False
        await self._persist_enabled(name, False)
        return True

    def _create_adapter(self, name: str) -> BaseAdapter | None:
        if name == "web":
            return WebAdapter()
        if name == "wechat869":
            return Wechat869Adapter(self.config.wechat869, queue=self.queue)
        if name == "wechat_ilink":
            return WechatIlinkAdapter(
                self.config.wechat_ilink,
                queue=self.queue,
                repository_provider=self.repository_provider,
            )
        return None

    async def start_enabled(self) -> None:
        await self._load_enabled_overrides()
        configured_names = set(self._configured_adapters())
        for name in configured_names:
            should_start = self._effective_enabled(name)
            adapter = self._adapters.get(name)
            if should_start:
                if adapter is None:
                    adapter = self._create_adapter(name)
                    if adapter is not None:
                        self.register(adapter)
                if adapter is not None:
                    await adapter.start()
            elif adapter is not None:
                await adapter.stop()
                self._adapters.pop(name, None)
        for name, adapter in list(self._adapters.items()):
            if name not in configured_names:
                await adapter.start()

    async def stop_all(self) -> None:
        for adapter in self._adapters.values():
            await adapter.stop()

    async def send(self, reply: Reply) -> None:
        adapter = self._adapters.get(reply.adapter)
        if adapter:
            await adapter.send(reply)

    def _effective_enabled(self, name: str) -> bool:
        if name in self._enabled_overrides:
            return self._enabled_overrides[name]
        return self._configured_adapters().get(name, ("", False))[1]

    async def _load_enabled_overrides(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            for name in self._configured_adapters():
                state = await repo.get_state(name)
                if isinstance(state.get("enabled"), bool):
                    self._enabled_overrides[name] = state["enabled"]

    async def _persist_enabled(self, name: str, enabled: bool) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            state = await repo.get_state(name)
            state["enabled"] = enabled
            await repo.set_state(name, state)
