from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xbot.core.config import (
    Settings,
    load_runtime_overrides,
    load_settings,
    runtime_config_path,
)
from xbot.core.logging import configure_logging
from xbot.runtime.context import AppContext, build_context
from xbot.storage.bootstrap import ensure_storage_ready

KEEP_SECRET = "__XBOT_KEEP_SECRET__"


class ConfigConflictError(RuntimeError):
    pass


class ConfigApplyError(RuntimeError):
    pass


SECTION_META: dict[str, tuple[str, str, str]] = {
    "xbot": ("基础信息", "机器人名称、时区与调试行为。", "system"),
    "server": ("服务监听", "HTTP 监听地址与端口，保存后需重启服务。", "system"),
    "api": ("控制台安全", "API 鉴权、访问 Token 与跨域来源。", "system"),
    "storage": ("数据库", "业务数据连接、连接池与迁移策略。", "system"),
    "queue": ("消息队列", "消息、回复、事件和失败队列。", "system"),
    "conversation": ("会话", "上下文窗口、摘要与并发隔离。", "system"),
    "runtime": ("运行时", "任务并发量与超时边界。", "system"),
    "plugins": ("插件", "插件目录与自动加载策略。", "system"),
    "skills": ("Skills", "Skill 目录与自动加载策略。", "system"),
    "agent": ("Agent 与模型", "Hermes、模型、工具审批、MCP 与成员权限。", "system"),
    "adapters.web": ("Web 通道", "控制台内置 Web 消息通道。", "channels"),
    "adapters.wechat869": ("微信 869", "869 协议服务、登录凭据、媒体与权限名单。", "channels"),
    "adapters.wechat_ilink": ("微信 iLink", "iLink 扫码登录、轮询、媒体与账号信息。", "channels"),
    "adapters.qq": ("QQ 官方机器人", "QQ 开放平台 Gateway、OpenAPI 凭据与权限名单。", "channels"),
    "adapters.telegram": ("Telegram Bot", "Telegram Bot API 长轮询、媒体与权限名单。", "channels"),
}

RESTART_REQUIRED_PREFIXES = (
    "server.",
    "storage.",
    "queue.",
    "api.cors_origins",
)

JSON_OBJECT_PATHS = {"agent.mcp.servers"}

OPTIONS: dict[str, list[str]] = {
    "storage.type": ["postgresql", "sqlite"],
    "queue.type": ["memory", "redis"],
    "conversation.store": ["postgresql", "sqlite"],
    "conversation.default_scope": ["private", "group", "channel", "agent_task", "system"],
    "queue.retry.backoff": ["fixed", "exponential"],
    "agent.mode": ["safe", "developer", "admin"],
    "agent.llm.provider": ["openai_compatible", "anthropic"],
    "adapters.wechat869.default_profile": ["member", "guest"],
    "adapters.qq.default_profile": ["member", "guest"],
    "adapters.telegram.default_profile": ["member", "guest"],
}

