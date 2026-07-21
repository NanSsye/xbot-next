from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import anyio

from xbot.core.config import AgentConfig
from xbot.core.logging import logger


_HERMES_TOOL_POLICY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xbot_hermes_tool_policy",
    default=None,
)

_MEMBER_TOOLSETS = [
    "wechat",
    "web",
    "file",
    "terminal",
    "skills",
    "todo",
    "memory",
    "session_search",
    "clarify",
    "vision",
]

_MEMBER_DENIED_TOOLS = {
    "process",
    "execute_code",
    "delegate_task",
    "cronjob",
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

_MEMBER_DENIED_PREFIXES = ("browser_",)

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


def hermes_vendor_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "vendor" / "hermes"


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
    vendor_dir = hermes_vendor_dir()
    if not (vendor_dir / "run_agent.py").exists():
        raise RuntimeError(f"Hermes source is missing: {vendor_dir}")
    vendor_text = str(vendor_dir)
    if vendor_text not in sys.path:
        sys.path.insert(0, vendor_text)
    return vendor_dir


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


def _configure_hermes_auxiliary_client(auxiliary_client: Any, config: AgentConfig) -> None:
    """Route Hermes auxiliary work through xbot's primary model endpoint.

    Hermes normally probes OpenRouter/Nous/custom providers for side tasks such
    as compression, title generation, memory, and web extraction. In xbot
    embedded mode the root .env is the single model authority, so auxiliary
    calls should not fall through to Hermes account providers or emit auth
    warnings for providers the user never configured.
    """
    provider = _provider_for_config(config) or "custom"
    model = str(config.llm.model or "")
    base_url = str(config.llm.base_url or "")
    api_key = str(config.llm.api_key or "")
    api_mode = _api_mode_for_config(config)
    main_runtime = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "api_mode": api_mode or "",
    }

    try:
        auxiliary_client.set_runtime_main(provider, model)
    except Exception:
        pass

    original_resolve = auxiliary_client.resolve_provider_client

    def resolve_xbot_provider(
        requested_provider: str,
        model_override: str | None = None,
        async_mode: bool = False,
        raw_codex: bool = False,
        explicit_base_url: str | None = None,
        explicit_api_key: str | None = None,
        api_mode: str | None = None,
        main_runtime: dict[str, Any] | None = None,
        is_vision: bool = False,
    ) -> tuple[Any | None, str | None]:
        requested = (requested_provider or "auto").strip().lower()
        if requested in {"", "auto", "custom"}:
            return original_resolve(
                "custom",
                model_override or model,
                async_mode=async_mode,
                raw_codex=raw_codex,
                explicit_base_url=explicit_base_url or base_url,
                explicit_api_key=explicit_api_key or api_key,
                api_mode=api_mode or api_mode_for_call,
                main_runtime=main_runtime or main_runtime_payload,
                is_vision=is_vision,
            )
        return original_resolve(
            requested_provider,
            model_override,
            async_mode=async_mode,
            raw_codex=raw_codex,
            explicit_base_url=explicit_base_url,
            explicit_api_key=explicit_api_key,
            api_mode=api_mode,
            main_runtime=main_runtime or main_runtime_payload,
            is_vision=is_vision,
        )

    api_mode_for_call = api_mode
    main_runtime_payload = main_runtime

    def resolve_auto_xbot(main_runtime: dict[str, Any] | None = None) -> tuple[Any | None, str | None]:
        return original_resolve(
            "custom",
            model,
            explicit_base_url=base_url,
            explicit_api_key=api_key,
            api_mode=api_mode_for_call,
            main_runtime=main_runtime or main_runtime_payload,
        )

    def get_text_auxiliary_client(
        task: str = "",
        *,
        main_runtime: dict[str, Any] | None = None,
    ) -> tuple[Any | None, str | None]:
        return original_resolve(
            "custom",
            model,
            explicit_base_url=base_url,
            explicit_api_key=api_key,
            api_mode=api_mode_for_call,
            main_runtime=main_runtime or main_runtime_payload,
        )

    def get_async_text_auxiliary_client(
        task: str = "",
        *,
        main_runtime: dict[str, Any] | None = None,
    ) -> tuple[Any | None, str | None]:
        return original_resolve(
            "custom",
            model,
            async_mode=True,
            explicit_base_url=base_url,
            explicit_api_key=api_key,
            api_mode=api_mode_for_call,
            main_runtime=main_runtime or main_runtime_payload,
        )

    auxiliary_client._resolve_custom_runtime = lambda: (base_url.rstrip("/"), api_key, api_mode_for_call)
    auxiliary_client._resolve_auto = resolve_auto_xbot
    auxiliary_client.resolve_provider_client = resolve_xbot_provider
    auxiliary_client.get_text_auxiliary_client = get_text_auxiliary_client
    auxiliary_client.get_async_text_auxiliary_client = get_async_text_auxiliary_client
    auxiliary_client._get_provider_chain = lambda: []
    auxiliary_client._try_openrouter = lambda *args, **kwargs: (None, None)
    auxiliary_client._try_nous = lambda *args, **kwargs: (None, None)


def _toolsets_for_source(source: str) -> list[str]:
    profile = _permission_profile_for_source(source)
    if profile == "guest":
        return ["wechat"]
    if profile == "member":
        return list(_MEMBER_TOOLSETS)
    if source.startswith("api") or source.startswith("terminal"):
        return ["hermes-api-server"]
    return ["hermes-api-server"]


def _permission_profile_for_source(source: str) -> str:
    normalized = (source or "").strip()
    if normalized.endswith(":guest") or normalized.endswith(":restricted"):
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


