from types import SimpleNamespace

import pytest

from xbot.messaging.models import Message, Reply
from xbot.plugins.manager import PluginManager

_LOAD_ALL = PluginManager.load_all


def _message(message_id: str = "m1") -> Message:
    return Message(
        id=message_id,
        platform="wechat",
        adapter="wechat869",
        conversation_id="room-a",
        sender_id="sender",
        content="hello",
        raw={"id": message_id, "scope": "group"},
    )


class ExplodingPlugin:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    async def on_message(self, message, ctx):
        self.calls += 1
        raise RuntimeError(f"{self.name} boom")


class ReplyingPlugin:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.sent = []

    async def on_message(self, message, ctx):
        self.calls += 1
        reply = Reply(
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            content=f"from {self.name}",
        )
        self.sent.append(reply)
        return reply


class FakeLoader:
    pass


def _manager_with(plugins: dict) -> PluginManager:
    config = type("Cfg", (), {"directory": "plugins"})()
    manager = PluginManager(config)
    manager._plugins = {name: plugin for name, plugin in plugins.items()}
    manager._manifests = {}
    manager._paths = {}
    for name in plugins:
        routing = type("Routing", (), {"priority": 10, "fallback": False, "exclusive": False, "enabled": True, "message_types": [], "platforms": [], "adapters": [], "scopes": [], "prefixes": [], "keywords": [], "exact": []})()
        manifest = type("Manifest", (), {"name": name, "routing": routing})()
        manager._manifests[name] = manifest
        manager._paths[name] = type("P", (), {"is_dir": lambda self: True, "__truediv__": lambda self, other: other})() if False else _dummy_path()
    return manager


def _dummy_path():
    class DummyPath:
        def __truediv__(self, other):
            return self

        @property
        def exists(self):
            return lambda: False

    return DummyPath()


@pytest.mark.anyio
async def test_plugin_exception_does_not_block_other_plugins():
    exploding = ExplodingPlugin("bad")
    replying = ReplyingPlugin("good")
    manager = _manager_with({"bad": exploding, "good": replying})
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    manager._send_reply = send_reply

    message = _message()
    await manager.dispatch_message(message)

    assert exploding.calls == 1
    assert replying.calls == 1
    assert len(replies) == 1
    assert replies[0].content == "from good"


@pytest.mark.anyio
async def test_plugin_config_cached_across_dispatch():
    replying = ReplyingPlugin("cached")
    manager = _manager_with({"cached": replying})

    async def send_reply(reply):
        return None

    manager._send_reply = send_reply

    loads = []

    def fake_load(plugin_dir, name):
        loads.append(name)
        return {"k": "v"}

    manager._load_plugin_config = fake_load
    manager._config_cache.clear()

    message = _message()
    await manager.dispatch_message(message)
    await manager.dispatch_message(message)
    await manager.dispatch_message(message)

    assert replying.calls == 3
    assert loads == ["cached"]


class LifecyclePlugin:
    def __init__(self, *, fail_load: bool = False):
        self.fail_load = fail_load
        self.load_calls = 0
        self.unload_calls = 0

    async def on_load(self, ctx):
        self.load_calls += 1
        if self.fail_load:
            raise RuntimeError("load failed")

    async def on_unload(self):
        self.unload_calls += 1


@pytest.mark.anyio
async def test_load_all_does_not_register_instance_when_on_load_fails(tmp_path):
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    failed = LifecyclePlugin(fail_load=True)

    class Loader:
        def load_manifest(self, path):
            if path.name != "broken":
                raise RuntimeError("not a lifecycle fixture")
            return SimpleNamespace(name="broken", enabled=True)

        def load_instance(self, path, manifest):
            return failed

    manager = PluginManager(SimpleNamespace(directory=str(tmp_path)))
    manager.loader = Loader()

    await _LOAD_ALL(manager)

    assert "broken" not in manager._plugins
    assert failed.load_calls == 1
    assert failed.unload_calls == 1


@pytest.mark.anyio
async def test_reload_constructor_failure_keeps_old_instance(tmp_path):
    plugin_dir = tmp_path / "stable"
    plugin_dir.mkdir()
    old = LifecyclePlugin()
    manifest = SimpleNamespace(name="stable", enabled=True)

    class Loader:
        def load_manifest(self, path):
            return manifest

        def load_instance(self, path, loaded_manifest):
            raise RuntimeError("constructor failed")

    manager = PluginManager(SimpleNamespace(directory=str(tmp_path)))
    manager.loader = Loader()
    manager._plugins["stable"] = old
    manager._manifests["stable"] = manifest
    manager._paths["stable"] = plugin_dir

    assert await manager.reload("stable") is False
    assert manager._plugins["stable"] is old
    assert old.unload_calls == 0


@pytest.mark.anyio
async def test_reload_on_load_failure_restores_old_instance(tmp_path):
    plugin_dir = tmp_path / "stable"
    plugin_dir.mkdir()
    old = LifecyclePlugin()
    replacement = LifecyclePlugin(fail_load=True)
    manifest = SimpleNamespace(name="stable", enabled=True)

    class Loader:
        def load_manifest(self, path):
            return manifest

        def load_instance(self, path, loaded_manifest):
            return replacement

    manager = PluginManager(SimpleNamespace(directory=str(tmp_path)))
    manager.loader = Loader()
    manager._plugins["stable"] = old
    manager._manifests["stable"] = manifest
    manager._paths["stable"] = plugin_dir

    assert await manager.reload("stable") is False
    assert manager._plugins["stable"] is old
    assert old.unload_calls == 1
    assert old.load_calls == 1
    assert replacement.load_calls == 1
    assert replacement.unload_calls == 1


@pytest.mark.anyio
async def test_unload_all_stops_every_registered_plugin():
    first = LifecyclePlugin()
    second = LifecyclePlugin()
    manager = _manager_with({"first": first, "second": second})

    await manager.unload_all()

    assert manager._plugins == {}
    assert first.unload_calls == 1
    assert second.unload_calls == 1