FULL_LABELS: dict[str, str] = {
    "xbot.name": "机器人名称",
    "xbot.timezone": "时区",
    "xbot.debug": "调试日志",
    "server.host": "监听地址",
    "server.port": "监听端口",
    "api.auth_enabled": "启用控制台鉴权",
    "api.token": "控制台 API Token",
    "api.cors_origins": "允许的跨域来源",
    "storage.type": "存储类型",
    "storage.url": "数据库连接串",
    "storage.admin_url": "数据库管理员连接串",
    "queue.type": "队列类型",
    "queue.redis_url": "Redis 连接串",
    "agent.enabled": "启用 Agent",
    "agent.llm.enabled": "启用模型",
    "agent.llm.provider": "模型协议",
    "agent.llm.base_url": "模型 API 地址",
    "agent.llm.api_key": "模型 API Key",
    "agent.llm.model": "模型名称",
    "agent.llm.enabled_models": "已启用模型",
    "agent.member_policy.workspace_roots": "成员工作区目录",
    "adapters.qq.enabled": "启用 QQ 通道",
    "adapters.qq.app_id": "QQ AppID",
    "adapters.qq.client_secret": "QQ AppSecret",
    "adapters.qq.intents": "Gateway Intents",
    "adapters.qq.api_base_url": "QQ OpenAPI 地址",
    "adapters.qq.token_url": "Access Token 地址",
    "adapters.qq.gateway_url": "固定 Gateway 地址",
    "adapters.qq.max_reply_chars": "单条回复长度",
    "adapters.qq.allow_active_messages": "允许 QQ 主动消息",
    "adapters.qq.media_enabled": "启用 QQ 媒体",
    "adapters.qq.media_dir": "QQ 媒体宿主机目录",
    "adapters.qq.auto_download_media": "自动下载 QQ 入站媒体",
    "adapters.qq.media_max_bytes": "QQ 媒体硬限制",
    "adapters.qq.media_image_max_bytes": "QQ 图片软限制",
    "adapters.qq.media_voice_max_bytes": "QQ 语音软限制",
    "adapters.qq.media_video_max_bytes": "QQ 视频软限制",
    "adapters.qq.media_file_max_bytes": "QQ 文件限制",
    "adapters.qq.media_chunk_size": "QQ 媒体分片大小",
    "adapters.qq.media_allowed_roots": "QQ 工具允许媒体根",
    "adapters.qq.channel_enabled": "启用 QQ 频道",
    "adapters.qq.admin_openids": "管理员 OpenID",
    "adapters.qq.member_openids": "成员 OpenID",
    "adapters.qq.default_profile": "默认权限",
    "adapters.wechat869.admin_wxids": "管理员 wxid",
    "adapters.wechat869.member_wxids": "成员 wxid",
    "adapters.wechat869.default_profile": "默认权限",
    "adapters.telegram.enabled": "启用 Telegram 通道",
    "adapters.telegram.bot_token": "Telegram Bot Token",
    "adapters.telegram.api_base_url": "Telegram Bot API 地址",
    "adapters.telegram.polling_timeout_seconds": "长轮询等待（秒）",
    "adapters.telegram.connect_timeout_seconds": "请求超时（秒）",
    "adapters.telegram.reconnect_seconds": "重连间隔（秒）",
    "adapters.telegram.max_reply_chars": "单条回复长度",
    "adapters.telegram.media_enabled": "启用 Telegram 媒体",
    "adapters.telegram.media_dir": "Telegram 媒体宿主机目录",
    "adapters.telegram.auto_download_media": "自动下载 Telegram 入站媒体",
    "adapters.telegram.media_max_bytes": "Telegram 媒体大小上限",
    "adapters.telegram.admin_user_ids": "管理员 User ID",
    "adapters.telegram.member_user_ids": "成员 User ID",
    "adapters.telegram.default_profile": "默认权限",
}

LEAF_LABELS: dict[str, str] = {
    "enabled": "启用",
    "auto_load": "自动加载",
    "host": "主机",
    "port": "端口",
    "base_url": "服务地址",
    "cdn_base_url": "CDN 地址",
    "gateway_url": "Gateway 地址",
    "connect_timeout_seconds": "连接超时（秒）",
    "reconnect_seconds": "重连间隔（秒）",
    "timeout_seconds": "请求超时（秒）",
    "max_attempts": "最大尝试次数",
    "retry_backoff_seconds": "重试退避（秒）",
    "directory": "目录",
    "media_dir": "媒体目录",
    "media_enabled": "启用媒体",
    "auto_download_images": "自动下载图片",
    "auto_download_files": "自动下载文件",
    "max_image_bytes": "图片上限（字节）",
    "max_file_bytes": "文件上限（字节）",
    "workspace_root": "工作区根目录",
    "workspace_roots": "授权工作区",
    "default_profile": "默认权限",
    "servers": "MCP 服务器",
}

DESCRIPTIONS: dict[str, str] = {
    "api.token": "修改后当前浏览器也要切换到新 Token；服务端永不回传明文。",
    "storage.url": "包含数据库口令，页面只显示是否已配置。",
    "storage.admin_url": "仅首次创建数据库或角色时使用，不写入普通日志。",
    "agent.llm.api_key": "留空表示保持原值；使用“恢复来源”可删除网页覆盖。",
    "agent.llm.model": "所有未单独指定模型的会话都使用此模型。",
    "agent.llm.enabled_models": "群聊只能从这里启用的模型中选择。",
    "adapters.qq.app_id": "在 QQ 开放平台创建机器人后获得。",
    "adapters.qq.client_secret": "只在服务端保存；页面与 API 永不回传明文。",
    "adapters.qq.gateway_url": "通常留空并通过 GET /gateway 自动发现。",
    "adapters.qq.default_profile": "公网通道建议 guest；只有白名单成员才开放受限工具。",
    "adapters.qq.allow_active_messages": "默认关闭；开启后 QQ 工具才可在没有触发消息 ID 时主动发送。",
    "adapters.qq.media_dir": "必须是宿主机持久化目录，不使用容器专属临时路径。",
    "adapters.qq.intents": "仅填写网页/ENV 中已获授权的整数 intents；不要默认加入特殊 intent 以免 4014。",
    "adapters.telegram.bot_token": "从 BotFather 获取；服务端保存，页面与 API 永不回传明文。",
    "adapters.telegram.api_base_url": "默认使用 Telegram 官方 API；自建 Bot API 可在此替换。",
    "adapters.telegram.media_dir": "必须使用宿主机持久化目录，避免容器重建后媒体丢失。",
}

