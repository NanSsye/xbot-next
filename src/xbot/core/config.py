from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class XBotConfig(BaseModel):
    name: str = "xbot"
    timezone: str = "Asia/Shanghai"
    debug: bool = False


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8548


class ApiConfig(BaseModel):
    auth_enabled: bool = False
    token: str = ""
    cors_origins: list[str] = Field(default_factory=list)


class StorageConfig(BaseModel):
    type: Literal["postgresql", "sqlite"] = "postgresql"
    url: str = "postgresql+asyncpg://xbot:xbot@192.168.6.19:5433/xbot"
    echo: bool = False
    persist_runtime_events: bool = True
    auto_bootstrap: bool = True
    admin_url: str | None = None
    create_database: bool = True
    create_role: bool = True
    run_migrations_on_startup: bool = True


class QueueConfig(BaseModel):
    type: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://192.168.6.41:6379/15"
    main_queue: str = "xbot:messages"
    reply_queue: str = "xbot:replies"
    event_queue: str = "xbot:events"
    agent_task_queue: str = "xbot:agent_tasks"
    dead_letter_queue: str = "xbot:dead_letters"


class QueueRetryConfig(BaseModel):
    max_attempts: int = 3
    initial_delay_seconds: int = 2
    max_delay_seconds: int = 60
    backoff: Literal["fixed", "exponential"] = "exponential"


class QueueSettings(QueueConfig):
    retry: QueueRetryConfig = Field(default_factory=QueueRetryConfig)


class ConversationContextConfig(BaseModel):
    recent_messages: int = 0
    max_chars: int = 16000
    auto_summarize: bool = True
    summary_every_messages: int = 50


class ConversationConcurrencyConfig(BaseModel):
    per_conversation_serial: bool = True
    max_active_conversations: int = 1000


class ConversationConfig(BaseModel):
    enabled: bool = True
    store: Literal["postgresql", "sqlite"] = "postgresql"
    default_scope: Literal["private", "group", "channel", "agent_task", "system"] = "private"
    context: ConversationContextConfig = Field(default_factory=ConversationContextConfig)
    concurrency: ConversationConcurrencyConfig = Field(default_factory=ConversationConcurrencyConfig)


class RuntimeConcurrencyConfig(BaseModel):
    max_message_tasks: int = 100
    max_plugin_tasks: int = 50
    max_agent_tasks: int = 5
    max_tool_tasks: int = 20
    sync_worker_threads: int = 8


class RuntimeTimeoutConfig(BaseModel):
    message_seconds: int = 60
    plugin_seconds: int = 30
    tool_seconds: int = 120
    agent_task_seconds: int = 1800
    http_seconds: int = 30


class RuntimeConfig(BaseModel):
    concurrency: RuntimeConcurrencyConfig = Field(default_factory=RuntimeConcurrencyConfig)
    timeout: RuntimeTimeoutConfig = Field(default_factory=RuntimeTimeoutConfig)


class PluginConfig(BaseModel):
    directory: str = "plugins"
    auto_load: bool = True


class SkillConfig(BaseModel):
    directory: str = "skills"
    auto_load: bool = True


class AgentApprovalConfig(BaseModel):
    dangerous_tools: bool = True
    outside_workspace: bool = True
    delete_files: bool = True
    shell_exec: bool = False
    database_write: bool = True


class AgentLLMConfig(BaseModel):
    enabled: bool = False
    provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str = "gpt-4.1-mini"
    context_window_tokens: int | None = None
    timeout_seconds: int = 60
    max_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    max_tokens: int = 2000
    temperature: float = 0.2


class AgentMCPServerConfig(BaseModel):
    enabled: bool = True
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    include_tools: list[str] = Field(default_factory=list)
    exclude_tools: list[str] = Field(default_factory=list)
    timeout: int = 120
    connect_timeout: int = 60


class AgentMCPConfig(BaseModel):
    enabled: bool = True
    servers: dict[str, AgentMCPServerConfig] = Field(default_factory=dict)


class AgentScheduleConfig(BaseModel):
    enabled: bool = True
    tick_seconds: float = 30.0
    max_due_per_tick: int = 10


class AgentMemberPolicyConfig(BaseModel):
    enabled: bool = True
    workspace_roots: list[str] = Field(default_factory=lambda: ["workspace", ".agent-workspace"])
    allow_terminal: bool = True
    allow_public_web: bool = True
    block_private_network: bool = True


