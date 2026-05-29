from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import anyio

from xbot.core.config import PluginConfig
from xbot.core.logging import logger
from xbot.messaging.models import Message, Reply
from xbot.plugins.context import PluginContext
from xbot.plugins.loader import PluginLoader
from xbot.plugins.manifest import PluginManifest, PluginRouting
from xbot.agent.tool_registry import ToolDefinition


class PluginManager:
    def __init__(self, config: PluginConfig, repository_provider=None) -> None:
        self.config = config
        self.repository_provider = repository_provider
        self.loader = PluginLoader()
        self._plugins: dict[str, Any] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._paths: dict[str, Path] = {}
        self._disabled: set[str] = set()
        self._agent = None
        self._send_reply = None
        self._conversations = None
        self._settings = None

    def attach_runtime(self, *, agent=None, send_reply=None, conversations=None, settings=None) -> None:
        self._agent = agent
        self._send_reply = send_reply
        self._conversations = conversations
        self._settings = settings

    async def load_all(self) -> None:
        root = Path(self.config.directory)
        if not root.exists():
            return
        for plugin_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                manifest = self.loader.load_manifest(plugin_dir)
                self._manifests[manifest.name] = manifest
                self._paths[manifest.name] = plugin_dir
                persisted_enabled = await self._get_persisted_enabled(manifest.name)
                enabled = persisted_enabled if persisted_enabled is not None else manifest.enabled
                await self._persist_manifest(manifest, plugin_dir, enabled)
                if manifest.name in self._disabled:
                    continue
                if not enabled:
                    self._disabled.add(manifest.name)
                    continue
                instance = self.loader.load_instance(plugin_dir, manifest)
                self._plugins[manifest.name] = instance
                await self._call(
                    instance.on_load,
                    self._context(manifest.name),
                )
            except Exception as exc:
                logger.warning(f"Failed to load plugin {plugin_dir}: {exc}")

    def list_plugins(self) -> list[dict]:
        return [
            {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "enabled": manifest.name in self._plugins and manifest.name not in self._disabled,
            }
            for manifest in self._manifests.values()
        ]

    def list_agent_tools(self, name: str | None = None) -> list[dict]:
        if name and name not in self._manifests:
            return []
        manifests = [(name, self._manifests[name])] if name else sorted(self._manifests.items())
        items = []
        for plugin_name, manifest in manifests:
            enabled = plugin_name in self._plugins and plugin_name not in self._disabled
            for item in manifest.agent_tools:
                metadata = {
                    **item.metadata,
                    "plugin": plugin_name,
                    "platforms": item.platforms,
                    "scopes": item.scopes,
                    "modes": item.modes,
                }
                items.append(
                    {
                        "plugin": plugin_name,
                        "enabled": enabled,
                        "name": item.name,
                        "handler": item.handler,
                        "description": item.description,
                        "risk_level": item.risk_level,
                        "toolset": item.toolset,
                        "cacheable": item.cacheable,
                        "timeout_seconds": item.timeout_seconds,
                        "invalidates_cache": item.invalidates_cache,
                        "input_schema": item.input_schema,
                        "metadata": metadata,
                    }
                )
        return items

    def iter_agent_tools(self):
        for name, plugin in self._plugins.items():
            if name in self._disabled:
                continue
            manifest = self._manifests.get(name)
            if manifest:
                for tool in self._manifest_agent_tools(name, plugin, manifest):
                    yield name, [tool]
            provider = getattr(plugin, "agent_tools", None)
            if not provider:
                continue
            try:
                yield name, list(provider() or [])
            except Exception as exc:
                logger.warning("Plugin agent tool provider failed: plugin={} error={}", name, exc)

    def _manifest_agent_tools(self, name: str, plugin, manifest: PluginManifest):
        for item in manifest.agent_tools:
            handler = getattr(plugin, item.handler, None)
            if handler is None:
                logger.warning(
                    "Plugin manifest agent tool ignored: plugin={} tool={} missing_handler={}",
                    name,
                    item.name,
                    item.handler,
                )
                continue
            yield ToolDefinition(
                name=item.name,
                description=item.description,
                risk_level=item.risk_level,
                handler=handler,
                input_schema=item.input_schema,
                toolset=item.toolset,
                source="plugin",
                cacheable=item.cacheable,
                timeout_seconds=item.timeout_seconds,
                invalidates_cache=item.invalidates_cache,
                metadata={
                    **item.metadata,
                    "platforms": item.platforms,
                    "scopes": item.scopes,
                    "modes": item.modes,
                },
            )

    async def enable(self, name: str) -> bool:
        manifest = self._manifests.get(name)
        plugin_dir = self._paths.get(name)
        if manifest is None or plugin_dir is None:
            return False
        self._disabled.discard(name)
        await self._persist_enabled(name, True)
        if name not in self._plugins:
            instance = self.loader.load_instance(plugin_dir, manifest)
            self._plugins[name] = instance
            await self._call(instance.on_load, self._context(name))
        return True

    async def disable(self, name: str) -> bool:
        if name not in self._manifests:
            return False
        self._disabled.add(name)
        await self._persist_enabled(name, False)
        instance = self._plugins.pop(name, None)
        if instance is not None:
            await self._call(instance.on_unload)
        return True

    async def dispatch_message(self, message: Message) -> None:
        candidates = sorted(
            self._plugins.items(),
            key=lambda item: self._manifests[item[0]].routing.priority,
        )
        fallback_candidates = []
        for name, plugin in candidates:
            if name in self._disabled:
                continue
            manifest = self._manifests[name]
            if manifest.routing.fallback:
                fallback_candidates.append((name, plugin))
                continue
            if not self._matches_routing(message, manifest.routing):
                continue
            result = await self._call(plugin.on_message, message, self._context(name))
            handled = await self._handle_plugin_result(result)
            if handled or self._claims_message(message, manifest.routing):
                return

        for name, plugin in fallback_candidates:
            manifest = self._manifests[name]
            if self._matches_routing(message, manifest.routing):
                result = await self._call(plugin.on_message, message, self._context(name))
                if await self._handle_plugin_result(result):
                    return

    async def _call(self, func, *args):
        if inspect.iscoroutinefunction(func):
            return await func(*args)
        return await anyio.to_thread.run_sync(lambda: func(*args))

    def _context(self, name: str) -> PluginContext:
        return PluginContext(
            name=name,
            data_dir=Path(self.config.directory) / name / "data",
            config={},
            agent=self._agent,
            send_reply=self._send_reply,
            conversations=self._conversations,
            settings=self._settings,
        )

    async def _handle_plugin_result(self, result) -> bool:
        if result is None or result is False:
            return False
        if result is True:
            return True
        if isinstance(result, Reply):
            if self._send_reply:
                await self._send_reply(result)
            return True
        if isinstance(result, list):
            handled = False
            for item in result:
                if isinstance(item, Reply) and self._send_reply:
                    await self._send_reply(item)
                    handled = True
            return handled
        if isinstance(result, dict):
            replies = result.get("replies") or []
            for reply in replies:
                if isinstance(reply, Reply) and self._send_reply:
                    await self._send_reply(reply)
            return bool(result.get("handled") or replies)
        return True

    def _matches_routing(self, message: Message, routing: PluginRouting) -> bool:
        if not routing.enabled:
            return False
        if routing.message_types and message.type not in routing.message_types:
            return False
        if routing.platforms and message.platform not in routing.platforms:
            return False
        if routing.adapters and message.adapter not in routing.adapters:
            return False
        scope = str(message.raw.get("scope") or "")
        if routing.scopes and scope not in routing.scopes:
            return False
        content = message.content or ""
        has_triggers = bool(routing.prefixes or routing.keywords or routing.exact)
        if not has_triggers:
            return True
        return (
            content in routing.exact
            or any(content.startswith(prefix) for prefix in routing.prefixes)
            or any(keyword in content for keyword in routing.keywords)
        )

    def _claims_message(self, message: Message, routing: PluginRouting) -> bool:
        has_triggers = bool(routing.prefixes or routing.keywords or routing.exact)
        return routing.exclusive and has_triggers and self._matches_routing(message, routing)

    async def _persist_manifest(self, manifest: PluginManifest, plugin_dir: Path, enabled: bool) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            await repo.upsert_manifest(manifest, str(plugin_dir), enabled)

    async def _persist_enabled(self, name: str, enabled: bool) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            await repo.set_enabled(name, enabled)

    async def _get_persisted_enabled(self, name: str) -> bool | None:
        if not self.repository_provider:
            return None
        async with self.repository_provider() as repo:
            return await repo.get_enabled(name)