ENV_ALIASES: dict[str, str] = {
    "server.host": "XBOT_SERVER_HOST",
    "server.port": "XBOT_SERVER_PORT",
    "api.auth_enabled": "XBOT_API_AUTH_ENABLED",
    "api.token": "XBOT_API_TOKEN",
    "api.cors_origins": "XBOT_API_CORS_ORIGINS",
    "storage.type": "XBOT_STORAGE_TYPE",
    "storage.url": "XBOT_DATABASE_URL",
    "storage.admin_url": "XBOT_ADMIN_DATABASE_URL",
    "storage.auto_bootstrap": "XBOT_DATABASE_AUTO_BOOTSTRAP",
    "storage.run_migrations_on_startup": "XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP",
    "queue.type": "XBOT_QUEUE_TYPE",
    "queue.redis_url": "XBOT_REDIS_URL",
    "conversation.store": "XBOT_CONVERSATION_STORE",
    "agent.llm.enabled": "XBOT_LLM_ENABLED",
    "agent.llm.provider": "XBOT_LLM_PROVIDER",
    "agent.llm.base_url": "XBOT_LLM_BASE_URL",
    "agent.llm.api_key": "XBOT_LLM_API_KEY",
    "agent.llm.model": "XBOT_LLM_MODEL",
    "agent.llm.enabled_models": "XBOT_LLM_ENABLED_MODELS",
}


