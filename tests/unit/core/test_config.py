from xbot.core.config import load_settings


def test_load_default_config(monkeypatch):
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    settings = load_settings("configs/xbot.toml")
    assert settings.xbot.name == "xbot"
    assert settings.storage.type == "postgresql"
    assert settings.storage.url == "postgresql+asyncpg://xbot:xbot@192.168.6.19:5433/xbot"
    assert settings.storage.auto_bootstrap is True
    assert settings.storage.run_migrations_on_startup is True
    assert settings.queue.redis_url == "redis://192.168.6.41:6379/15"
    assert settings.storage.persist_runtime_events is True
    assert settings.queue.dead_letter_queue == "xbot:dead_letters"
    assert settings.queue.retry.max_attempts == 3
    assert settings.conversation.enabled is True
    assert settings.conversation.context.recent_messages == 0
    assert settings.agent.mode == "developer"
    assert settings.agent.workspace.roots == ["."]
    assert settings.agent.llm.enabled is False
    assert settings.agent.llm.provider == "openai_compatible"
    assert settings.agent.memory.short_term_enabled is True
    assert settings.agent.memory.short_term_recent_turns == 0
    assert settings.agent.memory.short_term_max_tokens == 128000
    assert settings.agent.memory.short_term_summary_max_tokens == 32000
    assert settings.agent.memory.short_term_max_chars == 0
    assert settings.agent.memory.short_term_summary_max_chars == 0
    assert settings.agent.wiki.enabled is True
    assert settings.agent.wiki.directory == "data/agent/wiki"
    assert settings.agent.wiki.default_wiki == "xbot"
    assert settings.agent.wiki.rag_enabled is False
    assert settings.agent.mcp.enabled is True
    assert settings.agent.toolsets.group == [
        "core",
        "memory",
        "wiki",
        "filesystem",
        "skill",
        "wechat",
        "mcp",
        "environment",
        "task",
        "schedule",
        "plugin",
    ]
    assert settings.agent.schedule.enabled is True
    assert settings.agent.schedule.tick_seconds == 30.0
    assert settings.adapters.wechat869.enabled is False


