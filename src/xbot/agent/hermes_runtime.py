from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

import anyio

from xbot.core.config import AgentConfig
from xbot.core.logging import logger


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
    if config.llm.provider == "anthropic" and "api.anthropic.com" in (config.llm.base_url or ""):
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
    if source.startswith("api") or source.startswith("terminal"):
        return ["hermes-api-server"]
    return ["hermes-api-server"]


def _session_id_for_source(source: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in source.strip().lower())
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


async def run_hermes_agent(
    *,
    config: AgentConfig,
    task_id: str,
    input_text: str,
    source: str,
    attachments: list[dict] | None,
    add_event: Callable[..., Any],
    llm_status: Callable[[], dict],
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

        # Hermes .env is for Hermes-specific extensions. The primary model
        # remains controlled by xbot's root .env and is restored after Hermes'
        # loader/import path has had a chance to touch process env.
        os.environ["OPENAI_BASE_URL"] = str(config.llm.base_url or "")
        os.environ["OPENAI_API_KEY"] = str(config.llm.api_key or "")

        _configure_hermes_auxiliary_client(auxiliary_client, config)

        session_db = SessionDB()
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
            session_id=_session_id_for_source(source),
            session_db=session_db,
            platform="xbot",
            gateway_session_key=source,
            skip_context_files=False,
            skip_memory=False,
            max_tokens=config.llm.max_tokens,
            tool_delay=0,
            tool_progress_callback=tool_progress_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            stream_delta_callback=stream_delta_callback,
        )
        conversation_history = _restore_session_history(agent)
        if conversation_history:
            publish(
                "hermes.resumed",
                {
                    "session_id": getattr(agent, "session_id", _session_id_for_source(source)),
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