class ConfigService:
    def __init__(self, config_file: str | os.PathLike[str] | None = None) -> None:
        self.config_file = Path(config_file) if config_file else None

    def snapshot(self, runtime_settings: Settings) -> dict[str, Any]:
        config_file = self.config_file or runtime_settings.config_file
        overrides = load_runtime_overrides(config_file)
        persisted = load_settings(config_file, runtime_overrides=overrides)
        persisted_data = persisted.model_dump(mode="json", exclude={"config_file"})
        runtime_data = runtime_settings.model_dump(mode="json", exclude={"config_file"})
        sections: list[dict[str, Any]] = []
        fields_by_section: dict[str, list[dict[str, Any]]] = {}
        for path, value in self._flatten(persisted_data):
            section_key = self._section_for_path(path)
            if not section_key:
                continue
            secret = self._is_secret(path)
            runtime_value = self._get_path(runtime_data, path)
            field = {
                "path": path,
                "key": path.rsplit(".", 1)[-1],
                "label": self._label(path),
                "description": DESCRIPTIONS.get(path, ""),
                "type": self._field_type(value),
                "value": None if secret else value,
                "configured": self._configured(value),
                "masked_value": self._masked_value(value) if secret else "",
                "secret": secret,
                "source": "web" if self._has_path(overrides, path) else "env_or_file",
                "overridden": self._has_path(overrides, path),
                "env_name": self._env_name(path),
                "options": OPTIONS.get(path, []),
                "restart_required": self._restart_required(path),
                "pending_restart": self._restart_required(path) and value != runtime_value,
                "adapter_toggle": path.startswith("adapters.") and path.endswith(".enabled"),
            }
            fields_by_section.setdefault(section_key, []).append(field)
        for key, (title, description, scope) in SECTION_META.items():
            fields = fields_by_section.get(key, [])
            if not fields:
                continue
            sections.append(
                {
                    "key": key,
                    "title": title,
                    "description": description,
                    "scope": scope,
                    "fields": fields,
                }
            )
        pending = [
            field["path"]
            for section in sections
            for field in section["fields"]
            if field["pending_restart"]
        ]
        return {
            "revision": self._revision(overrides, config_file),
            "runtime_file": str(runtime_config_path(config_file)),
            "sections": sections,
            "pending_restart": pending,
            "updated_at": self._runtime_file_mtime(config_file),
        }

    async def apply(
        self,
        app,
        *,
        changes: list[dict[str, Any]],
        revision: str | None,
    ) -> dict[str, Any]:
        lock = getattr(app.state, "config_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            app.state.config_lock = lock
        async with lock:
            runtime_context: AppContext = app.state.context
            config_file = self.config_file or runtime_context.settings.config_file
            previous_overrides = load_runtime_overrides(config_file)
            current_revision = self._revision(previous_overrides, config_file)
            if revision and revision != current_revision:
                raise ConfigConflictError("配置已被其他页面更新，请刷新后重试")
            allowed_paths = {
                path
                for path, _ in self._flatten(
                    load_settings(config_file, runtime_overrides=previous_overrides).model_dump(
                        mode="json", exclude={"config_file"}
                    )
                )
            }
            next_overrides = deepcopy(previous_overrides)
            changed_paths: list[str] = []
            for change in changes:
                path = str(change.get("path") or "").strip()
                if path not in allowed_paths:
                    raise ValueError(f"不支持的配置路径: {path}")
                if path.startswith("adapters.") and path.endswith(".enabled"):
                    raise ValueError("通道启停请使用通道卡片上的实时开关")
                if bool(change.get("reset")):
                    self._delete_path(next_overrides, path)
                else:
                    value = change.get("value")
                    if value == KEEP_SECRET:
                        continue
                    self._set_path(next_overrides, path, value)
                changed_paths.append(path)
            if not changed_paths:
                return {
                    "applied": [],
                    "restart_required": [],
                    "snapshot": self.snapshot(runtime_context.settings),
                }
            candidate = load_settings(config_file, runtime_overrides=next_overrides)
            self._validate_security(candidate)
            restart_required = sorted(
                {path for path in changed_paths if self._restart_required(path)}
            )
            live_paths = sorted(set(changed_paths) - set(restart_required))
            live_candidate = candidate.model_copy(deep=True)
            for path, _ in self._flatten(
                candidate.model_dump(mode="json", exclude={"config_file"})
            ):
                if self._restart_required(path):
                    self._set_model_path(
                        live_candidate,
                        path,
                        self._get_model_path(runtime_context.settings, path),
                    )
            if live_paths:
                await ensure_storage_ready(live_candidate)
            self._write_overrides(config_file, next_overrides)
            if live_paths:
                try:
                    await self._replace_context(app, runtime_context, live_candidate)
                except Exception as exc:
                    self._write_overrides(config_file, previous_overrides)
                    raise ConfigApplyError(f"运行时应用失败，已回滚配置: {exc}") from exc
            active_context: AppContext = app.state.context
            return {
                "applied": live_paths,
                "restart_required": restart_required,
                "snapshot": self.snapshot(active_context.settings),
            }

    async def _replace_context(
        self,
        app,
        old_context: AppContext,
        settings: Settings,
    ) -> None:
        rollback_settings = old_context.settings.model_copy(deep=True)
        new_context = build_context(settings)
        stopped_old = False
        try:
            await old_context.engine.stop()
            stopped_old = True
            await new_context.engine.start()
            configure_logging(bool(settings.xbot.debug))
            app.state.context = new_context
            await old_context.storage.close()
        except Exception:
            with contextlib.suppress(Exception):
                configure_logging(bool(rollback_settings.xbot.debug))
            with contextlib.suppress(Exception):
                await new_context.engine.stop()
            with contextlib.suppress(Exception):
                await new_context.storage.close()
            if stopped_old:
                rollback_context = build_context(rollback_settings)
                await rollback_context.engine.start()
                app.state.context = rollback_context
                with contextlib.suppress(Exception):
                    await old_context.storage.close()
            raise

    def _validate_security(self, settings: Settings) -> None:
        if settings.api.auth_enabled and not settings.api.token.strip():
            raise ValueError("启用控制台鉴权前必须配置 API Token")
        if settings.adapters.qq.enabled and (
            not settings.adapters.qq.app_id.strip()
            or not settings.adapters.qq.client_secret.strip()
        ):
            raise ValueError("启用 QQ 通道前必须同时配置 AppID 与 AppSecret")
        if settings.adapters.telegram.enabled and not settings.adapters.telegram.bot_token.strip():
            raise ValueError("启用 Telegram 通道前必须配置 Bot Token")

    def _write_overrides(
        self,
        config_file: str | os.PathLike[str] | None,
        overrides: dict[str, Any],
    ) -> None:
        path = runtime_config_path(config_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        payload = json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)

    def _flatten(self, data: dict[str, Any], prefix: str = ""):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and path not in JSON_OBJECT_PATHS:
                yield from self._flatten(value, path)
            else:
                yield path, value

    def _section_for_path(self, path: str) -> str:
        if path.startswith("adapters."):
            parts = path.split(".")
            return ".".join(parts[:2]) if len(parts) >= 2 else ""
        return path.split(".", 1)[0]

    def _restart_required(self, path: str) -> bool:
        return any(path == prefix or path.startswith(prefix) for prefix in RESTART_REQUIRED_PREFIXES)

    def _is_secret(self, path: str) -> bool:
        if path in {"storage.url", "storage.admin_url", "queue.redis_url"}:
            return True
        leaf = path.rsplit(".", 1)[-1]
        if leaf in {"token", "bot_token", "api_key", "client_secret", "admin_key", "token_key"}:
            return True
        return path == "agent.mcp.servers"

    def _label(self, path: str) -> str:
        if path in FULL_LABELS:
            return FULL_LABELS[path]
        leaf = path.rsplit(".", 1)[-1]
        return LEAF_LABELS.get(leaf, leaf.replace("_", " "))

    def _env_name(self, path: str) -> str:
        if path in ENV_ALIASES:
            return ENV_ALIASES[path]
        prefixes = {
            "adapters.wechat869.": "XBOT_WECHAT869_",
            "adapters.wechat_ilink.": "XBOT_WECHAT_ILINK_",
            "adapters.qq.": "XBOT_QQ_",
            "adapters.telegram.": "XBOT_TELEGRAM_",
        }
        for prefix, env_prefix in prefixes.items():
            if path.startswith(prefix):
                return env_prefix + path.removeprefix(prefix).upper()
        return ""

    def _field_type(self, value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "json"
        return "string"

    def _configured(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (str, list, dict)):
            return bool(value)
        return True

    def _masked_value(self, value: Any) -> str:
        if not self._configured(value):
            return "未配置"
        if isinstance(value, str) and "://" in value and "@" in value:
            scheme, remainder = value.split("://", 1)
            credentials, target = remainder.rsplit("@", 1)
            username = credentials.split(":", 1)[0]
            return f"{scheme}://{username}:••••@{target}"
        return "已配置"

    def _revision(
        self,
        overrides: dict[str, Any],
        config_file: str | os.PathLike[str] | None,
    ) -> str:
        canonical = json.dumps(overrides, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        path = runtime_config_path(config_file)
        try:
            stat = path.stat()
            file_version = f"{stat.st_mtime_ns}:{stat.st_size}"
        except FileNotFoundError:
            file_version = "missing"
        payload = f"{file_version}\n{canonical}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _runtime_file_mtime(self, config_file: str | os.PathLike[str] | None) -> str | None:
        path = runtime_config_path(config_file)
        if not path.exists():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()

    def _get_path(self, data: dict[str, Any], path: str) -> Any:
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _has_path(self, data: dict[str, Any], path: str) -> bool:
        current: Any = data
        parts = path.split(".")
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return isinstance(current, dict) and parts[-1] in current

    def _set_path(self, data: dict[str, Any], path: str, value: Any) -> None:
        current = data
        parts = path.split(".")
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value

    def _delete_path(self, data: dict[str, Any], path: str) -> None:
        current = data
        parents: list[tuple[dict[str, Any], str]] = []
        parts = path.split(".")
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                return
            parents.append((current, part))
            current = child
        current.pop(parts[-1], None)
        for parent, key in reversed(parents):
            child = parent.get(key)
            if isinstance(child, dict) and not child:
                parent.pop(key, None)

    def _get_model_path(self, settings: Settings, path: str) -> Any:
        current: Any = settings
        for part in path.split("."):
            current = getattr(current, part)
        return deepcopy(current)

    def _set_model_path(self, settings: Settings, path: str, value: Any) -> None:
        current: Any = settings
        parts = path.split(".")
        for part in parts[:-1]:
            current = getattr(current, part)
        setattr(current, parts[-1], deepcopy(value))
