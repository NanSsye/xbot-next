from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio

from xbot.core.config import AgentConfig
from xbot.core.logging import logger

_HERMES_TOOL_POLICY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xbot_hermes_tool_policy",
    default=None,
)
_HERMES_AUX_RUNTIME: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xbot_hermes_aux_runtime", default=None,
)

_MEMBER_TOOLSETS = [
    "wechat",
    "qq",
    "telegram",
    "web",
    "file",
    "terminal",
    "skills",
    "todo",
    "memory",
    "session_search",
    "clarify",
    "vision",
    "artifacts",
]

_MEMBER_DENIED_TOOLS = {
    "process",
    "process_manage",
    "execute_code",
    "delegate_task",
    "cronjob",
    "cronjob_manage",
    "send_message",
    "text_to_speech",
    "computer_use",
    "ha_list_entities",
    "ha_get_state",
    "ha_list_services",
    "ha_call_service",
    "kanban_show",
    "kanban_list",
    "kanban_complete",
    "kanban_block",
    "kanban_heartbeat",
    "kanban_comment",
    "kanban_create",
    "kanban_link",
    "kanban_unblock",
}

_MEMBER_DENIED_PREFIXES = ("browser_", "kanban_")

_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}

_LAN_COMMAND_PATTERNS = [
    r"\bnmap\b",
    r"\bmasscan\b",
    r"\bnet\s+view\b",
    r"\bnbtstat\b",
    r"\barp\s+-a\b",
    r"\bnetstat\b",
    r"\broute\s+print\b",
    r"\bipconfig\s+/all\b",
    r"\bGet-NetNeighbor\b",
    r"\bTest-NetConnection\b",
    r"\bResolve-DnsName\b",
    r"\bnslookup\b",
    r"\bping\s+(?:10\.|127\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)",
    r"\b(?:curl|wget|Invoke-WebRequest|iwr)\b[^\n\r]*(?:10\.|127\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)",
    r"\b(?:ssh|scp|sftp|telnet|nc|netcat)\b[^\n\r]*(?:10\.|127\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)",
]

_PATH_ARG_KEYS = {
    "path",
    "file",
    "filename",
    "filepath",
    "file_path",
    "directory",
    "dir",
    "root",
    "cwd",
    "target",
    "output_path",
}

_URL_ARG_KEYS = {"url", "uri", "href"}


def hermes_source_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    release = json.loads((root / "configs/hermes-release.json").read_text(encoding="utf-8"))
    source = root / ".hermes" / release["tag"]
    if not (source / "install-stamp.json").is_file() or json.loads(
        (source / "install-stamp.json").read_text(encoding="utf-8")
    ).get("commit") != release["commit"]:
        raise RuntimeError("Pinned Hermes source missing or mismatched; run scripts/prepare_hermes.py and uv sync")
    return source


def hermes_home_dir() -> Path:
    return Path("data/hermes").resolve()


_DEFAULT_HERMES_CONFIG = """# xbot 内嵌 Hermes 默认配置。
# 主模型由 xbot 根目录 .env 注入；这里仅放 Hermes 自己的持久化能力。

model:
  provider: "custom"
  default: "MiniMax-M3"
  base_url: ""

terminal:
  backend: "local"
  cwd: "."
  timeout: 180
  lifetime_seconds: 300
  docker_mount_cwd_to_workspace: false

context:
  engine: "compressor"

compression:
  enabled: true
  threshold: 0.80

memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 6000
  user_char_limit: 3000
  nudge_interval: 3
  provider: ""

skills:
  creation_nudge_interval: 8

curator:
  enabled: true
  interval_hours: 168
  min_idle_hours: 2
  stale_after_days: 30
  archive_after_days: 90
  backup:
    enabled: true
    keep: 5

auxiliary:
  curator:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 600
    extra_body: {}
"""


_DEFAULT_HERMES_ENV_EXAMPLE = """# Hermes 专属扩展环境变量示例。
# 主聊天模型不要在这里配置；主模型统一使用 xbot 根目录 .env:
# XBOT_LLM_BASE_URL / XBOT_LLM_API_KEY / XBOT_LLM_MODEL / XBOT_LLM_PROVIDER
#
# 只有 Hermes 自带扩展、skill、外部 memory provider 需要的 key 才放这里。

# OpenRouter / Nous / Anthropic / Gemini 等辅助模型凭证。
# OPENROUTER_API_KEY=
# NOUS_API_KEY=
# ANTHROPIC_API_KEY=
# GEMINI_API_KEY=

# 搜索、浏览器、第三方 skill 示例。
# BRAVE_SEARCH_API_KEY=
# SERPAPI_API_KEY=
# GITHUB_TOKEN=

# 外部 memory provider 示例。
# HONCHO_API_KEY=
# MEM0_API_KEY=
# HINDSIGHT_API_KEY=
"""