class AgentConfig(BaseModel):
    enabled: bool = True
    uses_hermes_runtime: bool = True
    mode: Literal["safe", "developer", "admin"] = "developer"
    admin_mode_allowed: bool = False
    timezone: str = "Asia/Shanghai"
    workspace_root: str = "."
    allow_shell: bool = False
    allow_file_write: bool = True
    max_tool_iterations: int = 0
    auto_delegate_channel_tasks: bool = True
    max_inline_tool_result_chars: int = 20000
    tool_result_artifact_dir: str = "data/artifacts/agent_tool_results"
    approval: AgentApprovalConfig = Field(default_factory=AgentApprovalConfig)
    llm: AgentLLMConfig = Field(default_factory=AgentLLMConfig)
    mcp: AgentMCPConfig = Field(default_factory=AgentMCPConfig)
    schedule: AgentScheduleConfig = Field(default_factory=AgentScheduleConfig)
    member_policy: AgentMemberPolicyConfig = Field(default_factory=AgentMemberPolicyConfig)


class WebAdapterConfig(BaseModel):
    enabled: bool = True


class Wechat869AdapterConfig(BaseModel):
    enabled: bool = False
    host: str = "192.168.6.19"
    port: int = 8848
    admin_key: str = ""
    token_key: str = ""
    ws_url: str = ""
    bot_wxid: str = ""
    bot_nickname: str = ""
    admin_wxids: list[str] = Field(default_factory=list)
    member_wxids: list[str] = Field(default_factory=list)
    default_profile: Literal["member", "guest"] = "member"
    connect_timeout_seconds: int = 10
    reconnect_seconds: int = 5
    text_only: bool = False
    media_enabled: bool = True
    media_dir: str = "data/wechat869/media"
    auto_download_images: bool = True
    auto_download_files: bool = True
    max_image_bytes: int = 20 * 1024 * 1024
    max_file_bytes: int = 100 * 1024 * 1024


class WechatIlinkAdapterConfig(BaseModel):
    enabled: bool = False
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    token: str = ""
    cursor: str = ""
    poll_interval_seconds: float = 1.0
    connect_timeout_seconds: int = 45
    bot_wxid: str = ""
    bot_nickname: str = ""
    media_enabled: bool = True
    media_dir: str = "data/wechat_ilink/media"
    auto_download_images: bool = True
    auto_download_files: bool = True
    max_image_bytes: int = 20 * 1024 * 1024
    max_file_bytes: int = 100 * 1024 * 1024


class AdapterConfig(BaseModel):
    web: WebAdapterConfig = Field(default_factory=WebAdapterConfig)
    wechat869: Wechat869AdapterConfig = Field(default_factory=Wechat869AdapterConfig)
    wechat_ilink: WechatIlinkAdapterConfig = Field(default_factory=WechatIlinkAdapterConfig)


