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
    assert settings.adapters.wechat869.enabled is False


def test_env_overrides_database_and_redis(monkeypatch):
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/app")
    monkeypatch.setenv("XBOT_ADMIN_DATABASE_URL", "postgresql://postgres:admin@db:5432/postgres")
    monkeypatch.setenv("XBOT_DATABASE_AUTO_BOOTSTRAP", "false")
    monkeypatch.setenv("XBOT_REDIS_URL", "redis://redis:6379/2")
    monkeypatch.setenv("XBOT_LLM_ENABLED", "true")
    monkeypatch.setenv("XBOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("XBOT_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("XBOT_LLM_MODEL", "test-model")
    monkeypatch.setenv("XBOT_AGENT_ADMIN_MODE_ALLOWED", "admin")
    monkeypatch.setenv("XBOT_AGENT_MODE", "admin")
    monkeypatch.setenv("XBOT_AGENT_ALLOW_SHELL", "true")
    monkeypatch.setenv("XBOT_AGENT_WORKSPACE_ROOTS", "C:/tmp;D:/project")
    monkeypatch.setenv("XBOT_AGENT_WORKSPACE_ALLOW_ALL_FILESYSTEM", "true")
    monkeypatch.setenv("XBOT_AGENT_CACHE_TOOL_RESULT_TTL_SECONDS", "90")
    monkeypatch.setenv("XBOT_WECHAT869_ENABLED", "true")
    monkeypatch.setenv("XBOT_WECHAT869_HOST", "wechat.local")
    monkeypatch.setenv("XBOT_WECHAT869_PORT", "8848")
    monkeypatch.setenv("XBOT_WECHAT869_TOKEN_KEY", "token")
    settings = load_settings("configs/xbot.toml")
    assert settings.storage.url == "postgresql+asyncpg://u:p@db:5432/app"
    assert settings.storage.admin_url == "postgresql://postgres:admin@db:5432/postgres"
    assert settings.storage.auto_bootstrap is False
    assert settings.queue.redis_url == "redis://redis:6379/2"
    assert settings.agent.llm.enabled is True
    assert settings.agent.llm.api_key == "test-key"
    assert settings.agent.llm.base_url == "http://llm.local/v1"
    assert settings.agent.llm.model == "test-model"
    assert settings.agent.mode == "admin"
    assert settings.agent.admin_mode_allowed is True
    assert settings.agent.allow_shell is True
    assert settings.agent.workspace.roots == ["C:/tmp", "D:/project"]
    assert settings.agent.workspace.allow_all_filesystem is True
    assert settings.agent.cache.enabled is True
    assert settings.agent.cache.tool_result_ttl_seconds == 90
    assert settings.adapters.wechat869.enabled is True
    assert settings.adapters.wechat869.host == "wechat.local"
    assert settings.adapters.wechat869.port == 8848
    assert settings.adapters.wechat869.token_key == "token"