def _ensure_hermes_import_path() -> Path:
    source = hermes_source_dir()
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    for name in ("run_agent", "hermes_state", "model_tools"):
        module = sys.modules.get(name)
        if module is not None and not Path(module.__file__).resolve().is_relative_to(source):
            raise RuntimeError(f"Different Hermes source already loaded for {name}; restart xbot")
    from xbot.agent.tools.hermes_artifacts import register_xbot_artifact_tools
    from xbot.agent.tools.hermes_qq import register_xbot_qq_tools
    from xbot.agent.tools.hermes_telegram import register_xbot_telegram_tools
    from xbot.agent.tools.hermes_wechat import register_xbot_wechat_tools

    register_xbot_wechat_tools()
    register_xbot_qq_tools()
    register_xbot_telegram_tools()
    register_xbot_artifact_tools()
    return source


def _assert_safe_hermes_sqlite() -> None:
    """Refuse Hermes state writes on SQLite builds affected by WAL-reset corruption."""
    _ensure_hermes_import_path()
    from hermes_cli.sqlite_runtime import is_sqlite_wal_reset_vulnerable

    if is_sqlite_wal_reset_vulnerable(sqlite3.sqlite_version_info):
        raise RuntimeError(
            "Hermes cannot safely use this Python runtime: linked SQLite "
            f"{sqlite3.sqlite_version} contains the WAL-reset corruption bug. "
            "Use SQLite >=3.51.3, the 3.50.7 backport, or the 3.44.6 backport. "
            "The xbot Docker image builds a fixed SQLite automatically."
        )


def _ensure_hermes_home_files(home_dir: Path) -> None:
    home_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("logs", "memories", "skills", "sessions", "cron"):
        (home_dir / dirname).mkdir(parents=True, exist_ok=True)

    config_path = home_dir / "config.yaml"
    if not config_path.exists():
        config_path.write_text(_DEFAULT_HERMES_CONFIG, encoding="utf-8")

    env_example_path = home_dir / ".env.example"
    if not env_example_path.exists():
        env_example_path.write_text(_DEFAULT_HERMES_ENV_EXAMPLE, encoding="utf-8")


def _provider_for_config(config: AgentConfig) -> str | None:
    # Anthropic-compatible providers may not use api.anthropic.com, e.g. MiniMax Anthropic endpoint.
    if config.llm.provider == "anthropic":
        return "anthropic"
    return "custom"


def _api_mode_for_config(config: AgentConfig) -> str | None:
    base_url = (config.llm.base_url or "").rstrip("/").lower()
    if config.llm.provider == "anthropic" or base_url.endswith("/anthropic"):
        return "anthropic_messages"
    return "chat_completions"


def _configure_hermes_auxiliary_client(auxiliary_client: Any) -> None:
    """Keep automatic auxiliary calls on the current Xbot route."""
    original_resolve = auxiliary_client.resolve_provider_client
    if getattr(original_resolve, "_xbot_scoped_resolver", False):
        return

    def resolve_xbot_provider(
        provider: str,
        model: str | None = None,
        async_mode: bool = False,
        raw_codex: bool = False,
        explicit_base_url: str | None = None,
        explicit_api_key: str | None = None,
        api_mode: str | None = None,
        main_runtime: dict[str, Any] | None = None,
        is_vision: bool = False,
        task: str | None = None,
        pool_choice: Any = None,
    ) -> tuple[Any | None, str | None]:
        runtime = _HERMES_AUX_RUNTIME.get()
        if runtime and not explicit_base_url and (provider or "auto").strip().lower() in {"auto", "custom"}:
            provider = "custom"
            model = model or runtime["model"]
            explicit_base_url = runtime["base_url"]
            explicit_api_key = explicit_api_key or runtime["api_key"]
            api_mode = api_mode or runtime["api_mode"]
            main_runtime = main_runtime or runtime
        return original_resolve(
            provider,
            model,
            async_mode=async_mode,
            raw_codex=raw_codex,
            explicit_base_url=explicit_base_url,
            explicit_api_key=explicit_api_key,
            api_mode=api_mode,
            main_runtime=main_runtime,
            is_vision=is_vision,
            task=task,
            pool_choice=pool_choice,
        )

    resolve_xbot_provider._xbot_scoped_resolver = True
    auxiliary_client.resolve_provider_client = resolve_xbot_provider


