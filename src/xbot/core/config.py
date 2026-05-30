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
    port: int = 8080


class StorageConfig(BaseModel):
    type: Literal["postgresql"] = "postgresql"
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
    store: Literal["postgresql"] = "postgresql"
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
    curator_enabled: bool = True
    curator_interval_turns: int = 20
    curator_stale_after_days: int = 30
    curator_archive_after_days: int = 90


class AgentWorkspaceConfig(BaseModel):
    allow_all_filesystem: bool = False
    roots: list[str] = Field(default_factory=lambda: ["."])
    deny: list[str] = Field(default_factory=list)
    allow_outside_workspace: bool = False


class AgentApprovalConfig(BaseModel):
    dangerous_tools: bool = True
    outside_workspace: bool = True
    delete_files: bool = True
    shell_exec: bool = False
    database_write: bool = True


class AgentMemoryRedactionConfig(BaseModel):
    enabled: bool = True
    patterns: list[str] = Field(
        default_factory=lambda: ["password", "token", "secret", "api_key", "private_key"]
    )


class AgentMemoryConfig(BaseModel):
    enabled: bool = True
    store: Literal["postgresql"] = "postgresql"
    directory: str = "data/agent/memories"
    memory_char_limit: int = 2200
    user_char_limit: int = 1375
    review_enabled: bool = True
    review_interval: int = 10
    flush_min_turns: int = 6
    short_term_enabled: bool = True
    short_term_recent_turns: int = 0
    short_term_max_tokens: int = 128000
    short_term_summary_max_tokens: int = 32000
    short_term_max_chars: int = 0
    short_term_summary_max_chars: int = 0
    auto_compress: bool = True
    max_working_events: int = 50
    max_tool_output_chars: int = 12000
    semantic_memory: bool = True
    vector_search: bool = False
    retention_days: int = 180
    redaction: AgentMemoryRedactionConfig = Field(default_factory=AgentMemoryRedactionConfig)


class AgentWikiConfig(BaseModel):
    enabled: bool = True
    directory: str = "data/agent/wiki"
    default_wiki: str = "xbot"
    query_max_chars: int = 12000
    rag_enabled: bool = False
    vector_index: bool = False


class AgentLLMConfig(BaseModel):
    enabled: bool = False
    provider: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str = "gpt-4.1-mini"
    context_window_tokens: int | None = None
    timeout_seconds: int = 60
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


class AgentCacheConfig(BaseModel):
    enabled: bool = True
    tool_result_ttl_seconds: int = 30
    static_prompt: bool = True
    tool_results: bool = True
    skills: bool = True


class AgentToolsetConfig(BaseModel):
    api: list[str] = Field(
        default_factory=lambda: [
            "core",
            "memory",
            "wiki",
            "filesystem",
            "filesystem_write",
            "filesystem_dangerous",
            "skill",
            "shell",
            "mcp",
            "environment",
            "task",
            "browser",
            "database",
            "git",
            "plugin",
        ]
    )
    private: list[str] = Field(
        default_factory=lambda: ["core", "memory", "wiki", "filesystem", "skill", "wechat", "mcp", "environment", "task", "plugin"]
    )
    group: list[str] = Field(
        default_factory=lambda: ["core", "memory", "wiki", "filesystem", "skill", "wechat", "mcp", "environment", "task", "plugin"]
    )
    terminal: list[str] = Field(
        default_factory=lambda: [
            "core",
            "memory",
            "wiki",
            "filesystem",
            "filesystem_write",
            "skill",
            "shell",
            "mcp",
            "environment",
            "task",
            "browser",
            "database",
            "git",
            "plugin",
        ]
    )
    admin: list[str] = Field(
        default_factory=lambda: [
            "core",
            "memory",
            "wiki",
            "filesystem",
            "filesystem_write",
            "filesystem_dangerous",
            "skill",
            "shell",
            "mcp",
            "environment",
            "task",
            "browser",
            "database",
            "git",
            "plugin",
        ]
    )


