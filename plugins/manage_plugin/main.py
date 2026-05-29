from __future__ import annotations

from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase


class ManagePlugin(PluginBase):
    name = "manage_plugin"
    version = "0.1.0"

    async def on_message(self, message: Message, ctx):
        if not ctx.plugins or not ctx.send_reply:
            return False
        content = (message.content or "").strip()
        command, plugin_name = self._parse_command(content)
        if not command:
            return False
        allowed_commands = set(ctx.config.get("command") or [])
        if allowed_commands and command not in allowed_commands:
            return False
        if not self._is_admin(message, ctx):
            await self._reply(message, ctx, "你没有权限使用此命令")
            return True

        if command == "插件列表":
            await self._reply(message, ctx, self._format_plugin_list(ctx.plugins.list_plugins()))
            return True
        if command == "插件信息":
            await self._reply(message, ctx, self._format_plugin_info(ctx.plugins.list_plugins(), plugin_name))
            return True
        if command == "加载所有插件":
            await ctx.plugins.load_all()
            await self._reply(message, ctx, self._format_loaded_plugins(ctx.plugins.list_plugins(), "插件加载完成"))
            return True
        if command == "重载所有插件":
            await ctx.plugins.reload_all()
            await self._reply(message, ctx, self._format_loaded_plugins(ctx.plugins.list_plugins(), "插件重载完成"))
            return True
        if command == "卸载所有插件":
            disabled = []
            failed = []
            for item in ctx.plugins.list_plugins():
                name = item["name"]
                if name == self.name:
                    continue
                if await ctx.plugins.disable(name):
                    disabled.append(name)
                else:
                    failed.append(name)
            await self._reply(message, ctx, self._format_bulk_result("插件卸载完成", disabled, failed))
            return True

        if not plugin_name:
            await self._reply(message, ctx, f"请指定插件名称，例如：{command} agent_chat")
            return True
        if plugin_name == self.name and command in {"卸载插件", "重载插件"}:
            await self._reply(message, ctx, "不能卸载或重载管理插件本身")
            return True

        if command == "加载插件":
            await ctx.plugins.load_all()
            ok = await ctx.plugins.enable(plugin_name)
            await self._reply(message, ctx, f"{'加载成功' if ok else '加载失败或插件不存在'}：{plugin_name}")
            return True
        if command == "卸载插件":
            ok = await ctx.plugins.disable(plugin_name)
            await self._reply(message, ctx, f"{'卸载成功' if ok else '卸载失败或插件不存在'}：{plugin_name}")
            return True
        if command == "重载插件":
            ok = await ctx.plugins.reload(plugin_name)
            await self._reply(message, ctx, f"{'重载成功' if ok else '重载失败或插件不存在'}：{plugin_name}")
            return True

        return False

    def _parse_command(self, content: str) -> tuple[str | None, str | None]:
        parts = content.split(maxsplit=1)
        if not parts:
            return None, None
        command = parts[0].strip()
        plugin_name = parts[1].strip() if len(parts) > 1 else None
        return command, plugin_name

    def _is_admin(self, message: Message, ctx) -> bool:
        admin_wxids = {str(item) for item in (ctx.config.get("admin_wxids") or []) if str(item).strip()}
        if not admin_wxids:
            return True
        candidates = {
            message.sender_id,
            str(message.raw.get("sender_wxid") or ""),
            str(message.raw.get("group_member_wxid") or ""),
        }
        return bool(admin_wxids.intersection(candidates))

    async def _reply(self, message: Message, ctx, content: str) -> None:
        await ctx.send_reply(
            Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="text",
                content=content,
                quote_message_id=message.id,
            )
        )

    def _format_plugin_list(self, plugins: list[dict]) -> str:
        if not plugins:
            return "当前没有发现插件。"
        lines = ["插件列表："]
        for item in sorted(plugins, key=lambda plugin: plugin["name"]):
            status = "启用" if item.get("enabled") else "停用"
            lines.append(f"- {item['name']} v{item.get('version') or '0.0.0'}：{status}")
        return "\n".join(lines)

    def _format_plugin_info(self, plugins: list[dict], plugin_name: str | None) -> str:
        if not plugin_name:
            return "请指定插件名称，例如：插件信息 agent_chat"
        for item in plugins:
            if item["name"] == plugin_name:
                status = "启用" if item.get("enabled") else "停用"
                return (
                    f"插件名称：{item['name']}\n"
                    f"版本：{item.get('version') or '0.0.0'}\n"
                    f"状态：{status}\n"
                    f"描述：{item.get('description') or ''}"
                )
        return f"插件不存在：{plugin_name}"

    def _format_loaded_plugins(self, plugins: list[dict], title: str) -> str:
        enabled = [item["name"] for item in plugins if item.get("enabled")]
        return self._format_bulk_result(title, enabled, [])

    def _format_bulk_result(self, title: str, succeeded: list[str], failed: list[str]) -> str:
        lines = [title]
        if succeeded:
            lines.append("成功：")
            lines.extend(f"- {name}" for name in succeeded)
        if failed:
            lines.append("失败：")
            lines.extend(f"- {name}" for name in failed)
        if len(lines) == 1:
            lines.append("没有可处理的插件。")
        return "\n".join(lines)