class Settings(BaseModel):
    xbot: XBotConfig = Field(default_factory=XBotConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    skills: SkillConfig = Field(default_factory=SkillConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    adapters: AdapterConfig = Field(default_factory=AdapterConfig)
    config_file: Path | None = None


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _normalize_agent_config(data: dict[str, Any]) -> None:
    agent = data.get("agent")
    if not isinstance(agent, dict):
        return
    if isinstance(agent.get("workspace"), str):
        agent["workspace_root"] = agent.pop("workspace")


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on", "admin"}


def _env_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _env_int(value: str) -> int:
    return int(value.replace("_", "").strip())


def load_settings(config_file: str | os.PathLike[str] | None = None) -> Settings:
    path = Path(config_file or os.getenv("XBOT_CONFIG_FILE", "configs/xbot.toml"))
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    dotenv_values = (
        {}
        if os.getenv("XBOT_LOAD_DOTENV", "true").lower() in {"0", "false", "no", "off"}
        else _load_dotenv(path.parent.parent / ".env")
    )
    env = {**dotenv_values, **os.environ}
    if server_host := env.get("XBOT_SERVER_HOST") or env.get("XBOT_HOST"):
        data.setdefault("server", {})["host"] = server_host
    if server_port := env.get("XBOT_SERVER_PORT") or env.get("XBOT_PORT"):
        data.setdefault("server", {})["port"] = _env_int(server_port)
    if storage_type := env.get("XBOT_STORAGE_TYPE"):
        data.setdefault("storage", {})["type"] = storage_type
    if database_url := env.get("XBOT_DATABASE_URL"):
        data.setdefault("storage", {})["url"] = database_url
    if admin_database_url := env.get("XBOT_ADMIN_DATABASE_URL"):
        data.setdefault("storage", {})["admin_url"] = admin_database_url
    if auto_bootstrap := env.get("XBOT_DATABASE_AUTO_BOOTSTRAP"):
        data.setdefault("storage", {})["auto_bootstrap"] = _env_bool(auto_bootstrap)
    if run_migrations := env.get("XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP"):
        data.setdefault("storage", {})["run_migrations_on_startup"] = _env_bool(run_migrations)
    if api_auth_enabled := env.get("XBOT_API_AUTH_ENABLED"):
        data.setdefault("api", {})["auth_enabled"] = _env_bool(api_auth_enabled)
    if api_token := env.get("XBOT_API_TOKEN"):
        data.setdefault("api", {})["token"] = api_token
    if cors_origins := env.get("XBOT_API_CORS_ORIGINS"):
        data.setdefault("api", {})["cors_origins"] = _env_list(cors_origins)
    if redis_url := env.get("XBOT_REDIS_URL"):
        data.setdefault("queue", {})["redis_url"] = redis_url
    if queue_type := env.get("XBOT_QUEUE_TYPE"):
        data.setdefault("queue", {})["type"] = queue_type
    if conversation_store := env.get("XBOT_CONVERSATION_STORE"):
        data.setdefault("conversation", {})["store"] = conversation_store
    if llm_api_key := env.get("XBOT_LLM_API_KEY"):
        data.setdefault("agent", {}).setdefault("llm", {})["api_key"] = llm_api_key
    if llm_provider := env.get("XBOT_LLM_PROVIDER"):
        data.setdefault("agent", {}).setdefault("llm", {})["provider"] = llm_provider
    if llm_base_url := env.get("XBOT_LLM_BASE_URL"):
        data.setdefault("agent", {}).setdefault("llm", {})["base_url"] = llm_base_url
    if llm_model := env.get("XBOT_LLM_MODEL"):
        data.setdefault("agent", {}).setdefault("llm", {})["model"] = llm_model
    if llm_context_window := env.get("XBOT_LLM_CONTEXT_WINDOW_TOKENS"):
        data.setdefault("agent", {}).setdefault("llm", {})["context_window_tokens"] = _env_int(llm_context_window)
    if llm_timeout := env.get("XBOT_LLM_TIMEOUT_SECONDS"):
        data.setdefault("agent", {}).setdefault("llm", {})["timeout_seconds"] = _env_int(llm_timeout)
    if llm_max_attempts := env.get("XBOT_LLM_MAX_ATTEMPTS"):
        data.setdefault("agent", {}).setdefault("llm", {})["max_attempts"] = _env_int(llm_max_attempts)
    if llm_retry_backoff := env.get("XBOT_LLM_RETRY_BACKOFF_SECONDS"):
        data.setdefault("agent", {}).setdefault("llm", {})["retry_backoff_seconds"] = float(
            llm_retry_backoff
        )
    if llm_enabled := env.get("XBOT_LLM_ENABLED"):
        data.setdefault("agent", {}).setdefault("llm", {})["enabled"] = _env_bool(llm_enabled)
    if agent_mode := env.get("XBOT_AGENT_MODE"):
        data.setdefault("agent", {})["mode"] = agent_mode
    if agent_admin_allowed := env.get("XBOT_AGENT_ADMIN_MODE_ALLOWED"):
        data.setdefault("agent", {})["admin_mode_allowed"] = _env_bool(agent_admin_allowed)
    if agent_allow_shell := env.get("XBOT_AGENT_ALLOW_SHELL"):
        data.setdefault("agent", {})["allow_shell"] = _env_bool(agent_allow_shell)
    if agent_allow_file_write := env.get("XBOT_AGENT_ALLOW_FILE_WRITE"):
        data.setdefault("agent", {})["allow_file_write"] = _env_bool(agent_allow_file_write)
    if agent_max_tool_iterations := env.get("XBOT_AGENT_MAX_TOOL_ITERATIONS"):
        data.setdefault("agent", {})["max_tool_iterations"] = _env_int(agent_max_tool_iterations)
    if agent_auto_delegate := env.get("XBOT_AGENT_AUTO_DELEGATE_CHANNEL_TASKS"):
        data.setdefault("agent", {})["auto_delegate_channel_tasks"] = _env_bool(agent_auto_delegate)
    if max_inline_tool_result := env.get("XBOT_AGENT_MAX_INLINE_TOOL_RESULT_CHARS"):
        data.setdefault("agent", {})["max_inline_tool_result_chars"] = _env_int(max_inline_tool_result)
    if tool_result_artifact_dir := env.get("XBOT_AGENT_TOOL_RESULT_ARTIFACT_DIR"):
        data.setdefault("agent", {})["tool_result_artifact_dir"] = tool_result_artifact_dir
    if agent_schedule_enabled := env.get("XBOT_AGENT_SCHEDULE_ENABLED"):
        data.setdefault("agent", {}).setdefault("schedule", {})["enabled"] = _env_bool(
            agent_schedule_enabled
        )
    if agent_schedule_tick := env.get("XBOT_AGENT_SCHEDULE_TICK_SECONDS"):
        data.setdefault("agent", {}).setdefault("schedule", {})["tick_seconds"] = float(
            agent_schedule_tick
        )
    if agent_schedule_max_due := env.get("XBOT_AGENT_SCHEDULE_MAX_DUE_PER_TICK"):
        data.setdefault("agent", {}).setdefault("schedule", {})["max_due_per_tick"] = _env_int(
            agent_schedule_max_due
        )
    if agent_member_policy_enabled := env.get("XBOT_AGENT_MEMBER_POLICY_ENABLED"):
        data.setdefault("agent", {}).setdefault("member_policy", {})["enabled"] = _env_bool(
            agent_member_policy_enabled
        )
    if agent_member_workspace_roots := env.get("XBOT_AGENT_MEMBER_WORKSPACE_ROOTS"):
        data.setdefault("agent", {}).setdefault("member_policy", {})["workspace_roots"] = _env_list(
            agent_member_workspace_roots
        )
    if agent_member_allow_terminal := env.get("XBOT_AGENT_MEMBER_ALLOW_TERMINAL"):
        data.setdefault("agent", {}).setdefault("member_policy", {})["allow_terminal"] = _env_bool(
            agent_member_allow_terminal
        )
    if agent_member_allow_public_web := env.get("XBOT_AGENT_MEMBER_ALLOW_PUBLIC_WEB"):
        data.setdefault("agent", {}).setdefault("member_policy", {})["allow_public_web"] = _env_bool(
            agent_member_allow_public_web
        )
    if agent_member_block_private_network := env.get("XBOT_AGENT_MEMBER_BLOCK_PRIVATE_NETWORK"):
        data.setdefault("agent", {}).setdefault("member_policy", {})[
            "block_private_network"
        ] = _env_bool(agent_member_block_private_network)
    if wechat869_enabled := env.get("XBOT_WECHAT869_ENABLED"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["enabled"] = _env_bool(
            wechat869_enabled
        )
    if wechat869_host := env.get("XBOT_WECHAT869_HOST"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["host"] = wechat869_host
    if wechat869_port := env.get("XBOT_WECHAT869_PORT"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["port"] = int(wechat869_port)
    if wechat869_admin_key := env.get("XBOT_WECHAT869_ADMIN_KEY"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["admin_key"] = (
            wechat869_admin_key
        )
    if wechat869_token_key := env.get("XBOT_WECHAT869_TOKEN_KEY"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["token_key"] = (
            wechat869_token_key
        )
    if wechat869_ws_url := env.get("XBOT_WECHAT869_WS_URL"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["ws_url"] = wechat869_ws_url
    if wechat869_bot_wxid := env.get("XBOT_WECHAT869_BOT_WXID"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["bot_wxid"] = (
            wechat869_bot_wxid
        )
    if wechat869_bot_nickname := env.get("XBOT_WECHAT869_BOT_NICKNAME"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["bot_nickname"] = (
            wechat869_bot_nickname
        )
    if wechat869_admin_wxids := env.get("XBOT_WECHAT869_ADMIN_WXIDS"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["admin_wxids"] = _env_list(
            wechat869_admin_wxids
        )
    if wechat869_member_wxids := env.get("XBOT_WECHAT869_MEMBER_WXIDS"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["member_wxids"] = _env_list(
            wechat869_member_wxids
        )
    if wechat869_default_profile := env.get("XBOT_WECHAT869_DEFAULT_PROFILE"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["default_profile"] = (
            wechat869_default_profile
        )
    if wechat869_text_only := env.get("XBOT_WECHAT869_TEXT_ONLY"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["text_only"] = _env_bool(
            wechat869_text_only
        )
    if wechat869_media_enabled := env.get("XBOT_WECHAT869_MEDIA_ENABLED"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["media_enabled"] = _env_bool(
            wechat869_media_enabled
        )
    if wechat869_media_dir := env.get("XBOT_WECHAT869_MEDIA_DIR"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["media_dir"] = wechat869_media_dir
    if wechat869_auto_download_images := env.get("XBOT_WECHAT869_AUTO_DOWNLOAD_IMAGES"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["auto_download_images"] = _env_bool(
            wechat869_auto_download_images
        )
    if wechat869_auto_download_files := env.get("XBOT_WECHAT869_AUTO_DOWNLOAD_FILES"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["auto_download_files"] = _env_bool(
            wechat869_auto_download_files
        )
    if wechat869_max_image_bytes := env.get("XBOT_WECHAT869_MAX_IMAGE_BYTES"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["max_image_bytes"] = int(
            wechat869_max_image_bytes
        )
    if wechat869_max_file_bytes := env.get("XBOT_WECHAT869_MAX_FILE_BYTES"):
        data.setdefault("adapters", {}).setdefault("wechat869", {})["max_file_bytes"] = int(
            wechat869_max_file_bytes
        )
    if wechat_ilink_enabled := env.get("XBOT_WECHAT_ILINK_ENABLED"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["enabled"] = _env_bool(
            wechat_ilink_enabled
        )
    if wechat_ilink_base_url := env.get("XBOT_WECHAT_ILINK_BASE_URL"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["base_url"] = (
            wechat_ilink_base_url
        )
    if wechat_ilink_cdn_base_url := env.get("XBOT_WECHAT_ILINK_CDN_BASE_URL"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["cdn_base_url"] = (
            wechat_ilink_cdn_base_url
        )
    if wechat_ilink_token := env.get("XBOT_WECHAT_ILINK_TOKEN"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["token"] = wechat_ilink_token
    if wechat_ilink_cursor := env.get("XBOT_WECHAT_ILINK_CURSOR"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["cursor"] = (
            wechat_ilink_cursor
        )
    if wechat_ilink_poll_interval := env.get("XBOT_WECHAT_ILINK_POLL_INTERVAL_SECONDS"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})[
            "poll_interval_seconds"
        ] = float(wechat_ilink_poll_interval)
    if wechat_ilink_timeout := env.get("XBOT_WECHAT_ILINK_CONNECT_TIMEOUT_SECONDS"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})[
            "connect_timeout_seconds"
        ] = int(wechat_ilink_timeout)
    if wechat_ilink_bot_wxid := env.get("XBOT_WECHAT_ILINK_BOT_WXID"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["bot_wxid"] = (
            wechat_ilink_bot_wxid
        )
    if wechat_ilink_bot_nickname := env.get("XBOT_WECHAT_ILINK_BOT_NICKNAME"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["bot_nickname"] = (
            wechat_ilink_bot_nickname
        )
    if wechat_ilink_media_enabled := env.get("XBOT_WECHAT_ILINK_MEDIA_ENABLED"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["media_enabled"] = _env_bool(
            wechat_ilink_media_enabled
        )
    if wechat_ilink_media_dir := env.get("XBOT_WECHAT_ILINK_MEDIA_DIR"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["media_dir"] = (
            wechat_ilink_media_dir
        )
    if wechat_ilink_auto_download_images := env.get("XBOT_WECHAT_ILINK_AUTO_DOWNLOAD_IMAGES"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["auto_download_images"] = _env_bool(
            wechat_ilink_auto_download_images
        )
    if wechat_ilink_auto_download_files := env.get("XBOT_WECHAT_ILINK_AUTO_DOWNLOAD_FILES"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["auto_download_files"] = _env_bool(
            wechat_ilink_auto_download_files
        )
    if wechat_ilink_max_image_bytes := env.get("XBOT_WECHAT_ILINK_MAX_IMAGE_BYTES"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["max_image_bytes"] = int(
            wechat_ilink_max_image_bytes
        )
    if wechat_ilink_max_file_bytes := env.get("XBOT_WECHAT_ILINK_MAX_FILE_BYTES"):
        data.setdefault("adapters", {}).setdefault("wechat_ilink", {})["max_file_bytes"] = int(
            wechat_ilink_max_file_bytes
        )
    _normalize_agent_config(data)
    if isinstance(data.get("xbot"), dict):
        data.setdefault("agent", {})["timezone"] = data["xbot"].get("timezone", "Asia/Shanghai")
    settings = Settings.model_validate(data)
    settings.config_file = path
    return settings
