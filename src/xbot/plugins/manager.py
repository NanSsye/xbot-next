from __future__ import annotations

import asyncio
import inspect
import tomllib
from pathlib import Path
from typing import Any

import anyio

from xbot.agent.tool_registry import ToolDefinition
from xbot.core.config import PluginConfig
from xbot.core.logging import logger
from xbot.messaging.models import Message, Reply
from xbot.plugins.context import PluginContext
from xbot.plugins.loader import PluginLoader
from xbot.plugins.manifest import PluginManifest, PluginRouting


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
        self._adapters = None
        self._events = None
        self._scheduler = None
        self._config_cache: dict[str, dict] = {}

    def attach_runtime(
        self,
        *,
        agent=None,
        send_reply=None,
        conversations=None,
        settings=None,
        adapters=None,
        events=None,
        scheduler=None,
    ) -> None:
        self._agent = agent
        self._send_reply = send_reply
        self._conversations = conversations
        self._settings = settings
        self._adapters = adapters
        self._events = events
        self._scheduler = scheduler

    async def load_all(self) -> None:
        root = Path(self.config.directory)
        if not await asyncio.to_thread(root.exists):
            return
        plugin_dirs = await asyncio.to_thread(
            lambda: sorted(p for p in root.iterdir() if p.is_dir())
        )
        for plugin_dir in plugin_dirs:
            try:
                manifest = self.loader.load_manifest(plugin_dir)
                persisted_enabled = await self._get_persisted_enabled(manifest.name)
                enabled = persisted_enabled if persisted_enabled is not None else manifest.enabled
                if manifest.name in self._disabled or not enabled:
                    await self._persist_manifest(manifest, plugin_dir, enabled)
                    self._manifests[manifest.name] = manifest
                    self._paths[manifest.name] = plugin_dir
                    if manifest.name in self._plugins:
                        await self._unload_instance(manifest.name)
                if not enabled:
                    self._disabled.add(manifest.name)
                    continue
                if manifest.name in self._disabled or manifest.name in self._plugins:
                    continue
                instance = self.loader.load_instance(plugin_dir, manifest)
                self._config_cache.pop(manifest.name, None)
                try:
                    await self._call(
                        instance.on_load,
                        self._context(manifest.name, plugin_dir),
                    )
                    await self._persist_manifest(manifest, plugin_dir, enabled)
                except Exception:
                    await self._cleanup_failed_instance(manifest.name, instance)
                    self._config_cache.pop(manifest.name, None)
                    raise
                self._manifests[manifest.name] = manifest
                self._paths[manifest.name] = plugin_dir
                self._plugins[manifest.name] = instance
            except Exception as exc:
                logger.warning(f"Failed to load plugin {plugin_dir}: {exc}")
        for name, path in list(self._paths.items()):
            if await asyncio.to_thread(path.exists):
                continue
            await self._unload_instance(name)
            self._manifests.pop(name, None)
            self._paths.pop(name, None)
            self._disabled.discard(name)

    async def reload_all(self) -> None:
        existing = list(self._plugins)
        await self.load_all()
        for name in existing:
            if name in self._plugins:
                await self.reload(name)

    async def unload_all(self) -> None:
        for name in list(self._plugins):
            try:
                await self._unload_instance(name)
            except Exception as exc:
                self._plugins.pop(name, None)
                self._config_cache.pop(name, None)
                logger.exception("Failed to unload plugin {}: {}", name, exc)

    async def reload(self, name: str) -> bool:
        root = Path(self.config.directory)
        plugin_dir = self._paths.get(name)
        if plugin_dir is None:
            candidates = []
            if await asyncio.to_thread(root.exists):
                entries = await asyncio.to_thread(root.iterdir)
                candidates = [path for path in entries if path.is_dir()]
            for candidate in candidates:
                try:
                    manifest = self.loader.load_manifest(candidate)
                except Exception as exc:
                    logger.debug(f"Skip plugin candidate {candidate}: {exc}")
                    continue
                if manifest.name == name:
                    plugin_dir = candidate
                    break
        if plugin_dir is None:
            return False
        try:
            manifest = self.loader.load_manifest(plugin_dir)
            if manifest.name != name:
                raise ValueError(
                    f"Plugin manifest name changed from {name} to {manifest.name}"
                )
            enabled = await self._get_persisted_enabled(name)
            enabled = manifest.enabled if enabled is None else enabled
            if not enabled or name in self._disabled:
                await self._persist_manifest(manifest, plugin_dir, enabled)
                await self._unload_instance(name)
                self._manifests[name] = manifest
                self._paths[name] = plugin_dir
                return True
            instance = self.loader.load_instance(plugin_dir, manifest)
            old_instance = self._plugins.get(name)
            old_manifest = self._manifests.get(name)
            old_path = self._paths.get(name)
            missing = object()
            old_config = self._config_cache.get(name, missing)
            if old_instance is not None:
                await self._call(old_instance.on_unload)
                self._plugins.pop(name, None)
            self._config_cache.pop(name, None)
            try:
                await self._call(instance.on_load, self._context(name, plugin_dir))
                await self._persist_manifest(manifest, plugin_dir, enabled)
            except Exception:
                await self._cleanup_failed_instance(name, instance)
                self._config_cache.pop(name, None)
                if old_config is not missing:
                    self._config_cache[name] = old_config
                if old_instance is not None:
                    try:
                        await self._call(
                            old_instance.on_load,
                            self._context(name, old_path),
                        )
                        self._plugins[name] = old_instance
                    except Exception as rollback_exc:
                        logger.exception(
                            "Failed to restore plugin {} after reload failure: {}",
                            name,
                            rollback_exc,
                        )
                if old_manifest is not None:
                    self._manifests[name] = old_manifest
                if old_path is not None:
                    self._paths[name] = old_path
                raise
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._paths[name] = plugin_dir
            return True
        except Exception as exc:
            logger.warning("Failed to reload plugin {}: {}", name, exc)
            return False

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
        if name not in self._plugins:
            instance = self.loader.load_instance(plugin_dir, manifest)
            self._config_cache.pop(name, None)
            try:
                await self._call(instance.on_load, self._context(name, plugin_dir))
                await self._persist_enabled(name, True)
            except Exception:
                await self._cleanup_failed_instance(name, instance)
                self._config_cache.pop(name, None)
                raise
            self._plugins[name] = instance
        else:
            await self._persist_enabled(name, True)
        self._disabled.discard(name)
        return True

    async def disable(self, name: str) -> bool:
        if name not in self._manifests:
            return False
        self._disabled.add(name)
        await self._persist_enabled(name, False)
        await self._unload_instance(name)
        return True

    async def _unload_instance(self, name: str) -> None:
        instance = self._plugins.get(name)
        if instance is not None:
            await self._call(instance.on_unload)
            if self._plugins.get(name) is instance:
                self._plugins.pop(name, None)
        self._config_cache.pop(name, None)

    async def _cleanup_failed_instance(self, name: str, instance: Any) -> None:
        try:
            await self._call(instance.on_unload)
        except Exception as exc:
            logger.warning("Failed to clean up plugin {} after load error: {}", name, exc)

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
            try:
                result = await self._call(plugin.on_message, message, self._context(name))
            except Exception as exc:
                logger.exception(
                    "Plugin on_message 异常(已隔离): plugin={} message_id={} conversation={} error={}",
                    name,
                    message.id,
                    message.conversation_id,
                    exc,
                )
                continue
            handled = await self._handle_plugin_result(result)
            if handled or self._claims_message(message, manifest.routing):
                return

        for name, plugin in fallback_candidates:
            manifest = self._manifests[name]
            if self._matches_routing(message, manifest.routing):
                try:
                    result = await self._call(plugin.on_message, message, self._context(name))
                except Exception as exc:
                    logger.exception(
                        "Plugin on_message 异常(已隔离): plugin={} message_id={} conversation={} error={}",
                        name,
                        message.id,
                        message.conversation_id,
                        exc,
                    )
                    continue
                if await self._handle_plugin_result(result):
                    return

    async def _call(self, func, *args):
        if inspect.iscoroutinefunction(func):
            return await func(*args)
        return await anyio.to_thread.run_sync(lambda: func(*args))

    def _context(self, name: str, plugin_dir: Path | None = None) -> PluginContext:
        plugin_dir = plugin_dir or Path(self.config.directory) / name
        return PluginContext(
            name=name,
            data_dir=plugin_dir / "data",
            config=self._cached_plugin_config(plugin_dir, name),
            plugins=self,
            agent=self._agent,
            send_reply=self._send_reply,
            conversations=self._conversations,
            settings=self._settings,
            adapters=self._adapters,
            events=self._events,
            scheduler=self._scheduler,
        )

    def _cached_plugin_config(self, plugin_dir: Path, name: str) -> dict:
        cached = self._config_cache.get(name)
        if cached is not None:
            return cached
        config = self._load_plugin_config(plugin_dir, name)
        self._config_cache[name] = config
        return config

    def _load_plugin_config(self, plugin_dir: Path, name: str) -> dict:
        config_path = plugin_dir / "config.toml"
        if not config_path.exists():
            return {}
        try:
            with config_path.open("rb") as fh:
                data = tomllib.load(fh)
        except Exception as exc:
            logger.warning("Failed to load plugin config: plugin={} path={} error={}", name, config_path, exc)
            return {}
        section = data.get(name)
        if isinstance(section, dict):
            return section
        return data

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
        return routing.exclusive and self._matches_routing(message, routing)

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
