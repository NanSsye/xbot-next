from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import mimetypes
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from loguru import logger

from xbot.adapters.telegram.formatting import split_markdown
from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext


class AcodeApiError(RuntimeError):
    def __init__(self, status: int, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class AttachmentError(ValueError):
    pass


class AcodeRemotePlugin(PluginBase):
    name = "acode_remote"
    version = "0.4.1"

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        self._session: aiohttp.ClientSession | None = None
        self._enabled = False
        self._base_url = ""
        self._admin_token = ""
        self._allowed_user_ids: set[str] = set()
        self._agent_label = "小X"
        self._max_threads = 30
        self._page_size = 5
        self._request_timeout = 20.0
        self._result_timeout = 1800.0
        self._poll_interval = 1.5
        self._session_token = ""
        self._session_expires_at = 0.0
        self._auth_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._run_lock = asyncio.Lock()
        self._selections: dict[str, str] = {}
        self._favorites: dict[str, list[str]] = {}
        self._thread_titles: dict[str, str] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._service_tasks: set[asyncio.Task[Any]] = set()
        self._watchers: dict[str, asyncio.Task[Any]] = {}
        self._runs: dict[str, dict[str, Any]] = {}
        self._fork_requests: dict[str, dict[str, Any]] = {}
        self._fork_lock = asyncio.Lock()
        self._album_lock = asyncio.Lock()
        self._album_batches: dict[str, dict[str, Any]] = {}
        self._album_delay = 5.0
        self._searches: dict[str, dict[str, str]] = {}
        self._shown_approvals: set[str] = set()
        self._voice_transcription_enabled = True
        self._voice_transcription_model = "base"
        self._voice_model: Any = None
        self._voice_lock = asyncio.Lock()
        self._retention_days = 30
        self._maintenance_enabled = True

    async def on_load(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        config = self._plugin_config(ctx.config)
        self._enabled = bool(config.get("enabled", False))
        self._base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self._admin_token = str(config.get("admin_token") or "").strip()
        configured_users = config.get("allowed_user_ids")
        if isinstance(configured_users, list):
            self._allowed_user_ids = {str(item).strip() for item in configured_users if str(item).strip()}
        if not self._allowed_user_ids:
            telegram = getattr(getattr(ctx.settings, "adapters", None), "telegram", None)
            self._allowed_user_ids = {
                str(item).strip()
                for item in (getattr(telegram, "admin_user_ids", None) or [])
                if str(item).strip()
            }
        self._agent_label = str(config.get("agent_label") or "小X").strip() or "小X"
        self._max_threads = self._bounded_int(config.get("max_threads"), 30, 5, 100)
        self._request_timeout = self._bounded_float(config.get("request_timeout_seconds"), 20, 3, 120)
        self._result_timeout = self._bounded_float(config.get("result_timeout_seconds"), 1800, 30, 7200)
        self._poll_interval = self._bounded_float(config.get("poll_interval_seconds"), 1.5, 0.5, 10)
        self._album_delay = self._bounded_float(config.get("album_delay_seconds"), 5, 2, 15)
        self._voice_transcription_enabled = bool(config.get("voice_transcription_enabled", True))
        self._voice_transcription_model = (
            str(config.get("voice_transcription_model") or "base").strip() or "base"
        )
        self._retention_days = self._bounded_int(config.get("retention_days"), 30, 7, 3650)
        self._maintenance_enabled = bool(config.get("maintenance_enabled", True))
        await asyncio.to_thread(self._harden_config_permissions, ctx.data_dir.parent / "config.toml")
        self._selections = await asyncio.to_thread(self._read_state, ctx.data_dir / "selections.json")
        self._favorites = await asyncio.to_thread(
            self._read_favorites,
            ctx.data_dir / "favorites.json",
        )
        self._runs = await asyncio.to_thread(self._read_runs, ctx.data_dir / "pending_turns.json")
        if self._is_configured():
            for run_key in list(self._runs):
                self._start_watcher(run_key)
            if ctx.adapters is not None and self._allowed_user_ids:
                self._schedule(
                    self._configure_telegram_menu(),
                    name="acode-configure-telegram-menu",
                )
                self._schedule_service(
                    self._menu_refresh_loop(),
                    name="acode-menu-refresh",
                )
            self._schedule_service(self._retry_pending_loop(), name="acode-pending-retry")
            if self._maintenance_enabled:
                self._schedule_service(self._maintenance_loop(), name="acode-maintenance")
        logger.info(
            "[acode_remote] 已加载: enabled={} allowed_users={} configured={} recovered_turns={}",
            self._enabled,
            len(self._allowed_user_ids),
            self._is_configured(),
            len(self._runs),
        )

    async def on_unload(self) -> None:
        tasks = list(self._tasks | self._service_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._service_tasks.clear()
        self._watchers.clear()
        self._fork_requests.clear()
        self._album_batches.clear()
        self._voice_model = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._session_token = ""
        self._session_expires_at = 0.0

    async def on_message(self, message: Message, ctx: PluginContext):
        if message.platform != "telegram" or message.adapter != "telegram":
            return False
        if str(message.raw.get("scope") or "") != "private":
            return False

        content = str(message.content or "").strip()
        explicit = self._is_explicit_command(content)
        if not self._is_admin(message.sender_id):
            if explicit or content.startswith("acode:"):
                return self._reply(message, "该功能仅限管理员使用。")
            return False

        if message.type == "event":
            return await self._handle_callback(message, content)

        command = self._command(content)
        if command in {"/start", "/chat", "/codex", "/tasks", "/help"}:
            self._schedule(self._send_menu(message), name=f"acode-menu-{message.id}")
            return True
        if command in {"/find", "/search"}:
            parts = content.split(maxsplit=1)
            query = parts[1].strip() if len(parts) > 1 else ""
            if not query:
                return self._reply(message, "请输入搜索词，例如：/find xbot")
            self._schedule(
                self._send_search_results(message, query),
                name=f"acode-search-{message.id}",
            )
            return True
        if command == "/agent":
            await self._set_selection(message.sender_id, "agent")
            return self._reply(message, f"已切换到 {self._agent_label}。")
        if command == "/status":
            self._schedule(self._send_status(message), name=f"acode-status-{message.id}")
            return True
        if command == "/doctor":
            self._schedule(self._send_doctor(message), name=f"acode-doctor-{message.id}")
            return True
        if command == "/stop":
            thread_id = self._selected_thread(message.sender_id)
            if not thread_id:
                return self._reply(message, f"当前正在和 {self._agent_label} 聊天，没有选中 Codex 任务。")
            self._schedule(self._stop_thread(message, thread_id), name=f"acode-stop-{message.id}")
            return True
        if command == "/new":
            self._schedule(self._create_thread_from_command(message, content), name=f"acode-new-{message.id}")
            return True
        if command == "/rename":
            self._schedule(self._rename_thread(message, content), name=f"acode-rename-{message.id}")
            return True
        if command == "/archive":
            thread_id = self._selected_thread(message.sender_id)
            if not thread_id:
                return self._reply(message, "当前没有选中可归档的 Codex 任务。")
            return self._reply(
                message,
                "确认归档当前任务？归档后可以从 /archived 恢复。",
                keyboard=[[{"text": "确认归档", "callback_data": f"acode:archive:{thread_id}"}]],
            )
        if command == "/archived":
            self._schedule(self._send_archived(message), name=f"acode-archived-{message.id}")
            return True

        thread_id = self._selected_thread(message.sender_id)
        if not thread_id:
            return False
        attachments = self._message_attachments(message)
        if message.type != "text" and not attachments:
            return self._reply(message, "没有读取到可用附件，请重新发送图片或文件。")
        if not content or content in {"[图片]", "[文件]", "[视频]", "[语音]"}:
            content = "请查看并处理我发送的附件。"
        if not self._is_configured():
            return self._reply(message, self._configuration_error())

        if attachments:
            media_group_id = str(message.raw.get("telegram_media_group_id") or "").strip()
            if media_group_id:
                await self._queue_album(
                    message,
                    thread_id,
                    media_group_id,
                    content,
                    attachments,
                )
            else:
                self._schedule(
                    self._process_prompt(message, thread_id, content, attachments=attachments),
                    name=f"acode-prompt-{message.id}",
                )
        else:
            self._schedule(
                self._process_prompt(message, thread_id, content),
                name=f"acode-prompt-{message.id}",
            )
        return True

    async def _handle_callback(self, message: Message, content: str):
        if not content.startswith("acode:"):
            return False
        if content in {"acode:menu", "acode:refresh"}:
            self._schedule(self._send_menu(message), name=f"acode-menu-{message.id}")
            return True
        if content == "acode:status":
            self._schedule(self._send_status(message), name=f"acode-status-{message.id}")
            return True
        if content == "acode:doctor":
            self._schedule(self._send_doctor(message), name=f"acode-doctor-{message.id}")
            return True
        if content == "acode:noop":
            return True
        if content.startswith(("acode:page:", "acode:refresh:")):
            try:
                page = max(0, int(content.rsplit(":", 1)[-1]))
            except ValueError:
                page = 0
            self._schedule(self._send_menu(message, page=page), name=f"acode-menu-{message.id}")
            return True
        if content == "acode:agent":
            await self._set_selection(message.sender_id, "agent")
            return self._reply(
                message,
                f"*✅ 已切换聊天对象*\n\n当前：{self._md_escape(self._agent_label)}\n接下来发送的消息会交给现有 Agent。",
                keyboard=[[{"text": "📋 选择 Codex 任务", "callback_data": "acode:menu"}]],
                edit=True,
                markdown=True,
            )
        if content == "acode:stop":
            thread_id = self._selected_thread(message.sender_id)
            if not thread_id:
                return self._reply(message, "当前没有选中 Codex 任务。")
            self._schedule(self._stop_thread(message, thread_id), name=f"acode-stop-{message.id}")
            return True
        if content.startswith("acode:favorite:"):
            thread_id = content.removeprefix("acode:favorite:").strip()
            if not thread_id or len(thread_id) > 64:
                return self._reply(message, "任务编号无效，请刷新任务列表。")
            self._schedule(
                self._toggle_favorite(message, thread_id),
                name=f"acode-favorite-{message.id}",
            )
            return True
        if content.startswith("acode:search:"):
            parts = content.split(":")
            token = parts[2] if len(parts) > 2 else ""
            try:
                page = max(0, int(parts[3]))
            except (IndexError, ValueError):
                page = 0
            search = self._searches.get(token)
            if not search or search.get("sender_id") != message.sender_id:
                return self._reply(message, "搜索结果已过期，请重新发送 /find。")
            self._schedule(
                self._send_search_results(message, search["query"], page=page, token=token),
                name=f"acode-search-page-{message.id}",
            )
            return True
        if content.startswith("acode:approval:"):
            parts = content.split(":", 3)
            if len(parts) != 4 or parts[2] not in {"allow", "deny"}:
                return self._reply(message, "审批操作无效。")
            self._schedule(
                self._resolve_approval(message, parts[3], parts[2]),
                name=f"acode-approval-{message.id}",
            )
            return True
        if content.startswith("acode:archive:"):
            self._schedule(
                self._archive_thread(message, content.removeprefix("acode:archive:")),
                name=f"acode-archive-{message.id}",
            )
            return True
        if content.startswith("acode:restore:"):
            self._schedule(
                self._restore_thread(message, content.removeprefix("acode:restore:")),
                name=f"acode-restore-{message.id}",
            )
            return True
        if content.startswith("acode:fork:"):
            request_id = content.removeprefix("acode:fork:").strip()
            self._schedule(
                self._fork_and_send(message, request_id),
                name=f"acode-fork-{message.id}",
            )
            return True
        if content.startswith("acode:thread:"):
            thread_id = content.removeprefix("acode:thread:").strip()
            if not thread_id or len(thread_id) > 64:
                return self._reply(message, "任务编号无效，请刷新任务列表。")
            self._schedule(
                self._select_thread(message, thread_id),
                name=f"acode-select-{message.id}",
            )
            return True
        return True

    async def _send_menu(self, message: Message, *, page: int | None = None) -> None:
        if not self._enabled:
            await self._send(message, self._configuration_error())
            return
        if not self._is_configured():
            await self._send(message, self._configuration_error())
            return
        favorite_ids = set(self._favorites.get(message.sender_id, []))
        try:
            threads = await self._list_threads(limit=100 if favorite_ids else self._max_threads)
        except Exception as exc:
            await self._send(message, f"暂时无法读取 Codex 任务：{self._safe_error(exc)}")
            return

        current = self._selections.get(message.sender_id, "agent")
        threads.sort(key=lambda thread: str(thread.get("id") or "") not in favorite_ids)
        threads = threads[:self._max_threads]
        pages = self._menu_pages(threads)
        if not pages:
            await self._send(
                message,
                "*🧭 Codex 远程工作台*\n\n暂时没有可显示的 Codex 任务。",
                keyboard=[[{"text": "🔄 刷新", "callback_data": "acode:refresh:0"}]],
                edit=message.type == "event",
                markdown=True,
            )
            return
        for thread in threads:
            thread_id = str(thread.get("id") or "").strip()
            if thread_id:
                self._thread_titles[thread_id] = self._thread_title(thread)
        if page is None:
            page = next(
                (
                    index
                    for index, item in enumerate(pages)
                    if any(str(thread.get("id") or "") == current for thread in item["threads"])
                ),
                0,
            )
        page = min(max(0, page), len(pages) - 1)
        current_page = pages[page]
        rows: list[list[dict[str, str]]] = [[{
            "text": f"{'✅' if current == 'agent' else '💬'} {self._agent_label}｜现有 Agent",
            "callback_data": "acode:agent",
        }]]
        details: list[str] = []
        for index, thread in enumerate(current_page["threads"], start=1):
            thread_id = str(thread.get("id") or "").strip()
            if not thread_id:
                continue
            title = self._thread_title(thread)
            status = str(thread.get("status") or "completed")
            icon = self._status_icon(status)
            selected = current == thread_id
            favorite = thread_id in favorite_ids
            rows.append([{
                "text": f"{'✅' if selected else icon} {index}. {title}"[:54],
                "callback_data": f"acode:thread:{thread_id}",
            }, {
                "text": "★" if favorite else "☆",
                "callback_data": f"acode:favorite:{thread_id}",
            }])
            details.append(
                f"{index}. {'⭐ ' if favorite else ''}{icon} {self._md_escape(title)}"
            )
        if len(pages) > 1:
            rows.append([
                {"text": "◀️ 上一页", "callback_data": f"acode:page:{(page - 1) % len(pages)}"},
                {"text": f"{page + 1}/{len(pages)}", "callback_data": "acode:noop"},
                {"text": "下一页 ▶️", "callback_data": f"acode:page:{(page + 1) % len(pages)}"},
            ])
        rows.append([
            {"text": "🔄 刷新本页", "callback_data": f"acode:refresh:{page}"},
            {"text": "⏹ 停止当前任务", "callback_data": "acode:stop"},
        ])
        current_label = self._agent_label if current == "agent" else self._thread_titles.get(current, current[:8])
        content = (
            "*🧭 Codex 远程工作台*\n\n"
            f"当前：{self._md_escape(current_label)}\n"
            f"项目：*📁 {self._md_escape(current_page['project'])}*\n"
            f"路径：{self._md_escape(current_page['path'])}\n\n"
            "*本页任务*\n"
            + "\n".join(details)
            + f"\n\n第 {page + 1}/{len(pages)} 页 · 共 {len(threads)} 个最近任务\n"
            "点击任务即可切换，☆ 可收藏；搜索请发送 /find 关键词。"
        )
        await self._send(
            message,
            content,
            keyboard=rows,
            edit=message.type == "event",
            markdown=True,
        )

    async def _send_search_results(
        self,
        message: Message,
        query: str,
        *,
        page: int = 0,
        token: str = "",
    ) -> None:
        if not self._is_configured():
            await self._send(message, self._configuration_error())
            return
        try:
            threads = await self._list_threads(limit=100)
        except Exception as exc:
            await self._send(message, f"任务搜索失败：{self._safe_error(exc)}")
            return
        terms = [term for term in query.casefold().split() if term]
        matches = [
            thread
            for thread in threads
            if all(
                term in (
                    f"{self._thread_title(thread)} {thread.get('cwd') or ''}"
                ).casefold()
                for term in terms
            )
        ]
        favorite_ids = set(self._favorites.get(message.sender_id, []))
        matches.sort(key=lambda thread: str(thread.get("id") or "") not in favorite_ids)
        if not matches:
            await self._send(
                message,
                f"没有找到包含“{query[:40]}”的 Codex 任务。",
            )
            return
        token = token or secrets.token_hex(6)
        self._searches[token] = {"query": query, "sender_id": message.sender_id}
        page_size = 5
        pages = max(1, (len(matches) + page_size - 1) // page_size)
        page = min(page, pages - 1)
        start = page * page_size
        rows: list[list[dict[str, str]]] = []
        details: list[str] = []
        for index, thread in enumerate(matches[start:start + page_size], start=start + 1):
            thread_id = str(thread.get("id") or "").strip()
            if not thread_id:
                continue
            title = self._thread_title(thread)
            self._thread_titles[thread_id] = title
            favorite = thread_id in favorite_ids
            cwd = str(thread.get("cwd") or "未标记项目").removeprefix("\\\\?\\")
            project = next(
                (part for part in reversed(re.split(r"[\\/]+", cwd)) if part),
                "未标记项目",
            )
            rows.append([{
                "text": f"{index}. {title}"[:54],
                "callback_data": f"acode:thread:{thread_id}",
            }, {
                "text": "★" if favorite else "☆",
                "callback_data": f"acode:favorite:{thread_id}",
            }])
            details.append(
                f"{index}. {'⭐ ' if favorite else ''}*{self._md_escape(title)}*"
                f"\n   📁 {self._md_escape(project)}"
            )
        if pages > 1:
            rows.append([
                {"text": "◀️", "callback_data": f"acode:search:{token}:{(page - 1) % pages}"},
                {"text": f"{page + 1}/{pages}", "callback_data": "acode:noop"},
                {"text": "▶️", "callback_data": f"acode:search:{token}:{(page + 1) % pages}"},
            ])
        rows.append([{"text": "📋 返回全部任务", "callback_data": "acode:menu"}])
        await self._send(
            message,
            f"*🔎 任务搜索*\n\n关键词：{self._md_escape(query[:40])}\n\n"
            + "\n".join(details)
            + f"\n\n共找到 {len(matches)} 个 · 第 {page + 1}/{pages} 页",
            keyboard=rows,
            edit=message.type == "event",
            markdown=True,
        )

    async def _configure_telegram_menu(self) -> None:
        commands = [
            {"command": "codex", "description": "选择 Codex 任务"},
            {"command": "find", "description": "搜索 Codex 任务"},
            {"command": "new", "description": "安全创建 Codex 任务"},
            {"command": "rename", "description": "重命名当前任务"},
            {"command": "archive", "description": "归档当前任务"},
            {"command": "archived", "description": "恢复已归档任务"},
            {"command": "status", "description": "查看当前聊天对象"},
            {"command": "doctor", "description": "检查远程链路状态"},
            {"command": "stop", "description": "停止当前 Codex 任务"},
            {"command": "agent", "description": f"切回{self._agent_label}"[:20]},
            {"command": "help", "description": "打开 Codex 工作台"},
        ]
        for _ in range(30):
            adapters = self._ctx.adapters if self._ctx else None
            adapter = adapters.get("telegram") if adapters and hasattr(adapters, "get") else None
            configure = getattr(adapter, "configure_command_menu", None)
            if callable(configure):
                try:
                    await configure(sorted(self._allowed_user_ids), commands)
                    logger.info(
                        "[acode_remote] Telegram 管理员私聊菜单已配置: users={} commands={}",
                        len(self._allowed_user_ids),
                        len(commands),
                    )
                except Exception as exc:
                    logger.warning(
                        "[acode_remote] Telegram 私聊菜单配置失败: {}",
                        self._safe_error(exc),
                    )
                return
            await asyncio.sleep(1.0)
        logger.warning("[acode_remote] Telegram 适配器未就绪，私聊菜单未配置")

    async def _menu_refresh_loop(self) -> None:
        while self._is_configured():
            await asyncio.sleep(6 * 60 * 60)
            await self._configure_telegram_menu()

    async def _send_status(self, message: Message) -> None:
        thread_id = self._selected_thread(message.sender_id)
        if not thread_id:
            await self._send(message, f"当前聊天对象：{self._agent_label}｜现有 Agent")
            return
        try:
            payload = await self._request("GET", f"/sessions/{thread_id}")
            session = payload.get("session") if isinstance(payload, dict) else {}
            session = session if isinstance(session, dict) else {}
        except Exception as exc:
            await self._send(message, f"状态读取失败：{self._safe_error(exc)}")
            return
        status = str(session.get("status") or "completed")
        started = str(session.get("lastTurnStartedAt") or session.get("startedAt") or "")
        elapsed = "—"
        try:
            seconds = max(0, int(datetime.now(UTC).timestamp() - datetime.fromisoformat(started).timestamp()))
            elapsed = f"{seconds // 60}分{seconds % 60}秒"
        except (TypeError, ValueError):
            pass
        title = self._thread_titles.get(thread_id, str(session.get("title") or thread_id[:8]))
        workspace = str(session.get("workspacePath") or "未标记")
        await self._send(
            message,
            "*📊 Codex 运行状态*\n\n"
            f"任务：{self._md_escape(title)}\n"
            f"状态：{self._status_icon(status)} {self._md_escape(status)}\n"
            f"运行：{elapsed}\n"
            f"项目：{self._md_escape(self._short_path(workspace))}",
            keyboard=[[
                {"text": "🔄 刷新", "callback_data": "acode:status"},
                {"text": "⏹ 停止", "callback_data": "acode:stop"},
            ]],
            edit=message.type == "event",
            markdown=True,
        )

    async def _send_doctor(self, message: Message) -> None:
        checks: list[tuple[bool, str, str]] = []
        checks.append((self._is_configured(), "插件配置", "已启用并已加载私有配置"))

        adapters = self._ctx.adapters if self._ctx else None
        telegram = adapters.get("telegram") if adapters and hasattr(adapters, "get") else None
        telegram_ready = callable(getattr(telegram, "send_chat_action", None))
        checks.append((telegram_ready, "Telegram 通道", "适配器已连接" if telegram_ready else "适配器未就绪"))

        health: dict[str, Any] = {}
        gateway_error = ""
        started = time.perf_counter()
        try:
            payload = await self._request("GET", "/api/health")
            health = payload if isinstance(payload, dict) else {}
            gateway_ok = bool(health.get("ok"))
        except Exception as exc:
            gateway_ok = False
            gateway_error = self._safe_error(exc)
        elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
        gateway_detail = f"响应 {elapsed_ms} ms" if gateway_ok else gateway_error or "无法连接"
        checks.append((gateway_ok, "aCode 网关", gateway_detail))

        codex = health.get("codex") if isinstance(health.get("codex"), dict) else {}
        codex_ok = gateway_ok and bool(codex.get("connected")) and bool(codex.get("ready"))
        checks.append((codex_ok, "Codex 连接", "已连接并就绪" if codex_ok else "尚未就绪"))

        thread_id = self._selected_thread(message.sender_id)
        if thread_id and gateway_ok:
            try:
                status = await self._thread_status(thread_id)
                checks.append((True, "当前任务", f"事件链路正常 · {status}"))
            except Exception as exc:
                checks.append((False, "当前任务", self._safe_error(exc)))
        else:
            checks.append((True, "当前任务", "未选择 Codex 任务"))

        watchers = sum(not task.done() for task in self._watchers.values())
        checks.append((
            watchers >= len(self._runs),
            "断线恢复",
            f"监听 {watchers} · 待补发 {len(self._runs)}",
        ))

        voice_installed = importlib.util.find_spec("faster_whisper") is not None
        if not self._voice_transcription_enabled:
            voice_detail = "功能已关闭"
        elif voice_installed:
            voice_detail = f"组件已安装 · {self._voice_transcription_model} 模型按需加载"
        else:
            voice_detail = "缺少 faster-whisper 组件"
        checks.append((not self._voice_transcription_enabled or voice_installed, "语音转写", voice_detail))

        failed = sum(not ok for ok, _, _ in checks)
        lines = [
            f"{'✅' if ok else '❌'} *{self._md_escape(label)}* · {self._md_escape(detail)}"
            for ok, label, detail in checks
        ]
        summary = "全部正常，可以继续使用。" if not failed else f"发现 {failed} 项异常，请把本卡片发给我。"
        await self._send(
            message,
            "*🩺 Codex 远程诊断*\n\n" + "\n".join(lines) + f"\n\n{self._md_escape(summary)}",
            keyboard=[[{
                "text": "🔄 重新检查",
                "callback_data": "acode:doctor",
            }]],
            edit=message.type == "event",
            markdown=True,
        )

    async def _create_thread_from_command(self, message: Message, content: str) -> None:
        argument = content.split(maxsplit=1)[1].strip() if len(content.split(maxsplit=1)) > 1 else ""
        if "|" not in argument:
            await self._send(message, "格式：/new 项目名 | 要交给 Codex 的任务")
            return
        project_query, prompt = (part.strip() for part in argument.split("|", 1))
        if not project_query or not prompt:
            await self._send(message, "项目名和任务内容都不能为空。")
            return
        try:
            payload = await self._request("GET", "/api/workspaces")
            workspaces = payload.get("data") if isinstance(payload, dict) else []
            matches = [item for item in workspaces if isinstance(item, dict) and project_query.casefold() in f"{item.get('name')} {item.get('cwd')}".casefold()]
            if len(matches) != 1:
                names = "、".join(str(item.get("name") or "") for item in matches[:8]) or "无"
                await self._send(message, f"项目匹配不唯一或不存在：{names}")
                return
            cwd = str(matches[0]["cwd"])
            response = await self._request("POST", "/api/threads", payload={
                "cwd": cwd,
                "text": prompt,
                "title": prompt[:80],
            })
        except Exception as exc:
            await self._send(message, f"创建任务失败：{self._safe_error(exc)}")
            return
        thread_id = str(response.get("threadId") or "") if isinstance(response, dict) else ""
        if not thread_id:
            await self._send(message, "创建任务失败：aCode 未返回任务编号")
            return
        title = prompt[:32]
        self._thread_titles[thread_id] = title
        await self._set_selection(message.sender_id, thread_id)
        run_key = await self._register_run(
            thread_id=thread_id,
            turn_id=self._turn_id(response),
            title=title,
            started_at=datetime.now(UTC).timestamp(),
            conversation_id=message.conversation_id,
            prefer_existing=False,
        )
        sent = await self._send(message, self._live_progress("", []), markdown=True)
        sent_id = self._sent_message_id(sent)
        if sent_id:
            await self._set_progress_message(run_key, message.conversation_id, sent_id)
        self._start_watcher(run_key)

    async def _rename_thread(self, message: Message, content: str) -> None:
        thread_id = self._selected_thread(message.sender_id)
        title = content.split(maxsplit=1)[1].strip() if len(content.split(maxsplit=1)) > 1 else ""
        if not thread_id or not title:
            await self._send(message, "格式：/rename 新任务名称")
            return
        try:
            await self._request("PATCH", f"/api/threads/{thread_id}", payload={"title": title[:200]})
        except Exception as exc:
            await self._send(message, f"重命名失败：{self._safe_error(exc)}")
            return
        self._thread_titles[thread_id] = title[:32]
        await self._send(message, f"任务已重命名为：{title[:80]}")

    async def _archive_thread(self, message: Message, thread_id: str) -> None:
        try:
            await self._request("POST", f"/api/threads/{thread_id}/archive", payload={})
        except Exception as exc:
            await self._send(message, f"归档失败：{self._safe_error(exc)}", edit=True)
            return
        await self._set_selection(message.sender_id, "agent")
        await self._send(message, "任务已归档，可通过 /archived 恢复。", edit=True)

    async def _send_archived(self, message: Message) -> None:
        try:
            payload = await self._request("GET", "/api/threads?limit=20&archived=true")
        except Exception as exc:
            await self._send(message, f"归档列表读取失败：{self._safe_error(exc)}")
            return
        items = payload.get("data") if isinstance(payload, dict) else []
        rows = [[{"text": f"恢复 {self._thread_title(item)}"[:60], "callback_data": f"acode:restore:{item.get('id')}"}]
                for item in items if isinstance(item, dict) and item.get("id")]
        await self._send(message, "*🗄 已归档任务*\n\n点击下方任务即可恢复。" if rows else "暂无已归档任务。", keyboard=rows or None, markdown=bool(rows))

    async def _restore_thread(self, message: Message, thread_id: str) -> None:
        try:
            await self._request("POST", f"/api/threads/{thread_id}/unarchive", payload={})
        except Exception as exc:
            await self._send(message, f"恢复失败：{self._safe_error(exc)}", edit=True)
            return
        await self._send(message, "任务已恢复。", keyboard=[[{"text": "📋 返回任务列表", "callback_data": "acode:menu"}]], edit=True)

    async def _resolve_approval(self, message: Message, approval_id: str, decision: str) -> None:
        try:
            await self._request("POST", f"/api/approvals/{approval_id}/resolve", payload={"decision": decision})
        except Exception as exc:
            await self._send(message, f"审批失败：{self._safe_error(exc)}", edit=True)
            return
        label = "✅ 已允许" if decision == "allow" else "⛔ 已拒绝"
        await self._send(message, label, keyboard=[], edit=True)

    async def _toggle_favorite(self, message: Message, thread_id: str) -> None:
        async with self._state_lock:
            favorites = set(self._favorites.get(message.sender_id, []))
            if thread_id in favorites:
                favorites.remove(thread_id)
            else:
                favorites.add(thread_id)
            self._favorites[message.sender_id] = sorted(favorites)
            if self._ctx:
                await asyncio.to_thread(
                    self._write_json,
                    self._ctx.data_dir / "favorites.json",
                    self._favorites,
                )
        await self._send_menu(message)

    async def _queue_album(
        self,
        message: Message,
        thread_id: str,
        media_group_id: str,
        content: str,
        attachments: list[dict[str, Any]],
    ) -> None:
        key = f"{message.conversation_id}:{message.sender_id}:{media_group_id}"
        async with self._album_lock:
            batch = self._album_batches.setdefault(key, {
                "message": message,
                "thread_id": thread_id,
                "contents": [],
                "attachments": [],
                "task": None,
            })
            if content and content not in batch["contents"]:
                batch["contents"].append(content)
            batch["attachments"].extend(attachments)
            previous = batch.get("task")
            if isinstance(previous, asyncio.Task):
                previous.cancel()
            task = asyncio.create_task(
                self._flush_album(key),
                name=f"acode-album-{media_group_id[:16]}",
            )
            batch["task"] = task
            self._track(task)

    async def _flush_album(self, key: str) -> None:
        await asyncio.sleep(self._album_delay)
        async with self._album_lock:
            batch = self._album_batches.pop(key, None)
        if not isinstance(batch, dict):
            return
        attachments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for attachment in batch.get("attachments", []):
            if not isinstance(attachment, dict):
                continue
            identity = str(
                attachment.get("file_unique_id")
                or attachment.get("file_id")
                or attachment.get("local_path")
                or len(attachments)
            )
            if identity in seen:
                continue
            seen.add(identity)
            attachments.append(attachment)
        contents = [
            str(item)
            for item in batch.get("contents", [])
            if str(item) != "请查看并处理我发送的附件。"
        ]
        content = "\n".join(contents) if contents else "请查看并处理我发送的这些附件。"
        await self._process_prompt(
            batch["message"],
            str(batch["thread_id"]),
            content,
            attachments=attachments,
        )

    async def _select_thread(self, message: Message, thread_id: str) -> None:
        if not self._is_configured():
            await self._send(message, self._configuration_error())
            return
        try:
            threads = await self._list_threads(limit=100)
        except Exception as exc:
            await self._send(message, f"任务列表读取失败：{self._safe_error(exc)}")
            return
        thread = next((item for item in threads if str(item.get("id") or "") == thread_id), None)
        if thread is None:
            await self._send(message, "任务不存在或已不可见，请刷新任务列表。")
            return
        title = self._thread_title(thread)
        self._thread_titles[thread_id] = title
        await self._set_selection(message.sender_id, thread_id)
        await self._send(
            message,
            f"*✅ 已切换到 Codex*\n\n任务：{self._md_escape(title)}\n接下来发送的文字会进入这个任务。",
            keyboard=[
                [{"text": "💬 切回小X", "callback_data": "acode:agent"}],
                [
                    {"text": "📋 任务列表", "callback_data": "acode:menu"},
                    {"text": "⏹ 停止任务", "callback_data": "acode:stop"},
                ],
            ],
            edit=message.type == "event",
            markdown=True,
        )

    async def _process_prompt(
        self,
        message: Message,
        thread_id: str,
        content: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        title = self._thread_titles.get(thread_id, thread_id[:8])
        started_at = datetime.now(UTC).timestamp()
        await self._send_chat_action(
            message.conversation_id,
            self._attachment_action(attachments) if attachments else "typing",
        )
        try:
            if attachments and self._voice_transcription_enabled:
                content, attachments = await self._transcribe_voice(content, attachments)
            status = await self._thread_status(thread_id)
            steering = status in {
                "running", "starting", "waiting-approval"
            }
            if steering and attachments:
                await self._send(
                    message,
                    "当前任务正在运行，暂时不能追加图片或文件。请等待本轮结束后再发送。",
                )
                return
            path = (
                f"/api/threads/{thread_id}/interjections"
                if steering
                else f"/api/threads/{thread_id}/turns"
            )
            payload: dict[str, Any] = {"text": content}
            if attachments:
                payload["attachments"] = await asyncio.to_thread(
                    self._encode_attachments,
                    attachments,
                )
            response = await self._request("POST", path, payload=payload)
        except AttachmentError as exc:
            await self._send(message, str(exc))
            return
        except AcodeApiError as exc:
            if self._is_active_writer_error(exc):
                await self._send_fork_offer(message, thread_id, title, content)
                return
            if exc.status == 409:
                await self._send(
                    message,
                    f"Codex 当前不能接收这条消息：{self._safe_error(exc)}",
                    keyboard=[[{"text": "⏹ 停止任务", "callback_data": "acode:stop"}]],
                )
            else:
                await self._send(message, f"发送到 Codex 失败：{self._safe_error(exc)}")
            return
        except Exception as exc:
            if self._is_active_writer_error(exc):
                await self._send_fork_offer(message, thread_id, title, content)
                return
            await self._send(message, f"发送到 Codex 失败：{self._safe_error(exc)}")
            return

        turn_id = self._turn_id(response)
        run_key = await self._register_run(
            thread_id=thread_id,
            turn_id=turn_id,
            title=title,
            started_at=started_at,
            conversation_id=message.conversation_id,
            prefer_existing=steering,
        )
        run = self._runs.get(run_key, {})
        targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
        if not str(targets.get(message.conversation_id) or ""):
            try:
                sent = await self._send(
                    message,
                    self._live_progress("", []),
                    keyboard=[[{"text": "⏹ 停止", "callback_data": "acode:stop"}]],
                    markdown=True,
                )
                message_id = self._sent_message_id(sent)
                if message_id:
                    await self._set_progress_message(run_key, message.conversation_id, message_id)
            except Exception as exc:
                logger.warning(
                    "[acode_remote] 创建实时进度消息失败: thread={} turn={} error={}",
                    thread_id,
                    turn_id,
                    self._safe_error(exc),
                )
        self._start_watcher(run_key)

    async def _transcribe_voice(
        self,
        content: str,
        attachments: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        voice_items = [
            item for item in attachments
            if str(item.get("type") or "") in {"voice", "audio"}
        ]
        if not voice_items:
            return content, attachments
        if len(voice_items) != len(attachments):
            raise AttachmentError("语音暂时不能和其他附件一起发送，请分开发送。")
        transcripts: list[str] = []
        for item in voice_items:
            raw_path = str(item.get("local_path") or "").strip()
            if item.get("download_error") or not raw_path or not Path(raw_path).is_file():
                raise AttachmentError("语音下载失败，请重新发送。")
            transcripts.append(await self._transcribe_file(Path(raw_path)))
        transcript = "\n".join(part for part in transcripts if part).strip()
        if not transcript:
            raise AttachmentError("没有识别到清晰的语音内容，请重试或直接发送文字。")
        prefix = "" if content in {"", "请查看并处理我发送的附件。"} else f"{content}\n\n"
        return f"{prefix}这是我的语音转写内容，请直接处理：\n{transcript[:20000]}", []

    async def _transcribe_file(self, path: Path) -> str:
        async with self._voice_lock:
            if self._voice_model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise AttachmentError("服务器尚未安装语音转写组件，请管理员完成部署。") from exc
                if not self._ctx:
                    raise AttachmentError("语音转写组件尚未就绪。")
                cache_dir = self._ctx.data_dir / "whisper"
                cache_dir.mkdir(parents=True, exist_ok=True)
                self._voice_model = await asyncio.to_thread(
                    WhisperModel,
                    self._voice_transcription_model,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(cache_dir),
                )
            try:
                segments, _info = await asyncio.to_thread(
                    self._voice_model.transcribe,
                    str(path),
                    beam_size=1,
                    vad_filter=True,
                )
                return await asyncio.to_thread(
                    lambda: "".join(str(segment.text) for segment in segments).strip()
                )
            except Exception as exc:
                raise AttachmentError("语音转写失败，请稍后重试。") from exc

    async def _send_fork_offer(
        self,
        message: Message,
        thread_id: str,
        title: str,
        content: str,
    ) -> None:
        request_id = secrets.token_hex(16)
        now = asyncio.get_running_loop().time()
        async with self._fork_lock:
            self._fork_requests = {
                key: value
                for key, value in self._fork_requests.items()
                if now - float(value.get("created_at") or 0) < 3600
            }
            self._fork_requests[request_id] = {
                "sender_id": message.sender_id,
                "conversation_id": message.conversation_id,
                "source_thread_id": thread_id,
                "source_title": title,
                "content": content,
                "created_at": now,
                "processing": False,
                "forked_thread_id": "",
            }
        await self._send(
            message,
            "*🔒 电脑端正在使用这个任务*\n\n"
            f"任务：{self._md_escape(title)}\n"
            "可以复制当前历史创建 TG 分支，电脑端任务不会停止。",
            keyboard=[[
                {"text": "🌿 创建 TG 分支并继续", "callback_data": f"acode:fork:{request_id}"},
            ], [
                {"text": "📋 选择其他任务", "callback_data": "acode:menu"},
            ]],
            markdown=True,
        )

    async def _fork_and_send(self, message: Message, request_id: str) -> None:
        async with self._fork_lock:
            request = self._fork_requests.get(request_id)
            if not request or request.get("sender_id") != message.sender_id or request.get("conversation_id") != message.conversation_id:
                await self._send(
                    message,
                    "这个分支请求已过期，请重新发送刚才的消息。",
                    edit=True,
                )
                return
            if request.get("forked_thread_id"):
                thread_id = str(request["forked_thread_id"])
                await self._set_selection(message.sender_id, thread_id)
                await self._send(
                    message,
                    f"*✅ TG 分支已存在*\n\n当前：{self._md_escape(str(request['fork_title']))}",
                    keyboard=[[{"text": "📋 返回任务列表", "callback_data": "acode:menu"}]],
                    edit=True,
                    markdown=True,
                )
                return
            if request.get("processing"):
                await self._send(message, "TG 分支正在创建，请稍候。", edit=True)
                return
            request["processing"] = True

        source_thread_id = str(request["source_thread_id"])
        fork_title = f"TG｜{request['source_title']}"[:80]
        try:
            response = await self._request(
                "POST",
                f"/api/threads/{source_thread_id}/fork",
                payload={"title": fork_title, "idempotency_key": request_id},
            )
            forked_thread_id = str(response.get("threadId") or "") if isinstance(response, dict) else ""
            if not forked_thread_id:
                raise RuntimeError("aCode 未返回 TG 分支任务编号")
            async with self._fork_lock:
                request["forked_thread_id"] = forked_thread_id
                request["fork_title"] = fork_title
                request["processing"] = False
            self._thread_titles[forked_thread_id] = fork_title
            await self._set_selection(message.sender_id, forked_thread_id)
            await self._send(
                message,
                f"*🌿 TG 分支创建成功*\n\n当前：{self._md_escape(fork_title)}\n正在继续发送刚才的消息。",
                keyboard=[[{"text": "📋 返回任务列表", "callback_data": "acode:menu"}]],
                edit=True,
                markdown=True,
            )
            await self._process_prompt(message, forked_thread_id, str(request["content"]))
        except Exception as exc:
            async with self._fork_lock:
                request["processing"] = False
            await self._send(
                message,
                f"创建 TG 分支失败：{self._safe_error(exc)}",
                keyboard=[[{
                    "text": "🔄 重新创建",
                    "callback_data": f"acode:fork:{request_id}",
                }]],
                edit=True,
            )

    async def _watch_run(self, run_key: str) -> None:
        run = self._runs.get(run_key)
        if not isinstance(run, dict):
            return
        thread_id = str(run.get("thread_id") or "")
        started_at = self._timestamp_number(run.get("started_at"))
        turn_id = str(run.get("turn_id") or "")
        completed_messages: list[str] = []
        agent_chunks: dict[str, list[str]] = {}
        latest_agent_id = ""
        tool_steps: list[str] = []
        running_tools: dict[str, int] = {}
        processed_count = 0
        last_live_content = ""
        timeout_due_at = (
            started_at + self._result_timeout
            if started_at > 0
            else time.time() + self._result_timeout
        )
        final_status = "completed"
        typing_task = asyncio.create_task(
            self._typing_heartbeat(run_key),
            name=f"acode-typing-{thread_id[:8]}-{turn_id[:8] or 'pending'}",
        )
        try:
            while True:
                payload = await self._request("GET", f"/sessions/{thread_id}/events")
                entries = payload.get("events") if isinstance(payload, dict) else []
                current_entries = entries if isinstance(entries, list) else []
                if len(current_entries) < processed_count:
                    processed_count = 0
                new_entries = current_entries[processed_count:]
                processed_count = len(current_entries)
                finished = False
                for entry in new_entries:
                    event = entry.get("message") if isinstance(entry, dict) else None
                    if not isinstance(event, dict) or not self._event_is_current(event, started_at):
                        continue
                    if not self._event_matches_turn(event, turn_id):
                        continue
                    event_type = str(event.get("type") or "")
                    event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                    if event_type == "approval-requested":
                        await self._auto_approve(event_payload)
                        continue
                    if event_type == "session-output":
                        output_type = str(event_payload.get("eventType") or "")
                        if output_type == "item/agentMessage/delta":
                            chunk = str(event_payload.get("chunk") or "")
                            if chunk:
                                if not running_tools:
                                    tool_steps.clear()
                                latest_agent_id = self._event_item_id(event_payload) or latest_agent_id or "agent"
                                agent_chunks.setdefault(latest_agent_id, []).append(chunk)
                        elif output_type == "item/completed":
                            text = self._completed_agent_text(event_payload)
                            if text:
                                completed_messages.append(text)
                                latest_agent_id = self._completed_item_id(event_payload) or latest_agent_id
                        self._update_tool_steps(event_payload, tool_steps, running_tools)
                    if event_type == "session-finished":
                        finished_text = self._finished_agent_text(event_payload)
                        if finished_text:
                            completed_messages.append(finished_text)
                        final_status = self._finished_status(event_payload)
                        finished = True

                partial = "".join(agent_chunks.get(latest_agent_id, [])) if latest_agent_id else ""
                if finished:
                    if tool_steps:
                        live_content = self._live_progress(partial, tool_steps)
                        if live_content != last_live_content:
                            await self._update_live_message(run_key, live_content)
                    output = completed_messages[-1] if completed_messages else partial
                    await self._deliver_result(run_key, output, final_status)
                    return
                live_content = self._live_progress(partial, tool_steps)
                if live_content != last_live_content:
                    await self._update_live_message(run_key, live_content)
                    last_live_content = live_content
                if time.time() >= timeout_due_at:
                    await self._deliver_timeout(run_key)
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[acode_remote] 任务监听失败: thread={} error={}",
                thread_id,
                self._safe_error(exc),
            )
            await self._deliver_retry_notice(run_key)
        finally:
            typing_task.cancel()
            await asyncio.gather(typing_task, return_exceptions=True)

    async def _deliver_result(self, run_key: str, output: str, status: str) -> None:
        run = self._runs.get(run_key)
        if not isinstance(run, dict):
            return
        targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
        delivered = {str(item) for item in run.get("delivered_to", [])}
        if status == "completed":
            content = output.strip() or "任务已完成，没有返回文字内容。"
        elif status == "cancelled":
            content = output.strip() or "任务已停止。"
        else:
            content = output.strip() or "任务执行失败，请查看 aCode 或 Codex 日志。"
        for conversation_id in targets:
            if conversation_id in delivered:
                continue
            await self._finish_live_message(run_key, conversation_id, content)
            await self._mark_delivered(run_key, conversation_id)

    async def _auto_approve(self, payload: dict[str, Any]) -> None:
        approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else {}
        approval_id = str(approval.get("id") or "")
        if not approval_id or approval_id in self._shown_approvals:
            return
        self._shown_approvals.add(approval_id)
        try:
            await self._request(
                "POST",
                f"/api/approvals/{approval_id}/resolve",
                payload={"decision": "allow"},
            )
            logger.info("[acode_remote] TG 完全模式已自动允许本次操作")
        except Exception as exc:
            logger.warning(
                "[acode_remote] TG 完全模式自动授权失败: {}",
                self._safe_error(exc),
            )

    async def _deliver_timeout(self, run_key: str) -> None:
        run = self._runs.get(run_key, {})
        targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
        delivered = {str(item) for item in run.get("delivered_to", [])}
        notified = {str(item) for item in run.get("timeout_notified_to", [])}
        thread_id = str(run.get("thread_id") or "")
        for conversation_id, message_id in dict(targets).items():
            if conversation_id in delivered or conversation_id in notified:
                continue
            try:
                response = await self._send_to_conversation(
                    conversation_id,
                    "等待实时结果超时，任务仍在电脑端继续运行；完成后会自动更新这里。",
                    keyboard=[[{"text": "⏹ 停止", "callback_data": "acode:stop"}]],
                    edit_message_id=str(message_id or ""),
                )
            except Exception as exc:
                if not message_id:
                    raise
                logger.warning(
                    "[acode_remote] 超时提示编辑失败，改为新消息发送: thread={} error={}",
                    thread_id,
                    self._safe_error(exc),
                )
                response = await self._send_to_conversation(
                    conversation_id,
                    "等待实时结果超时，任务仍在电脑端继续运行；完成后会自动更新这里。",
                    keyboard=[[{"text": "⏹ 停止", "callback_data": "acode:stop"}]],
                )
            sent_id = self._sent_message_id(response)
            if sent_id and sent_id != str(message_id or ""):
                await self._set_progress_message(run_key, conversation_id, sent_id)
            await self._mark_timeout_notified(run_key, conversation_id)

    async def _deliver_retry_notice(self, run_key: str) -> None:
        run = self._runs.get(run_key, {})
        targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
        delivered = {str(item) for item in run.get("delivered_to", [])}
        for conversation_id in targets:
            if conversation_id in delivered:
                continue
            message_id = str(targets.get(conversation_id) or "")
            try:
                await self._send_to_conversation(
                    conversation_id,
                    "🌐 连接暂时中断，正在自动重试…",
                    keyboard=[[{"text": "⏹ 停止", "callback_data": "acode:stop"}]],
                    edit_message_id=message_id,
                )
            except Exception as exc:
                logger.debug(
                    "[acode_remote] 重试提示发送失败: error={}",
                    type(exc).__name__,
                )
                continue

    async def _retry_pending_loop(self) -> None:
        while self._is_configured():
            await asyncio.sleep(10)
            for run_key in list(self._runs):
                watcher = self._watchers.get(run_key)
                if watcher is None or watcher.done():
                    self._start_watcher(run_key)

    async def _maintenance_loop(self) -> None:
        await asyncio.sleep(60)
        while self._is_configured() and self._maintenance_enabled:
            try:
                await self._run_maintenance()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "[acode_remote] 附件维护失败: error={}",
                    self._safe_error(exc),
                )
            await asyncio.sleep(24 * 60 * 60)

    async def _run_maintenance(self) -> None:
        local_preview = await asyncio.to_thread(self._cleanup_telegram_media, True)
        outbound_preview = await asyncio.to_thread(self._cleanup_outbound, True)
        remote_preview = await self._request(
            "POST",
            "/api/maintenance/cleanup",
            payload={"retention_days": self._retention_days, "dry_run": True},
        )
        local_result = await asyncio.to_thread(self._cleanup_telegram_media, False)
        outbound_result = await asyncio.to_thread(self._cleanup_outbound, False)
        remote_result = await self._request(
            "POST",
            "/api/maintenance/cleanup",
            payload={"retention_days": self._retention_days, "dry_run": False},
        )
        logger.info(
            "[acode_remote] 附件维护完成: local_candidates={} local_removed={} remote_candidates={} remote_removed={}",
            local_preview["eligible_files"] + outbound_preview["eligible_files"],
            local_result["removed_files"] + outbound_result["removed_files"],
            int(remote_preview.get("eligibleFiles") or 0) if isinstance(remote_preview, dict) else 0,
            int(remote_result.get("removedFiles") or 0) if isinstance(remote_result, dict) else 0,
        )

    def _cleanup_telegram_media(self, dry_run: bool) -> dict[str, int]:
        adapters = self._ctx.adapters if self._ctx else None
        adapter = adapters.get("telegram") if adapters and hasattr(adapters, "get") else None
        media_dir = str(getattr(getattr(adapter, "config", None), "media_dir", "") or "").strip()
        if not media_dir:
            return {"eligible_files": 0, "removed_files": 0}
        root = Path(media_dir).expanduser().resolve()
        return self._cleanup_owned_directory(root, dry_run)

    def _cleanup_outbound(self, dry_run: bool) -> dict[str, int]:
        if not self._ctx:
            return {"eligible_files": 0, "removed_files": 0}
        return self._cleanup_owned_directory(
            (self._ctx.data_dir / "outbound").resolve(),
            dry_run,
        )

    def _cleanup_owned_directory(self, root: Path, dry_run: bool) -> dict[str, int]:
        if not root.is_dir():
            return {"eligible_files": 0, "removed_files": 0}
        cutoff = time.time() - self._retention_days * 24 * 60 * 60
        eligible = 0
        removed = 0
        for path in root.rglob("*"):
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
                if not path.is_file() or path.is_symlink() or path.stat().st_mtime >= cutoff:
                    continue
                eligible += 1
                if not dry_run:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        if not dry_run:
            directories = sorted(
                (path for path in root.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            )
            for directory in directories:
                try:
                    directory.rmdir()
                except OSError:
                    continue
        return {"eligible_files": eligible, "removed_files": removed}

    async def _stop_thread(self, message: Message, thread_id: str) -> None:
        turn_id = self._active_turn_id(thread_id)
        if not turn_id:
            await self._send(message, "当前任务没有可停止的运行步骤。")
            return
        try:
            await self._request(
                "POST",
                f"/api/threads/{thread_id}/interrupt",
                payload={"turnId": turn_id},
            )
        except AcodeApiError as exc:
            if exc.status == 409:
                await self._send(message, "当前任务没有可停止的运行步骤。")
            else:
                await self._send(message, f"停止任务失败：{self._safe_error(exc)}")
            return
        except Exception as exc:
            await self._send(message, f"停止任务失败：{self._safe_error(exc)}")
            return
        await self._send(message, "停止请求已发送。")

    async def _list_threads(self, *, limit: int) -> list[dict[str, Any]]:
        payload = await self._request("GET", f"/api/threads?limit={max(1, min(limit, 100))}")
        items = payload.get("data") if isinstance(payload, dict) else []
        threads = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        return sorted(
            threads,
            key=lambda item: (
                str(item.get("status") or "") not in {"running", "starting", "waiting-approval"},
                -self._timestamp_number(item.get("updatedAtMs")),
            ),
        )

    async def _thread_status(self, thread_id: str) -> str:
        payload = await self._request("GET", f"/sessions/{thread_id}")
        session = payload.get("session") if isinstance(payload, dict) else None
        return str(session.get("status") or "completed") if isinstance(session, dict) else "completed"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        token = await self._ensure_auth()
        session = await self._http_session()
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        async with session.request(
            method,
            f"{self._base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        ) as response:
            data = await self._response_json(response)
            if response.status == 401 and retry_auth:
                self._session_token = ""
                self._session_expires_at = 0.0
                return await self._request(method, path, payload=payload, retry_auth=False)
            if response.status >= 400:
                raise self._api_error(response.status, data)
            return data

    async def _ensure_auth(self) -> str:
        if self._session_token and self._session_expires_at > asyncio.get_running_loop().time() + 30:
            return self._session_token
        async with self._auth_lock:
            if self._session_token and self._session_expires_at > asyncio.get_running_loop().time() + 30:
                return self._session_token
            if not self._is_configured():
                raise RuntimeError(self._configuration_error())
            session = await self._http_session()
            timeout = aiohttp.ClientTimeout(total=self._request_timeout)
            async with session.post(
                f"{self._base_url}/api/auth/login",
                json={"token": self._admin_token},
                timeout=timeout,
            ) as response:
                data = await self._response_json(response)
                if response.status >= 400:
                    raise AcodeApiError(response.status, "aCode 认证失败")
                token = str(data.get("token") or "") if isinstance(data, dict) else ""
                if not token:
                    raise RuntimeError("aCode 认证响应缺少会话令牌")
                self._session_token = token
                self._session_expires_at = asyncio.get_running_loop().time() + 11 * 60 * 60
                return token

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @staticmethod
    async def _response_json(response: aiohttp.ClientResponse) -> Any:
        try:
            return await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return {}

    @staticmethod
    def _api_error(status: int, data: Any) -> AcodeApiError:
        record = data if isinstance(data, dict) else {}
        code = str(record.get("error") or "")
        message = str(record.get("message") or code or f"HTTP {status}")
        return AcodeApiError(status, message, code=code)

    async def _set_selection(self, user_id: str, value: str) -> None:
        async with self._state_lock:
            self._selections[str(user_id)] = value
            if self._ctx:
                await asyncio.to_thread(
                    self._write_state,
                    self._ctx.data_dir / "selections.json",
                    self._selections,
                )

    def _selected_thread(self, user_id: str) -> str | None:
        value = self._selections.get(str(user_id), "agent")
        return None if value == "agent" else value

    async def _send(
        self,
        message: Message,
        content: str,
        *,
        keyboard: list[list[dict[str, str]]] | None = None,
        edit: bool = False,
        markdown: bool = False,
    ) -> Any:
        if not self._ctx or not self._ctx.send_reply:
            return None
        return await self._ctx.send_reply(
            self._reply(message, content, keyboard=keyboard, edit=edit, markdown=markdown)
        )

    async def _send_chat_action(self, conversation_id: str, action: str) -> None:
        adapters = self._ctx.adapters if self._ctx else None
        adapter = adapters.get("telegram") if adapters and hasattr(adapters, "get") else None
        sender = getattr(adapter, "send_chat_action", None)
        if not callable(sender):
            return
        try:
            await sender(conversation_id, action)
        except Exception as exc:
            logger.debug("[acode_remote] Telegram chat action 发送失败: {}", type(exc).__name__)

    async def _send_typing(self, conversation_id: str) -> None:
        await self._send_chat_action(conversation_id, "typing")

    async def _typing_heartbeat(self, run_key: str) -> None:
        while run_key in self._runs:
            await asyncio.sleep(4.0)
            run = self._runs.get(run_key, {})
            targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
            await asyncio.gather(
                *(self._send_typing(conversation_id) for conversation_id in targets),
            )

    async def _send_to_conversation(
        self,
        conversation_id: str,
        content: str,
        *,
        keyboard: list[list[dict[str, str]]] | None = None,
        edit_message_id: str = "",
        markdown: bool = True,
    ) -> Any:
        if not self._ctx or not self._ctx.send_reply:
            return None
        metadata: dict[str, Any] = {}
        if keyboard is not None:
            metadata["inline_keyboard"] = keyboard
        if edit_message_id:
            metadata["edit_message_id"] = edit_message_id
        if markdown:
            metadata["parse_mode"] = "Markdown"
        return await self._ctx.send_reply(Reply(
            platform="telegram",
            adapter="telegram",
            conversation_id=conversation_id,
            type="keyboard" if keyboard else ("markdown" if markdown else "text"),
            content=content,
            metadata=metadata,
        ))

    async def _update_live_message(self, run_key: str, content: str) -> None:
        run = self._runs.get(run_key, {})
        targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
        thread_id = str(run.get("thread_id") or "")
        for conversation_id, message_id in dict(targets).items():
            if not message_id:
                continue
            try:
                await self._send_to_conversation(
                    conversation_id,
                    content,
                    keyboard=[[{"text": "⏹ 停止", "callback_data": "acode:stop"}]],
                    edit_message_id=message_id,
                )
            except Exception as exc:
                logger.warning(
                    "[acode_remote] 更新实时进度失败: thread={} error={}",
                    thread_id,
                    self._safe_error(exc),
                )
                await self._set_progress_message(run_key, conversation_id, "")

    async def _finish_live_message(
        self,
        run_key: str,
        conversation_id: str,
        content: str,
    ) -> None:
        run = self._runs.get(run_key, {})
        targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
        thread_id = str(run.get("thread_id") or "")
        chunks = self._split_telegram_text(content)
        message_id = str(targets.get(conversation_id) or "")
        try:
            await self._send_to_conversation(
                conversation_id,
                chunks[0],
                keyboard=[],
                edit_message_id=message_id,
            )
        except Exception as exc:
            if not message_id:
                raise
            logger.warning(
                "[acode_remote] 完成消息编辑失败，改为新消息发送: thread={} error={}",
                thread_id,
                self._safe_error(exc),
            )
            await self._send_to_conversation(conversation_id, chunks[0])
        for chunk in chunks[1:]:
            await self._send_to_conversation(conversation_id, chunk)

    @staticmethod
    def _reply(
        message: Message,
        content: str,
        *,
        keyboard: list[list[dict[str, str]]] | None = None,
        edit: bool = False,
        markdown: bool = False,
    ) -> Reply:
        metadata: dict[str, Any] = {}
        if keyboard:
            metadata["inline_keyboard"] = keyboard
        if markdown:
            metadata["parse_mode"] = "Markdown"
        if edit and message.type == "event":
            telegram_message_id = message.raw.get("telegram_message_id")
            if telegram_message_id:
                metadata["edit_message_id"] = str(telegram_message_id)
        return Reply(
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            type="keyboard" if keyboard else "text",
            content=content,
            metadata=metadata,
            quote_message_id=message.id if message.type != "event" else None,
        )

    def _status_reply(self, message: Message) -> Reply:
        thread_id = self._selected_thread(message.sender_id)
        if not thread_id:
            return self._reply(message, f"当前聊天对象：{self._agent_label}｜现有 Agent")
        title = self._thread_titles.get(thread_id, thread_id[:8])
        return self._reply(
            message,
            f"当前聊天对象：Codex｜{title}",
            keyboard=[[{"text": "📋 切换聊天对象", "callback_data": "acode:menu"}]],
        )

    def _is_admin(self, sender_id: str) -> bool:
        return str(sender_id) in self._allowed_user_ids

    def _is_configured(self) -> bool:
        if not self._enabled or len(self._admin_token) < 16:
            return False
        parsed = urlparse(self._base_url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )

    def _configuration_error(self) -> str:
        return "aCode 远程插件尚未配置，请编辑 plugins/acode_remote/config.toml。"

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc).strip() or type(exc).__name__
        if self._admin_token:
            text = text.replace(self._admin_token, "[已隐藏]")
        if self._session_token:
            text = text.replace(self._session_token, "[已隐藏]")
        if "already has an active writer" in text.lower():
            return "该任务正在被电脑端 Codex 使用，不能同时接管；请先释放该任务或选择其他任务。"
        return text[:300]

    @staticmethod
    def _is_active_writer_error(exc: Exception) -> bool:
        return "already has an active writer" in str(exc).lower()

    def _active_turn_id(self, thread_id: str) -> str:
        candidates = [
            run
            for run in self._runs.values()
            if isinstance(run, dict)
            and str(run.get("thread_id") or "") == thread_id
            and str(run.get("turn_id") or "")
        ]
        if not candidates:
            return ""
        latest = max(candidates, key=lambda run: self._timestamp_number(run.get("started_at")))
        return str(latest.get("turn_id") or "")

    @staticmethod
    def _message_attachments(message: Message) -> list[dict[str, Any]]:
        value = message.raw.get("attachments") if isinstance(message.raw, dict) else None
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _encode_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(attachments) > 8:
            raise AttachmentError("一次最多发送 8 个附件。")
        encoded: list[dict[str, Any]] = []
        max_bytes = 15 * 1024 * 1024
        for attachment in attachments:
            if str(attachment.get("source") or "") != "telegram":
                raise AttachmentError("附件来源无效，请直接在 Telegram 重新发送。")
            if attachment.get("download_error"):
                raise AttachmentError("附件下载失败，请重新发送或换一个更小的文件。")
            raw_path = str(attachment.get("local_path") or "").strip()
            path = Path(raw_path)
            if not raw_path or not path.is_file():
                raise AttachmentError("附件尚未下载完成，请稍后重新发送。")
            size = path.stat().st_size
            if size > max_bytes:
                raise AttachmentError(f"附件 {path.name} 超过 15 MB，无法发送给 Codex。")
            name = path.name
            mime_type = str(attachment.get("mime_type") or "").strip()
            if not mime_type:
                mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            encoded.append({
                "name": name,
                "mimeType": mime_type,
                "size": size,
                "dataBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
            })
        return encoded

    async def _register_run(
        self,
        *,
        thread_id: str,
        turn_id: str,
        title: str,
        started_at: float,
        conversation_id: str,
        prefer_existing: bool,
    ) -> str:
        async with self._run_lock:
            run_key = self._matching_run_key(thread_id, turn_id) if prefer_existing else ""
            if not run_key:
                suffix = turn_id or secrets.token_hex(12)
                run_key = f"{thread_id}:{suffix}"
            run = self._runs.get(run_key)
            if not isinstance(run, dict):
                run = {
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "title": title,
                    "started_at": started_at,
                    "targets": {},
                    "delivered_to": [],
                    "timeout_notified_to": [],
                }
                self._runs[run_key] = run
            elif turn_id and not str(run.get("turn_id") or ""):
                run["turn_id"] = turn_id
            targets = run.setdefault("targets", {})
            if not isinstance(targets, dict):
                targets = {}
                run["targets"] = targets
            targets.setdefault(conversation_id, "")
            await self._persist_runs_locked()
            return run_key

    def _matching_run_key(self, thread_id: str, turn_id: str) -> str:
        candidates: list[tuple[float, str]] = []
        for run_key, run in self._runs.items():
            if str(run.get("thread_id") or "") != thread_id:
                continue
            stored_turn_id = str(run.get("turn_id") or "")
            if turn_id and stored_turn_id and stored_turn_id != turn_id:
                continue
            candidates.append((self._timestamp_number(run.get("started_at")), run_key))
        return max(candidates, default=(0.0, ""))[1]

    async def _set_progress_message(
        self,
        run_key: str,
        conversation_id: str,
        message_id: str,
    ) -> None:
        async with self._run_lock:
            run = self._runs.get(run_key)
            if not isinstance(run, dict):
                return
            targets = run.get("targets")
            if not isinstance(targets, dict):
                targets = {}
                run["targets"] = targets
            targets[conversation_id] = message_id
            await self._persist_runs_locked()

    async def _mark_delivered(self, run_key: str, conversation_id: str) -> None:
        async with self._run_lock:
            run = self._runs.get(run_key)
            if not isinstance(run, dict):
                return
            delivered = {str(item) for item in run.get("delivered_to", [])}
            delivered.add(conversation_id)
            run["delivered_to"] = sorted(delivered)
            targets = run.get("targets") if isinstance(run.get("targets"), dict) else {}
            if targets and set(targets).issubset(delivered):
                self._runs.pop(run_key, None)
            await self._persist_runs_locked()

    async def _mark_timeout_notified(
        self, run_key: str, conversation_id: str
    ) -> None:
        async with self._run_lock:
            run = self._runs.get(run_key)
            if not isinstance(run, dict):
                return
            notified = {str(item) for item in run.get("timeout_notified_to", [])}
            notified.add(conversation_id)
            run["timeout_notified_to"] = sorted(notified)
            await self._persist_runs_locked()

    async def _persist_runs_locked(self) -> None:
        if not self._ctx:
            return
        snapshot = json.loads(json.dumps(self._runs, ensure_ascii=False))
        await asyncio.to_thread(
            self._write_json,
            self._ctx.data_dir / "pending_turns.json",
            snapshot,
        )

    def _start_watcher(self, run_key: str) -> None:
        if run_key in self._watchers or run_key not in self._runs:
            return
        run = self._runs[run_key]
        thread_id = str(run.get("thread_id") or "")
        turn_id = str(run.get("turn_id") or "")
        watcher = asyncio.create_task(
            self._watch_run(run_key),
            name=f"acode-watch-{thread_id[:8]}-{turn_id[:8] or 'pending'}",
        )
        self._watchers[run_key] = watcher
        self._track(watcher)

        def clear(done: asyncio.Task[Any]) -> None:
            if self._watchers.get(run_key) is done:
                self._watchers.pop(run_key, None)

        watcher.add_done_callback(clear)

    def _schedule(self, awaitable, *, name: str) -> None:
        self._track(asyncio.create_task(awaitable, name=name))

    def _schedule_service(self, awaitable, *, name: str) -> None:
        task = asyncio.create_task(awaitable, name=name)
        self._service_tasks.add(task)
        task.add_done_callback(self._service_finished)

    def _service_finished(self, task: asyncio.Task[Any]) -> None:
        self._service_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "[acode_remote] 后台服务失败: task={} error={}",
                task.get_name(),
                self._safe_error(error),
            )

    def _track(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._task_finished)

    def _task_finished(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("[acode_remote] 后台任务失败: task={} error={}", task.get_name(), self._safe_error(error))

    @staticmethod
    def _plugin_config(value: dict[str, Any] | None) -> dict[str, Any]:
        config = value if isinstance(value, dict) else {}
        nested = config.get("acode_remote")
        return nested if isinstance(nested, dict) else config

    @staticmethod
    def _command(content: str) -> str:
        first = content.split(maxsplit=1)[0].lower() if content else ""
        return first.split("@", 1)[0]

    @classmethod
    def _is_explicit_command(cls, content: str) -> bool:
        return cls._command(content) in {
            "/start", "/chat", "/codex", "/tasks", "/help", "/agent", "/status", "/stop",
            "/doctor", "/find", "/search", "/new", "/rename", "/archive", "/archived",
        }

    @staticmethod
    def _attachment_action(attachments: list[dict[str, Any]] | None) -> str:
        kinds = {
            str(item.get("type") or "file")
            for item in (attachments or [])
            if isinstance(item, dict)
        }
        if kinds == {"image"}:
            return "upload_photo"
        if kinds == {"video"}:
            return "upload_video"
        if kinds == {"voice"}:
            return "upload_voice"
        return "upload_document"

    @staticmethod
    def _thread_title(thread: dict[str, Any]) -> str:
        title = str(thread.get("title") or thread.get("preview") or "未命名任务").strip()
        if "## My request:" in title:
            title = title.rsplit("## My request:", 1)[-1]
        lines = [line.strip(" #-\t") for line in title.splitlines()]
        ignored = ("files mentioned by the user", "my request", "in-app-browser-context")
        useful = [
            line for line in lines
            if line
            and not any(marker in line.casefold() for marker in ignored)
            and not re.fullmatch(r"\[?https?://\S+", line, flags=re.IGNORECASE)
        ]
        value = useful[0] if useful else " ".join(title.split())
        value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
        value = " ".join(value.split())
        return value[:32] or "未命名任务"

    def _menu_pages(self, threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        projects: dict[str, dict[str, Any]] = {}
        for thread in threads:
            cwd = str(thread.get("cwd") or "").strip()
            path = cwd.removeprefix("\\\\?\\").rstrip("\\/") or "未标记项目"
            parts = [part for part in re.split(r"[\\/]+", path) if part]
            project = parts[-1] if parts else "未标记项目"
            key = path.casefold()
            group = projects.setdefault(key, {"project": project, "path": path, "threads": []})
            group["threads"].append(thread)
        pages: list[dict[str, Any]] = []
        for group in projects.values():
            project_threads = group["threads"]
            pages.extend(
                {
                    "project": group["project"],
                    "path": self._short_path(group["path"]),
                    "threads": project_threads[start:start + self._page_size],
                }
                for start in range(0, len(project_threads), self._page_size)
            )
        return pages

    @staticmethod
    def _short_path(path: str) -> str:
        if len(path) <= 46:
            return path
        parts = [part for part in re.split(r"[\\/]+", path) if part]
        return "…\\" + "\\".join(parts[-2:]) if len(parts) >= 2 else "…" + path[-43:]

    @staticmethod
    def _md_escape(value: str) -> str:
        return re.sub(r"([_*\[`])", r"\\\1", str(value))

    @staticmethod
    def _status_icon(status: str) -> str:
        if status in {"running", "starting"}:
            return "🟢"
        if status == "waiting-approval":
            return "🟡"
        if status in {"failed", "cancelled"}:
            return "🔴"
        return "⚪"

    @staticmethod
    def _timestamp_number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _event_is_current(event: dict[str, Any], started_at: float) -> bool:
        timestamp = str(event.get("timestamp") or "")
        if not timestamp:
            return True
        try:
            return datetime.fromisoformat(timestamp).timestamp() >= started_at - 2
        except ValueError:
            return True

    @staticmethod
    def _sent_message_id(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        message_id = str(payload.get("message_id") or "").strip()
        if message_id:
            return message_id
        message_ids = payload.get("message_ids")
        if isinstance(message_ids, list) and message_ids:
            return str(message_ids[-1] or "").strip()
        return ""

    @staticmethod
    def _turn_id(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        direct = str(payload.get("turnId") or payload.get("turn_id") or "").strip()
        if direct:
            return direct
        turn = payload.get("turn")
        return str(turn.get("id") or "").strip() if isinstance(turn, dict) else ""

    @classmethod
    def _event_matches_turn(cls, event: dict[str, Any], turn_id: str) -> bool:
        if not turn_id:
            return True
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        json_payload = payload.get("jsonPayload") if isinstance(payload.get("jsonPayload"), dict) else {}
        found: list[str] = []
        for record in (event, payload, json_payload):
            direct = str(record.get("turnId") or record.get("turn_id") or "").strip()
            if direct:
                found.append(direct)
            turn = record.get("turn")
            if isinstance(turn, dict) and str(turn.get("id") or "").strip():
                found.append(str(turn["id"]).strip())
        if found:
            return turn_id in found
        return str(event.get("type") or "") != "session-finished"

    @staticmethod
    def _event_item_id(payload: dict[str, Any]) -> str:
        json_payload = payload.get("jsonPayload")
        return str(json_payload.get("itemId") or "").strip() if isinstance(json_payload, dict) else ""

    @staticmethod
    def _completed_item_id(payload: dict[str, Any]) -> str:
        json_payload = payload.get("jsonPayload")
        item = json_payload.get("item") if isinstance(json_payload, dict) else None
        return str(item.get("id") or "").strip() if isinstance(item, dict) else ""

    def _update_tool_steps(
        self,
        payload: dict[str, Any],
        tool_steps: list[str],
        running_tools: dict[str, int],
    ) -> bool:
        event_type = str(payload.get("eventType") or "")
        if not event_type.startswith("item/"):
            return False
        json_payload = payload.get("jsonPayload")
        json_payload = json_payload if isinstance(json_payload, dict) else {}
        item = json_payload.get("item") if isinstance(json_payload.get("item"), dict) else {}
        kind = str(item.get("type") or "")
        if not kind:
            parts = event_type.split("/")
            kind = parts[1] if len(parts) > 2 else ""
        tool_name = self._tool_display_name(kind, item)
        if not tool_name:
            return False
        item_id = str(item.get("id") or json_payload.get("itemId") or kind).strip()
        key = f"{kind}:{item_id}"
        completed = event_type == "item/completed"
        if completed:
            failed = str(item.get("status") or "").lower() in {"failed", "error"}
            if kind == "commandExecution":
                exit_code = item.get("exitCode")
                failed = failed or (exit_code is not None and str(exit_code).strip() != "0")
            text = f"⚠️ {tool_name}" if failed else f"✅ {tool_name}"
        else:
            text = f"⏳ {tool_name}"
        tool_steps[:] = [text]
        running_tools.clear()
        running_tools[key] = 0
        if completed:
            running_tools.clear()
        return True

    @staticmethod
    def _tool_display_name(kind: str, item: dict[str, Any]) -> str:
        fixed = {
            "commandExecution": "shell_command",
            "fileChange": "apply_patch",
            "webSearch": "web_search",
        }
        if kind in fixed:
            return fixed[kind]
        if kind != "mcpToolCall":
            return ""
        for key in ("tool", "toolName", "name"):
            value = item.get(key)
            if isinstance(value, str):
                safe = re.sub(r"[^a-zA-Z0-9_.:-]", "", value)[:64]
                if safe:
                    return safe
        return "mcp_tool"

    @staticmethod
    def _live_progress(partial: str, tool_steps: list[str]) -> str:
        sections = ["*🟢 Codex 正在处理*", "──────────"]
        if tool_steps:
            sections.append(tool_steps[-1])
        prefix = "\n\n".join(sections) + "\n\n"
        body = partial.strip() or "💭 *正在思考…*"
        available = max(1, 3900 - len(prefix))
        if len(body) > available:
            body = "…" + body[-(available - 1):]
        return prefix + body

    @staticmethod
    def _split_telegram_text(content: str, limit: int = 3900) -> list[str]:
        return split_markdown(
            content.strip() or "任务已完成，没有返回文字内容。",
            limit,
        )

    @staticmethod
    def _completed_agent_text(payload: dict[str, Any]) -> str:
        json_payload = payload.get("jsonPayload")
        item = json_payload.get("item") if isinstance(json_payload, dict) else None
        if not isinstance(item, dict) or item.get("type") != "agentMessage":
            return ""
        return str(item.get("text") or "").strip()

    @staticmethod
    def _finished_agent_text(payload: dict[str, Any]) -> str:
        turn = payload.get("turn")
        items = turn.get("items") if isinstance(turn, dict) else None
        if not isinstance(items, list):
            return ""
        for item in reversed(items):
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = str(item.get("text") or "").strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _finished_status(payload: dict[str, Any]) -> str:
        turn = payload.get("turn")
        status = str(turn.get("status") or "") if isinstance(turn, dict) else ""
        if status in {"cancelled", "interrupted"}:
            return "cancelled"
        if status in {"failed", "error"}:
            return "failed"
        return "completed"

    @staticmethod
    def _read_state(path: Path) -> dict[str, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if str(key).strip() and str(value).strip()
        }

    @staticmethod
    def _read_favorites(path: Path) -> dict[str, list[str]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(user_id): sorted({
                str(thread_id)
                for thread_id in thread_ids
                if str(thread_id).strip()
            })
            for user_id, thread_ids in payload.items()
            if str(user_id).strip() and isinstance(thread_ids, list)
        }

    @staticmethod
    def _read_runs(path: Path) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        runs: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if not str(key).strip() or not isinstance(value, dict):
                continue
            thread_id = str(value.get("thread_id") or "").strip()
            targets = value.get("targets")
            if not thread_id or not isinstance(targets, dict) or not targets:
                continue
            clean_targets = {
                str(conversation_id): str(message_id or "")
                for conversation_id, message_id in targets.items()
                if str(conversation_id).strip()
            }
            if not clean_targets:
                continue
            delivered_to = [
                str(item)
                for item in value.get("delivered_to", [])
                if str(item).strip()
            ]
            timeout_notified_to = [
                str(item)
                for item in value.get("timeout_notified_to", [])
                if str(item).strip() and str(item) in clean_targets
            ]
            if set(clean_targets).issubset(set(delivered_to)):
                continue
            runs[str(key)] = {
                "thread_id": thread_id,
                "turn_id": str(value.get("turn_id") or "").strip(),
                "title": str(value.get("title") or thread_id[:8]),
                "started_at": AcodeRemotePlugin._timestamp_number(value.get("started_at")),
                "targets": clean_targets,
                "delivered_to": delivered_to,
                "timeout_notified_to": timeout_notified_to,
            }
        return runs

    @staticmethod
    def _write_state(path: Path, state: dict[str, str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _harden_config_permissions(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            return

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            return max(minimum, min(maximum, float(value)))
        except (TypeError, ValueError):
            return default