def test_env_overrides_database_and_redis(monkeypatch):
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/app")
    monkeypatch.setenv("XBOT_STORAGE_TYPE", "postgresql")
    monkeypatch.setenv("XBOT_ADMIN_DATABASE_URL", "postgresql://postgres:admin@db:5432/postgres")
    monkeypatch.setenv("XBOT_DATABASE_AUTO_BOOTSTRAP", "false")
    monkeypatch.setenv("XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP", "false")
    monkeypatch.setenv("XBOT_REDIS_URL", "redis://redis:6379/2")
    monkeypatch.setenv("XBOT_QUEUE_TYPE", "redis")
    monkeypatch.setenv("XBOT_CONVERSATION_STORE", "postgresql")
    monkeypatch.setenv("XBOT_LLM_ENABLED", "true")
    monkeypatch.setenv("XBOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("XBOT_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("XBOT_LLM_MODEL", "test-model")
    monkeypatch.setenv("XBOT_LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("XBOT_LLM_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("XBOT_LLM_RETRY_BACKOFF_SECONDS", "0.5")
    monkeypatch.setenv("XBOT_AGENT_ADMIN_MODE_ALLOWED", "admin")
    monkeypatch.setenv("XBOT_AGENT_MODE", "admin")
    monkeypatch.setenv("XBOT_AGENT_ALLOW_SHELL", "true")
    monkeypatch.setenv("XBOT_AGENT_WORKSPACE_ROOTS", "C:/tmp;D:/project")
    monkeypatch.setenv("XBOT_AGENT_WORKSPACE_ALLOW_ALL_FILESYSTEM", "true")
    monkeypatch.setenv("XBOT_AGENT_CACHE_TOOL_RESULT_TTL_SECONDS", "90")
    monkeypatch.setenv("XBOT_AGENT_SCHEDULE_ENABLED", "false")
    monkeypatch.setenv("XBOT_AGENT_SCHEDULE_TICK_SECONDS", "15")
    monkeypatch.setenv("XBOT_AGENT_SCHEDULE_MAX_DUE_PER_TICK", "3")
    monkeypatch.setenv("XBOT_AGENT_WIKI_DIRECTORY", "data/custom-wiki")
    monkeypatch.setenv("XBOT_AGENT_WIKI_DEFAULT", "project")
    monkeypatch.setenv("XBOT_AGENT_WIKI_QUERY_MAX_CHARS", "4096")
    monkeypatch.setenv("XBOT_AGENT_TOOLSETS_GROUP", "core,skill")
    monkeypatch.setenv("XBOT_AGENT_MCP_ENABLED", "false")
    monkeypatch.setenv("XBOT_WECHAT869_ENABLED", "true")
    monkeypatch.setenv("XBOT_WECHAT869_HOST", "wechat.local")
    monkeypatch.setenv("XBOT_WECHAT869_PORT", "8848")
    monkeypatch.setenv("XBOT_WECHAT869_TOKEN_KEY", "token")
    monkeypatch.setenv("XBOT_WECHAT869_TEXT_ONLY", "false")
    monkeypatch.setenv("XBOT_WECHAT869_MEDIA_DIR", "data/custom-media")
    monkeypatch.setenv("XBOT_WECHAT869_MAX_IMAGE_BYTES", "123")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_ENABLED", "true")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_BASE_URL", "https://ilink.local")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_TOKEN", "ilink-token")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_CURSOR", "cursor-1")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_POLL_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_CONNECT_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_CDN_BASE_URL", "https://cdn.ilink.local/c2c")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_MEDIA_DIR", "data/ilink-media")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_MAX_IMAGE_BYTES", "456")
    monkeypatch.setenv("XBOT_WECHAT_ILINK_MAX_FILE_BYTES", "789")
    settings = load_settings("configs/xbot.toml")
    assert settings.storage.url == "postgresql+asyncpg://u:p@db:5432/app"
    assert settings.storage.type == "postgresql"
    assert settings.storage.admin_url == "postgresql://postgres:admin@db:5432/postgres"
    assert settings.storage.auto_bootstrap is False
    assert settings.storage.run_migrations_on_startup is False
    assert settings.queue.redis_url == "redis://redis:6379/2"
    assert settings.queue.type == "redis"
    assert settings.conversation.store == "postgresql"
    assert settings.agent.llm.enabled is True
    assert settings.agent.llm.api_key == "test-key"
    assert settings.agent.llm.base_url == "http://llm.local/v1"
    assert settings.agent.llm.model == "test-model"
    assert settings.agent.llm.timeout_seconds == 45
    assert settings.agent.llm.max_attempts == 4
    assert settings.agent.llm.retry_backoff_seconds == 0.5
    assert settings.agent.mode == "admin"
    assert settings.agent.admin_mode_allowed is True
    assert settings.agent.allow_shell is True
    assert settings.agent.workspace.roots == ["C:/tmp", "D:/project"]
    assert settings.agent.workspace.allow_all_filesystem is True
    assert settings.agent.cache.enabled is True
    assert settings.agent.cache.tool_result_ttl_seconds == 90
    assert settings.agent.schedule.enabled is False
    assert settings.agent.schedule.tick_seconds == 15
    assert settings.agent.schedule.max_due_per_tick == 3
    assert settings.agent.wiki.directory == "data/custom-wiki"
    assert settings.agent.wiki.default_wiki == "project"
    assert settings.agent.wiki.query_max_chars == 4096
    assert settings.agent.toolsets.group == ["core", "skill"]
    assert settings.agent.mcp.enabled is False
    assert settings.adapters.wechat869.enabled is True
    assert settings.adapters.wechat869.host == "wechat.local"
    assert settings.adapters.wechat869.port == 8848
    assert settings.adapters.wechat869.token_key == "token"
    assert settings.adapters.wechat869.text_only is False
    assert settings.adapters.wechat869.media_dir == "data/custom-media"
    assert settings.adapters.wechat869.max_image_bytes == 123
    assert settings.adapters.wechat_ilink.enabled is True
    assert settings.adapters.wechat_ilink.base_url == "https://ilink.local"
    assert settings.adapters.wechat_ilink.token == "ilink-token"
    assert settings.adapters.wechat_ilink.cursor == "cursor-1"
    assert settings.adapters.wechat_ilink.poll_interval_seconds == 2.5
    assert settings.adapters.wechat_ilink.connect_timeout_seconds == 30
    assert settings.adapters.wechat_ilink.cdn_base_url == "https://cdn.ilink.local/c2c"
    assert settings.adapters.wechat_ilink.media_dir == "data/ilink-media"
    assert settings.adapters.wechat_ilink.max_image_bytes == 456
    assert settings.adapters.wechat_ilink.max_file_bytes == 789


def test_env_overrides_local_storage_and_memory_queue(monkeypatch):
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_STORAGE_TYPE", "sqlite")
    monkeypatch.setenv("XBOT_DATABASE_URL", "sqlite+aiosqlite:///data/xbot.db")
    monkeypatch.setenv("XBOT_QUEUE_TYPE", "memory")
    monkeypatch.setenv("XBOT_CONVERSATION_STORE", "sqlite")

    settings = load_settings("configs/xbot.toml")

    assert settings.storage.type == "sqlite"
    assert settings.storage.url == "sqlite+aiosqlite:///data/xbot.db"
    assert settings.queue.type == "memory"
    assert settings.conversation.store == "sqlite"