def clear_hermes_session(source: str | None = None) -> dict[str, Any]:
    """Delete the Hermes session mapped to an xbot source."""
    _ensure_hermes_import_path()
    home_dir = hermes_home_dir()
    _ensure_hermes_home_files(home_dir)
    os.environ["HERMES_HOME"] = str(home_dir)

    from hermes_state import SessionDB

    normalized_source = source or "default"
    session_id = _session_id_for_source(normalized_source)
    session_db = SessionDB(db_path=home_dir / "state.db")
    deleted = session_db.delete_session(session_id, sessions_dir=home_dir / "sessions")
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


def _restore_session_history(agent: Any) -> list[dict[str, Any]]:
    session_db = getattr(agent, "_session_db", None)
    session_id = getattr(agent, "session_id", None)
    if not session_db or not session_id:
        return []
    try:
        session_row = session_db.get_session(session_id)
        if not session_row:
            return []
        resolved_id = session_db.resolve_resume_session_id(session_id)
        if resolved_id and resolved_id != session_id:
            agent.session_id = resolved_id
            session_id = resolved_id
        restored = session_db.get_messages_as_conversation(session_id)
    except Exception as exc:
        logger.warning("Hermes 会话历史恢复失败: session_id={} error={}", session_id, exc)
        return []
    return [item for item in restored if item.get("role") != "session_meta"]


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
    roots = policy.get("workspace_roots") or []
    if not roots:
        return False
    try:
        resolved = _resolve_member_path(raw_path, policy)
    except Exception:
        return False
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
        if function_name in {
            "wechat_send_text", "wechat_send_image", "wechat_send_file", "wechat_send_voice",
            "wechat_send_video", "wechat_send_link", "wechat_send_music_card",
        }:
            return None
        return "当前 869 用户是 guest 权限，只能普通聊天，不能调用工具。"

    name = str(function_name or "")
    args = function_args if isinstance(function_args, dict) else {}
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
    import run_agent

    original = getattr(model_tools, "_xbot_original_handle_function_call", None)
    if original is None:
        original = model_tools.handle_function_call
        setattr(model_tools, "_xbot_original_handle_function_call", original)

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

    run_agent.handle_function_call = model_tools.handle_function_call


def _tool_policy_for_source(config: AgentConfig, source: str) -> dict[str, Any]:
    profile = _permission_profile_for_source(source)
    policy_config = config.member_policy
    if profile == "member" and not policy_config.enabled:
        profile = "admin"
    return {
        "profile": profile,
        "workspace_roots": _member_workspace_roots(config),
        "cwd": Path.cwd(),
        "allow_terminal": bool(policy_config.allow_terminal),
        "allow_public_web": bool(policy_config.allow_public_web),
        "block_private_network": bool(policy_config.block_private_network),
    }


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
) -> str:
    if not config.llm.enabled or not config.llm.api_key:
        return "LLM provider is not available: missing model API configuration."
    _ensure_hermes_import_path()
    home_dir = hermes_home_dir()
    _ensure_hermes_home_files(home_dir)
    os.environ["HERMES_HOME"] = str(home_dir)
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
            publish("llm.delta", {"delta": delta})

    def run_sync() -> str:
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv(hermes_home=home_dir)

        from run_agent import AIAgent
        from agent import auxiliary_client
        from hermes_state import SessionDB
        from tools.xbot_wechat_tools import reset_send_context, set_send_context

        _install_hermes_tool_policy_wrapper()

        # Hermes .env is for Hermes-specific extensions. The primary model
        # remains controlled by xbot's root .env and is restored after Hermes'
        # loader/import path has had a chance to touch process env.
        os.environ["OPENAI_BASE_URL"] = str(config.llm.base_url or "")
        os.environ["OPENAI_API_KEY"] = str(config.llm.api_key or "")

        _configure_hermes_auxiliary_client(auxiliary_client, config)

        session_db = SessionDB()
        session_source = _session_source_for_source(source)
        session_id = _session_id_for_source(source)
        tool_policy = _tool_policy_for_source(config, source)
        token = _HERMES_TOOL_POLICY.set(tool_policy)
        send_token = None
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
        agent = AIAgent(
            base_url=config.llm.base_url,
            api_key=config.llm.api_key,
            provider=_provider_for_config(config),
            api_mode=_api_mode_for_config(config),
            model=config.llm.model,
            max_iterations=90,
            enabled_toolsets=_toolsets_for_source(source),
            quiet_mode=True,
            save_trajectories=True,
            session_id=session_id,
            session_db=session_db,
            platform="xbot",
            gateway_session_key=session_source,
            skip_context_files=False,
            skip_memory=False,
            max_tokens=config.llm.max_tokens,
            tool_delay=0,
            tool_progress_callback=tool_progress_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            stream_delta_callback=stream_delta_callback,
        )
        try:
            conversation_history = _restore_session_history(agent)
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
            if send_token is not None:
                reset_send_context(send_token)
            _HERMES_TOOL_POLICY.reset(token)
        if isinstance(result, dict):
            output = result.get("final_response") or result.get("response") or result.get("content") or ""
            if output:
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
        logger.exception("Hermes Agent 执行失败: task_id={} error={}", task_id, exc)
        await add_event(task_id, "hermes.failed", {"error": str(exc)})
        return f"Hermes Agent 执行失败: {exc}"
    await add_event(
        task_id,
        "hermes.completed",
        {"output_chars": len(output), "tool_event_count": len(tool_events)},
    )
    return output.strip()