class AgentConfig(BaseModel):
    enabled: bool = True
    mode: Literal["safe", "developer", "admin"] = "developer"
    admin_mode_allowed: bool = False
    timezone: str = "Asia/Shanghai"
    workspace_root: str = "."
    allow_shell: bool = False
    allow_file_write: bool = True
    max_tool_iterations: int = 0
    workspace: AgentWorkspaceConfig = Field(default_factory=AgentWorkspaceConfig)
    approval: AgentApprovalConfig = Field(default_factory=AgentApprovalConfig)
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    wiki: AgentWikiConfig = Field(default_factory=AgentWikiConfig)
    llm: AgentLLMConfig = Field(default_factory=AgentLLMConfig)
    mcp: AgentMCPConfig = Field(default_factory=AgentMCPConfig)
    cache: AgentCacheConfig = Field(default_factory=AgentCacheConfig)
    toolsets: AgentToolsetConfig = Field(default_factory=AgentToolsetConfig)


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
    if database_url := env.get("XBOT_DATABASE_URL"):
        data.setdefault("storage", {})["url"] = database_url
    if admin_database_url := env.get("XBOT_ADMIN_DATABASE_URL"):
        data.setdefault("storage", {})["admin_url"] = admin_database_url
    if auto_bootstrap := env.get("XBOT_DATABASE_AUTO_BOOTSTRAP"):
        data.setdefault("storage", {})["auto_bootstrap"] = _env_bool(auto_bootstrap)
    if run_migrations := env.get("XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP"):
        data.setdefault("storage", {})["run_migrations_on_startup"] = _env_bool(run_migrations)
    if redis_url := env.get("XBOT_REDIS_URL"):
        data.setdefault("queue", {})["redis_url"] = redis_url
    if llm_api_key := env.get("XBOT_LLM_API_KEY"):
        data.setdefault("agent", {}).setdefault("llm", {})["api_key"] = llm_api_key
    if llm_base_url := env.get("XBOT_LLM_BASE_URL"):
        data.setdefault("agent", {}).setdefault("llm", {})["base_url"] = llm_base_url
    if llm_model := env.get("XBOT_LLM_MODEL"):
        data.setdefault("agent", {}).setdefault("llm", {})["model"] = llm_model
    if llm_context_window := env.get("XBOT_LLM_CONTEXT_WINDOW_TOKENS"):
        data.setdefault("agent", {}).setdefault("llm", {})["context_window_tokens"] = _env_int(llm_context_window)
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
    if agent_workspace_root := env.get("XBOT_AGENT_WORKSPACE_ROOT"):
        data.setdefault("agent", {})["workspace_root"] = agent_workspace_root
    if agent_workspace_allow_all := env.get("XBOT_AGENT_WORKSPACE_ALLOW_ALL_FILESYSTEM"):
        data.setdefault("agent", {}).setdefault("workspace", {})["allow_all_filesystem"] = _env_bool(
            agent_workspace_allow_all
        )
    if agent_workspace_allow_outside := env.get("XBOT_AGENT_WORKSPACE_ALLOW_OUTSIDE"):
        data.setdefault("agent", {}).setdefault("workspace", {})["allow_outside_workspace"] = _env_bool(
            agent_workspace_allow_outside
        )
    if agent_workspace_roots := env.get("XBOT_AGENT_WORKSPACE_ROOTS"):
        data.setdefault("agent", {}).setdefault("workspace", {})["roots"] = [
            item.strip() for item in agent_workspace_roots.split(";") if item.strip()
        ]
    if agent_cache_enabled := env.get("XBOT_AGENT_CACHE_ENABLED"):
        data.setdefault("agent", {}).setdefault("cache", {})["enabled"] = _env_bool(
            agent_cache_enabled
        )
    if agent_cache_ttl := env.get("XBOT_AGENT_CACHE_TOOL_RESULT_TTL_SECONDS"):
        data.setdefault("agent", {}).setdefault("cache", {})["tool_result_ttl_seconds"] = int(
            agent_cache_ttl
        )
    if agent_cache_static_prompt := env.get("XBOT_AGENT_CACHE_STATIC_PROMPT"):
        data.setdefault("agent", {}).setdefault("cache", {})["static_prompt"] = _env_bool(
            agent_cache_static_prompt
        )
    if agent_cache_tool_results := env.get("XBOT_AGENT_CACHE_TOOL_RESULTS"):
        data.setdefault("agent", {}).setdefault("cache", {})["tool_results"] = _env_bool(
            agent_cache_tool_results
        )
    if agent_cache_skills := env.get("XBOT_AGENT_CACHE_SKILLS"):
        data.setdefault("agent", {}).setdefault("cache", {})["skills"] = _env_bool(
            agent_cache_skills
        )
    if agent_wiki_enabled := env.get("XBOT_AGENT_WIKI_ENABLED"):
        data.setdefault("agent", {}).setdefault("wiki", {})["enabled"] = _env_bool(agent_wiki_enabled)
    if agent_wiki_directory := env.get("XBOT_AGENT_WIKI_DIRECTORY"):
        data.setdefault("agent", {}).setdefault("wiki", {})["directory"] = agent_wiki_directory
    if agent_wiki_default := env.get("XBOT_AGENT_WIKI_DEFAULT"):
        data.setdefault("agent", {}).setdefault("wiki", {})["default_wiki"] = agent_wiki_default
    if agent_wiki_query_max_chars := env.get("XBOT_AGENT_WIKI_QUERY_MAX_CHARS"):
        data.setdefault("agent", {}).setdefault("wiki", {})["query_max_chars"] = _env_int(
            agent_wiki_query_max_chars
        )
    if agent_toolsets_api := env.get("XBOT_AGENT_TOOLSETS_API"):
        data.setdefault("agent", {}).setdefault("toolsets", {})["api"] = _env_list(
            agent_toolsets_api
        )
    if agent_toolsets_private := env.get("XBOT_AGENT_TOOLSETS_PRIVATE"):
        data.setdefault("agent", {}).setdefault("toolsets", {})["private"] = _env_list(
            agent_toolsets_private
        )
    if agent_toolsets_group := env.get("XBOT_AGENT_TOOLSETS_GROUP"):
        data.setdefault("agent", {}).setdefault("toolsets", {})["group"] = _env_list(
            agent_toolsets_group
        )
    if agent_toolsets_terminal := env.get("XBOT_AGENT_TOOLSETS_TERMINAL"):
        data.setdefault("agent", {}).setdefault("toolsets", {})["terminal"] = _env_list(
            agent_toolsets_terminal
        )
    if agent_toolsets_admin := env.get("XBOT_AGENT_TOOLSETS_ADMIN"):
        data.setdefault("agent", {}).setdefault("toolsets", {})["admin"] = _env_list(
            agent_toolsets_admin
        )
    if agent_mcp_enabled := env.get("XBOT_AGENT_MCP_ENABLED"):
        data.setdefault("agent", {}).setdefault("mcp", {})["enabled"] = _env_bool(
            agent_mcp_enabled
        )
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
