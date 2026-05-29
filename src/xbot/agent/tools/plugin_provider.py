from __future__ import annotations

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.logging import logger


def register_plugin_tools(registry: ToolRegistry, plugins) -> None:
    if not plugins or not hasattr(plugins, "iter_agent_tools"):
        return
    registry.unregister_source_prefix("plugin:")
    for plugin_name, tools in plugins.iter_agent_tools():
        for tool in tools:
            if not isinstance(tool, ToolDefinition):
                logger.warning(
                    "Plugin agent tool ignored: plugin={} reason=not ToolDefinition",
                    plugin_name,
                )
                continue
            registry.register(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    risk_level=tool.risk_level,
                    handler=tool.handler,
                    input_schema=tool.input_schema,
                    toolset=tool.toolset or "plugin",
                    source=f"plugin:{plugin_name}",
                    cacheable=tool.cacheable,
                    timeout_seconds=tool.timeout_seconds,
                    invalidates_cache=tool.invalidates_cache,
                    metadata={**(tool.metadata or {}), "plugin": plugin_name},
                )
            )
            logger.info("Plugin agent tool registered: plugin={} tool={}", plugin_name, tool.name)