def _toolsets_for_source(source: str) -> list[str]:
    profile = _permission_profile_for_source(source)
    is_qq = ":qq:" in (source or "")
    is_telegram = ":telegram:" in (source or "")
    channel_toolset = "telegram" if is_telegram else "qq" if is_qq else "wechat"
    if profile == "guest":
        return [channel_toolset, "artifacts"]
    if profile == "member":
        return [channel_toolset, *[item for item in _MEMBER_TOOLSETS if item not in {"qq", "telegram", "wechat"}]]
    return ["hermes-api-server", channel_toolset, "artifacts"]


def _permission_profile_for_source(source: str) -> str:
    normalized = (source or "").strip()
    if normalized.endswith((":guest", ":restricted")):
        return "guest"
    if normalized.endswith(":member"):
        return "member"
    return "admin"


def _session_source_for_source(source: str) -> str:
    """Map a permission-scoped xbot source back to the shared Hermes session.

    Tool permission is decided per incoming message, but chat memory should
    stay at the channel conversation level. For example, a WeChat group should
    not split into two Hermes sessions just because one turn is restricted.
    """
    normalized = (source or "default").strip() or "default"
    for suffix in (":restricted", ":member", ":guest"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _session_id_for_source(source: str) -> str:
    session_source = _session_source_for_source(source)
    safe = "".join(ch if ch.isalnum() else "-" for ch in session_source.strip().lower())
    safe = "-".join(part for part in safe.split("-") if part)
    return f"xbot-{safe[:96] or 'default'}"


def _artifact_output_dir(source: str, channel_context: dict[str, Any] | None) -> Path:
    channel = dict(channel_context or {})
    platform = "telegram" if ":telegram:" in source else "qq" if ":qq:" in source else "wechat"
    identity = "\0".join((
        platform,
        str(channel.get("conversation_id") or _session_source_for_source(source)),
        str(channel.get("sender_id") or "anonymous"),
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    output_dir = hermes_home_dir() / "outputs" / platform / digest
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return output_dir.resolve()


def _persona_identity_override(channel_context: dict[str, Any] | None) -> str | None:
    prompt = str((channel_context or {}).get("persona_prompt") or "").strip()[:8000]
    return prompt or None


def _model_for_channel(config: AgentConfig, channel_context: dict[str, Any] | None) -> str:
    conversation_model = str((channel_context or {}).get("conversation_model") or "").strip()
    if conversation_model and conversation_model in config.llm.enabled_models:
        return conversation_model
    return config.llm.model


def clear_hermes_session(source: str | None = None) -> dict[str, Any]:
    """Delete the Hermes session mapped to an xbot source."""
    _assert_safe_hermes_sqlite()
    home_dir = hermes_home_dir()
    _ensure_hermes_home_files(home_dir)
    os.environ["HERMES_HOME"] = str(home_dir)
    _ensure_hermes_import_path()

    from gateway.session_ingress_media import native_inputs_root
    from persistence_assembly import open_persistence, profile_scope
    from session_retention import after_sessions_removed

    normalized_source = source or "default"
    session_id = _session_id_for_source(normalized_source)
    with open_persistence(profile_scope(home=home_dir)) as store:
        deleted = store.sessions.delete(
            session_id, include_compression_chain=True, media_root=str(native_inputs_root()),
        )
        after_sessions_removed(
            store, home_dir, deleted, reason="delete", primary=session_id, sessions_dir=home_dir / "sessions",
        )
    return {
        "success": True,
        "runtime": "hermes",
        "source": normalized_source,
        "session_id": session_id,
        "deleted": bool(deleted),
        "message": "Hermes session cleared; the next turn will rebuild system prompt and reload SOUL.md.",
    }


def _input_with_attachments(input_text: str, attachments: list[dict] | None) -> str:
    if not attachments:
        return input_text
    lines = [input_text.rstrip(), "", "[xbot attachments]"]
    for item in attachments:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("filename") or item.get("path") or "attachment"
        path = item.get("path") or item.get("local_path") or item.get("url") or ""
        media_type = item.get("media_type") or item.get("mime_type") or item.get("type") or ""
        lines.append(f"- name={name} type={media_type} path={path}")
    return "\n".join(lines).strip()


def _restore_session_history(store: Any, session_id: str) -> tuple[str, list[dict[str, Any]]]:
    from persistence.core.identity import SessionId

    resolved = store.lineage.resolve_resume_target(SessionId(session_id))
    restored = store.messages.read_conversation(resolved)
    return resolved, [item.as_openai_message() for item in restored if item.role != "session_meta"]


def _member_workspace_roots(config: AgentConfig) -> list[Path]:
    roots = getattr(config.member_policy, "workspace_roots", None) or []
    resolved: list[Path] = []
    base = Path.cwd()
    for raw in roots:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = base / path
        resolved.append(path.resolve())
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_member_path(raw_path: str, policy: dict[str, Any]) -> Path:
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        cwd = policy.get("cwd")
        base = Path(str(cwd)).expanduser() if cwd else Path.cwd()
        if not base.is_absolute():
            base = Path.cwd() / base
        path = base / path
    return path.resolve()


def _member_path_allowed(raw_path: str, policy: dict[str, Any]) -> bool:
    try:
        resolved = _resolve_member_path(raw_path, policy)
    except Exception:
        return False
    attachment_paths = policy.get("attachment_paths") or []
    if any(resolved == Path(path) for path in attachment_paths):
        return True
    roots = policy.get("workspace_roots") or []
    return any(_is_relative_to(resolved, Path(root)) for root in roots)


def _extract_values_by_key(value: Any, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in keys and isinstance(item, str):
                found.append(item)
            found.extend(_extract_values_by_key(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_extract_values_by_key(item, keys))
    return found


def _host_is_private(host: str) -> bool:
    hostname = (host or "").strip().strip("[]").lower()
    if not hostname:
        return False
    if hostname in _PRIVATE_HOSTNAMES or hostname.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _url_is_private(raw_url: str) -> bool:
    text = str(raw_url or "").strip()
    if not text:
        return False
    parsed = urlparse(text if "://" in text else f"http://{text}")
    return _host_is_private(parsed.hostname or "")


def _command_looks_like_private_network_probe(command: str) -> bool:
    text = str(command or "")
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _LAN_COMMAND_PATTERNS)


def _tool_policy_denial(function_name: str, function_args: dict[str, Any], policy: dict[str, Any]) -> str | None:
    profile = policy.get("profile") or "admin"
    if profile == "admin":
        return None
    if profile == "guest":
        channel = str(policy.get("channel") or "")
        allowed = {
            "wechat_send_text", "wechat_send_image", "wechat_send_file", "wechat_send_voice",
            "wechat_send_video", "wechat_send_link", "wechat_send_music_card",
        } if channel in {"", "wechat"} else {
            "qq_send_text", "qq_send_markdown", "qq_send_image", "qq_send_file", "qq_send_voice",
            "qq_send_video", "qq_send_stream", "qq_input_notify",
        } if channel == "qq" else {
            "telegram_send_text", "telegram_send_image", "telegram_send_file",
            "telegram_send_voice", "telegram_send_video",
        }
        allowed.add("artifact_create")
        if function_name in allowed:
            return None
        return "访客只能使用当前通道的消息工具和通用文件产物。"

    name = str(function_name or "")
    args = function_args if isinstance(function_args, dict) else {}
    channel = str(policy.get("channel") or "")
    if channel == "qq" and name.startswith("wechat_send_"):
        return "QQ 会话不能调用 WeChat 发送工具。"
    if channel == "wechat" and name.startswith("qq_"):
        return "WeChat 会话不能调用 QQ 工具。"
    if channel != "telegram" and name.startswith("telegram_"):
        return "非 Telegram 会话不能调用 Telegram 工具。"
    if channel == "telegram" and name.startswith(("qq_", "wechat_send_")):
        return "Telegram 会话不能调用其他通道的发送工具。"
    if name in _MEMBER_DENIED_TOOLS or any(name.startswith(prefix) for prefix in _MEMBER_DENIED_PREFIXES):
        return f"普通成员不能调用 {name}。"

    if name == "terminal":
        if not bool(policy.get("allow_terminal", True)):
            return "普通成员的终端工具已在配置中关闭。"
        command = str(args.get("command") or args.get("cmd") or "")
        if _command_looks_like_private_network_probe(command):
            return "普通成员不能扫描、探测或访问局域网/私有网络目标。"
        cwd = args.get("cwd") or args.get("working_dir")
        if cwd and not _member_path_allowed(str(cwd), policy):
            return "普通成员只能在授权工作目录内执行终端命令。"

    if name in {"read_file", "write_file", "patch", "search_files"}:
        path_values = _extract_values_by_key(args, _PATH_ARG_KEYS)
        if not path_values:
            return "普通成员文件工具必须显式指定授权工作目录内的路径。"
        for path_value in path_values:
            if not _member_path_allowed(path_value, policy):
                return f"普通成员不能访问授权工作目录外的路径: {path_value}"

    if name in {"web_extract", "browser_navigate"}:
        if not bool(policy.get("allow_public_web", True)):
            return "普通成员的公网访问工具已在配置中关闭。"
        url_values = _extract_values_by_key(args, _URL_ARG_KEYS)
        for url in url_values:
            if bool(policy.get("block_private_network", True)) and _url_is_private(url):
                return f"普通成员不能访问 localhost、内网或私有网络 URL: {url}"

    if bool(policy.get("block_private_network", True)):
        for url in _extract_values_by_key(args, _URL_ARG_KEYS):
            if _url_is_private(url):
                return f"普通成员不能访问 localhost、内网或私有网络 URL: {url}"

    return None


def _policy_error(message: str) -> str:
    return json.dumps(
        {
            "error": "xbot_tool_policy_denied",
            "message": message,
        },
        ensure_ascii=False,
    )


def _install_hermes_tool_policy_wrapper() -> None:
    import model_tools

    original = getattr(model_tools, "_xbot_original_handle_function_call", None)
    if original is None:
        original = model_tools.handle_function_call
        model_tools._xbot_original_handle_function_call = original

        def xbot_policy_handle_function_call(function_name: str, function_args: dict[str, Any], *args, **kwargs) -> str:
            policy = _HERMES_TOOL_POLICY.get()
            if policy:
                denial = _tool_policy_denial(function_name, function_args or {}, policy)
                if denial:
                    logger.warning(
                        "Hermes 工具调用被 xbot 权限策略拦截: profile={} tool={} reason={}",
                        policy.get("profile"),
                        function_name,
                        denial,
                    )
                    return _policy_error(denial)
            return original(function_name, function_args, *args, **kwargs)

        model_tools.handle_function_call = xbot_policy_handle_function_call


def _bind_hermes_tool_policy(agent: Any, policy: dict[str, Any]) -> None:
    from agent.tool_guardrails import ToolGuardrailDecision

    if policy["profile"] == "admin":
        return
    guardrails = agent._tool_guardrails
    upstream_check = guardrails.before_call
    upstream_block = agent._guardrail_block_result

    def before_call(name: str, args: dict[str, Any]) -> ToolGuardrailDecision:
        denial = _tool_policy_denial(name, args, policy)
        if denial:
            return ToolGuardrailDecision(action="block", code="xbot_tool_policy_denied", message=denial, tool_name=name)
        return upstream_check(name, args)

    def block_result(decision: ToolGuardrailDecision) -> str:
        # Permission denials reject the call, not the rest of the conversation.
        if decision.code == "xbot_tool_policy_denied":
            return _policy_error(decision.message)
        return upstream_block(decision)

    guardrails.before_call = before_call
    agent._guardrail_block_result = block_result


def _tool_policy_for_source(
    config: AgentConfig,
    source: str,
    *,
    attachments: list[dict] | None = None,
) -> dict[str, Any]:
    profile = _permission_profile_for_source(source)
    policy_config = config.member_policy
    if profile == "member" and not policy_config.enabled:
        profile = "admin"
    attachment_paths: list[Path] = []
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        raw_path = attachment.get("local_path") or attachment.get("path")
        if not raw_path:
            continue
        resolved: Path | None = None
        try:
            path = Path(str(raw_path)).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            resolved = path.resolve()
        except Exception:
            resolved = None
        if resolved is not None and resolved.is_file():
            attachment_paths.append(resolved)
    return {
        "profile": profile,
        "channel": "telegram" if ":telegram:" in (source or "") else "qq" if ":qq:" in (source or "") else "wechat" if ":wechat" in (source or "") else "",
        "workspace_roots": _member_workspace_roots(config),
        "attachment_paths": attachment_paths,
        "cwd": Path.cwd(),
        "allow_terminal": bool(policy_config.allow_terminal),
        "allow_public_web": bool(policy_config.allow_public_web),
        "block_private_network": bool(policy_config.block_private_network),
    }


def _guest_direct_tools(source: str, policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose the small guest allowlist directly, without deferred tool search."""
    from model_tools import get_tool_definitions

    tool_definitions = get_tool_definitions(
        _toolsets_for_source(source),
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    return [
        definition
        for definition in tool_definitions
        if _tool_policy_denial(
            str((definition.get("function") or {}).get("name") or ""),
            {},
            policy,
        ) is None
    ]


async def run_hermes_agent(
    *,
    config: AgentConfig,
    task_id: str,
    input_text: str,
    source: str,
    attachments: list[dict] | None,
    add_event: Callable[..., Any],
    llm_status: Callable[[], dict],
    send_reply: Callable[..., Any] | None = None,
    mark_proactive_send: Callable[[], None] | None = None,
    channel_context: dict[str, Any] | None = None,
) -> str:
    from xbot.core.exceptions import XBotError

    web_source = source.startswith("terminal:control-ui:")
    if not config.llm.enabled or not config.llm.api_key:
        if web_source:
            raise XBotError("尚未配置模型，请先打开设置。")
        return "LLM provider is not available: missing model API configuration."
    home_dir = hermes_home_dir()
    _ensure_hermes_home_files(home_dir)
    os.environ["HERMES_HOME"] = str(home_dir)
    _ensure_hermes_import_path()
    os.environ["OPENAI_BASE_URL"] = str(config.llm.base_url or "")
    os.environ["OPENAI_API_KEY"] = str(config.llm.api_key or "")

    loop = asyncio.get_running_loop()
    tool_events: list[dict[str, Any]] = []

    def publish(event_type: str, content: object) -> None:
        async def _publish() -> None:
            await add_event(task_id, event_type, content)

        asyncio.run_coroutine_threadsafe(_publish(), loop)

    def tool_progress_callback(*args: Any) -> None:
        payload = {"args": [str(arg)[:1200] for arg in args]}
        tool_events.append({"type": "tool.progress", **payload})
        publish("tool.progress", payload)

    def tool_start_callback(call_id: str, name: str, args: object) -> None:
        payload = {"call_id": call_id, "tool": name, "input": args}
        tool_events.append({"type": "tool.started", **payload})
        publish("tool.started", payload)

    def tool_complete_callback(call_id: str, name: str, args: object, result: object) -> None:
        payload = {"call_id": call_id, "tool": name, "input": args, "output": result}
        tool_events.append({"type": "tool.completed", **payload})
        publish("tool.completed", payload)

    def stream_delta_callback(delta: str | None) -> None:
        if delta:
            asyncio.run_coroutine_threadsafe(
                add_event(task_id, "llm.delta", {"delta": delta}, persist=False), loop
            )

    def run_sync() -> str:
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv(hermes_home=home_dir)
        _assert_safe_hermes_sqlite()

        from agent import auxiliary_client
        from agent.agent_init import set_config_context_length
        from persistence_assembly import open_persistence, profile_scope
        from run_agent import AIAgent

        from xbot.agent.tools.hermes_artifacts import (
            reset_artifact_context,
            set_artifact_context,
        )
        from xbot.agent.tools.hermes_qq import reset_send_context as reset_qq_send_context
        from xbot.agent.tools.hermes_qq import set_send_context as set_qq_send_context
        from xbot.agent.tools.hermes_telegram import (
            reset_send_context as reset_telegram_send_context,
        )
        from xbot.agent.tools.hermes_telegram import set_send_context as set_telegram_send_context
        from xbot.agent.tools.hermes_wechat import reset_send_context, set_send_context

        _install_hermes_tool_policy_wrapper()

        # Hermes .env is for Hermes-specific extensions. The primary model
        # remains controlled by xbot's root .env and is restored after Hermes'
        # loader/import path has had a chance to touch process env.
        os.environ["OPENAI_BASE_URL"] = str(config.llm.base_url or "")
        os.environ["OPENAI_API_KEY"] = str(config.llm.api_key or "")

        _configure_hermes_auxiliary_client(auxiliary_client)

        session_source = _session_source_for_source(source)
        session_id = _session_id_for_source(source)
        tool_policy = _tool_policy_for_source(config, source, attachments=attachments)
        token = _HERMES_TOOL_POLICY.set(tool_policy)
        send_token = None
        qq_send_token = None
        telegram_send_token = None
        artifact_output_dir = _artifact_output_dir(source, channel_context)
        runtime_channel = dict(channel_context or {})
        runtime_channel["media_roots"] = [
            *list(runtime_channel.get("media_roots") or []),
            str(artifact_output_dir),
        ]
        artifact_token = set_artifact_context({
            "output_dir": str(artifact_output_dir),
            "channel": tool_policy.get("channel") or "wechat",
        })
        session_parts = session_source.split(":", 3)
        if (
            send_reply is not None
            and len(session_parts) == 4
            and session_parts[0] == "channel"
            and session_parts[1] == "wechat"
        ):
            async def send_wechat_reply(**kwargs: Any) -> None:
                from xbot.messaging.models import Reply

                message_type = kwargs["message_type"]
                if session_parts[2] != "wechat869" and message_type in {
                    "voice", "video", "link", "music_card",
                }:
                    raise RuntimeError(f"{message_type} is only supported by the wechat869 adapter.")
                await send_reply(Reply(
                    platform=kwargs["platform"],
                    adapter=kwargs["adapter"],
                    conversation_id=kwargs["conversation_id"],
                    type=message_type,
                    content=kwargs["content"],
                    metadata=kwargs.get("metadata") or {},
                ))
                if mark_proactive_send is not None:
                    mark_proactive_send()

            send_token = set_send_context({
                "loop": loop,
                "sender": send_wechat_reply,
                "adapter": session_parts[2],
                "conversation_id": session_parts[3],
            })
        if (
            send_reply is not None
            and len(session_parts) == 4
            and session_parts[0] == "channel"
            and session_parts[1] == "qq"
        ):
            channel = runtime_channel
            async def send_qq_reply(**kwargs: Any) -> object | None:
                from xbot.messaging.models import Reply

                metadata = dict(kwargs.get("metadata") or {})
                quote_message_id = (
                    metadata.pop("quote_message_id")
                    if "quote_message_id" in metadata
                    else channel.get("message_id")
                )
                event_id = metadata.get("event_id") or channel.get("event_id")
                if quote_message_id and event_id:
                    raise ValueError("QQ sender 不能同时携带 quote_message_id 与 event_id")
                if event_id:
                    metadata["event_id"] = event_id
                result = await send_reply(Reply(
                    platform="qq", adapter="qq", conversation_id=kwargs.get("conversation_id") or session_parts[3],
                    type=str(kwargs.get("message_type") or "text"), content=str(kwargs.get("content") or ""),
                    metadata=metadata, quote_message_id=quote_message_id,
                ))
                return result

            qq_send_token = set_qq_send_context({
                "loop": loop, "sender": send_qq_reply, "adapter": "qq",
                "conversation_id": channel.get("conversation_id") or session_parts[3],
                "message_id": channel.get("message_id"), "event_id": channel.get("event_id"),
                "profile": channel.get("profile", "guest"),
                "scope": channel.get("scope", "private"), "media_roots": channel.get("media_roots", []),
                "mark_proactive_send": mark_proactive_send,
                "recall": channel.get("recall"), "react": channel.get("react"),
            })
        if (
            send_reply is not None
            and len(session_parts) == 4
            and session_parts[0] == "channel"
            and session_parts[1] == "telegram"
        ):
            channel = runtime_channel

            async def send_telegram_reply(**kwargs: Any) -> object | None:
                from xbot.messaging.models import Reply

                metadata = dict(kwargs.get("metadata") or {})
                quote_message_id = metadata.pop("quote_message_id", channel.get("message_id"))
                return await send_reply(Reply(
                    platform="telegram",
                    adapter="telegram",
                    conversation_id=kwargs.get("conversation_id") or session_parts[3],
                    type=str(kwargs.get("message_type") or "text"),
                    content=str(kwargs.get("content") or ""),
                    metadata=metadata,
                    quote_message_id=quote_message_id,
                ))

            telegram_send_token = set_telegram_send_context({
                "loop": loop,
                "sender": send_telegram_reply,
                "adapter": "telegram",
                "conversation_id": channel.get("conversation_id") or session_parts[3],
                "message_id": channel.get("message_id"),
                "profile": channel.get("profile", "guest"),
                "scope": channel.get("scope", "private"),
                "media_roots": channel.get("media_roots", []),
                "mark_proactive_send": mark_proactive_send,
            })
        agent = None
        store = None
        model = _model_for_channel(config, channel_context)
        aux_runtime = {
            "provider": _provider_for_config(config) or "custom",
            "model": model,
            "base_url": config.llm.base_url,
            "api_key": config.llm.api_key,
            "api_mode": _api_mode_for_config(config),
        }
        persona = _persona_identity_override(channel_context)
        aux_token = _HERMES_AUX_RUNTIME.set(aux_runtime)
        try:
            store = open_persistence(profile_scope(home=home_dir), eager=True)
            session_id, conversation_history = _restore_session_history(store, session_id)
            agent = AIAgent(
                base_url=config.llm.base_url,
                api_key=config.llm.api_key,
                provider=_provider_for_config(config),
                api_mode=_api_mode_for_config(config),
                model=model,
                max_iterations=90,
                enabled_toolsets=_toolsets_for_source(source),
                ephemeral_system_prompt=f"本会话角色设定（优先于默认角色）：\n{persona}" if persona else None,
                quiet_mode=True,
                save_trajectories=True,
                session_id=session_id,
                persistence=store,
                platform="xbot",
                gateway_session_key=session_source,
                max_tokens=config.llm.max_tokens,
                tool_progress_callback=tool_progress_callback,
                tool_start_callback=tool_start_callback,
                tool_complete_callback=tool_complete_callback,
                stream_delta_callback=stream_delta_callback,
            )
            if (context_length := config.llm.context_window_tokens) is not None:
                set_config_context_length(agent, context_length)
                agent.context_compressor.context_length = context_length
            _bind_hermes_tool_policy(agent, tool_policy)
            if tool_policy["profile"] == "guest":
                agent.tools = _guest_direct_tools(source, tool_policy)
                agent.valid_tool_names = {
                    str((definition.get("function") or {}).get("name") or "")
                    for definition in agent.tools
                }
            if conversation_history:
                publish(
                    "hermes.resumed",
                    {
                        "session_id": getattr(agent, "session_id", session_id),
                        "session_source": session_source,
                        "permission_source": source,
                        "permission_profile": tool_policy.get("profile"),
                        "message_count": len(conversation_history),
                        "user_message_count": sum(
                            1 for item in conversation_history if item.get("role") == "user"
                        ),
                    },
                )
            result = agent.run_conversation(
                _input_with_attachments(input_text, attachments),
                conversation_history=conversation_history,
                task_id=task_id,
            )
        finally:
            with contextlib.ExitStack() as cleanup:
                cleanup.callback(_HERMES_TOOL_POLICY.reset, token)
                cleanup.callback(_HERMES_AUX_RUNTIME.reset, aux_token)
                cleanup.callback(reset_artifact_context, artifact_token)
                if send_token is not None:
                    cleanup.callback(reset_send_context, send_token)
                if qq_send_token is not None:
                    cleanup.callback(reset_qq_send_context, qq_send_token)
                if telegram_send_token is not None:
                    cleanup.callback(reset_telegram_send_context, telegram_send_token)
                if store is not None:
                    cleanup.callback(store.close)
                if agent is not None:
                    cleanup.callback(agent.close)
        if isinstance(result, dict):
            if web_source and (result.get("failed") or result.get("completed") is False):
                raise XBotError("Hermes did not complete the turn")
            output = result.get("final_response") or result.get("response") or result.get("content") or ""
            if output or web_source:
                return str(output)
            return str(result)
        return str(result or "")

    await add_event(
        task_id,
        "hermes.started",
        {
            "status": llm_status(),
            "source": source,
            "session_id": _session_id_for_source(source),
            "session_source": _session_source_for_source(source),
            "permission_profile": _permission_profile_for_source(source),
            "member_workspace_roots": [
                str(path) for path in _member_workspace_roots(config)
            ],
            "toolsets": _toolsets_for_source(source),
        },
    )
    try:
        output = await anyio.to_thread.run_sync(run_sync)
    except Exception as exc:
        if web_source:
            logger.error("Web Hermes turn failed: task_id={} error_type={}", task_id, type(exc).__name__)
            raise XBotError("模型回复失败，请检查模型配置和运行日志。") from None
        logger.exception("Hermes Agent 执行失败: task_id={} error={}", task_id, exc)
        await add_event(task_id, "hermes.failed", {"error": str(exc)})
        return f"Hermes Agent 执行失败: {exc}"
    await add_event(
        task_id,
        "hermes.completed",
        {"output_chars": len(output), "tool_event_count": len(tool_events)},
    )
    return output.strip()
