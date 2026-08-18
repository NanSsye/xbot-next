import pytest
from pydantic import ValidationError

from xbot.core.config import AgentLLMConfig, load_settings


def test_load_default_config(monkeypatch):
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    settings = load_settings("configs/xbot.toml")
    assert settings.xbot.name == "xbot"
    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 8548
    assert settings.storage.type == "postgresql"
    assert settings.storage.url == "postgresql+asyncpg://xbot:xbot@postgres:5432/xbot"
    assert settings.storage.auto_bootstrap is True
    assert settings.storage.run_migrations_on_startup is True
    assert settings.queue.redis_url == "redis://redis:6379/15"
    assert settings.storage.persist_runtime_events is True
    assert settings.queue.dead_letter_queue == "xbot:dead_letters"
    assert settings.api.auth_enabled is False
    assert settings.api.token == ""
    assert settings.api.cors_origins == []
    assert settings.queue.retry.max_attempts == 3
    assert settings.conversation.enabled is True
    assert settings.conversation.context.recent_messages == 0
    assert settings.agent.mode == "developer"
    assert settings.agent.llm.enabled is False
    assert settings.agent.llm.provider == "openai_compatible"
    assert settings.agent.llm.enabled_models == [settings.agent.llm.model]
    assert settings.agent.max_inline_tool_result_chars == 20000
    assert settings.agent.tool_result_artifact_dir == "data/artifacts/agent_tool_results"
    assert settings.agent.mcp.enabled is True
    assert settings.agent.schedule.enabled is True
    assert settings.agent.schedule.tick_seconds == 30.0
    assert settings.adapters.wechat869.enabled is False
    assert settings.adapters.qq.enabled is False
    assert settings.adapters.qq.intents == 1 << 25
    assert settings.adapters.qq.default_profile == "guest"
    assert settings.adapters.telegram.enabled is False
    assert settings.adapters.telegram.bot_token == ""


def test_env_overrides_database_and_redis(monkeypatch):
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("XBOT_SERVER_PORT", "18080")
    monkeypatch.setenv("XBOT_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/app")
    monkeypatch.setenv("XBOT_STORAGE_TYPE", "postgresql")
    monkeypatch.setenv("XBOT_ADMIN_DATABASE_URL", "postgresql://postgres:admin@db:5432/postgres")
    monkeypatch.setenv("XBOT_DATABASE_AUTO_BOOTSTRAP", "false")
    monkeypatch.setenv("XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP", "false")
    monkeypatch.setenv("XBOT_REDIS_URL", "redis://redis:6379/2")
    monkeypatch.setenv("XBOT_QUEUE_TYPE", "redis")
    monkeypatch.setenv("XBOT_CONVERSATION_STORE", "postgresql")
    monkeypatch.setenv("XBOT_API_AUTH_ENABLED", "true")
    monkeypatch.setenv("XBOT_API_TOKEN", "secret-token")
    monkeypatch.setenv("XBOT_API_CORS_ORIGINS", "https://console.example.com,http://127.0.0.1:5173")
    monkeypatch.setenv("XBOT_LLM_ENABLED", "true")
    monkeypatch.setenv("XBOT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("XBOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("XBOT_LLM_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setenv("XBOT_LLM_MODEL", "claude-3-5-sonnet-latest")
    monkeypatch.setenv("XBOT_LLM_ENABLED_MODELS", "claude-3-5-sonnet-latest,claude-3-haiku")
    monkeypatch.setenv("XBOT_LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("XBOT_LLM_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("XBOT_LLM_RETRY_BACKOFF_SECONDS", "0.5")
    monkeypatch.setenv("XBOT_AGENT_ADMIN_MODE_ALLOWED", "admin")
    monkeypatch.setenv("XBOT_AGENT_MODE", "admin")
    monkeypatch.setenv("XBOT_AGENT_ALLOW_SHELL", "true")
    monkeypatch.setenv("XBOT_AGENT_MAX_TOOL_ITERATIONS", "12")
    monkeypatch.setenv("XBOT_AGENT_AUTO_DELEGATE_CHANNEL_TASKS", "false")
    monkeypatch.setenv("XBOT_AGENT_MAX_INLINE_TOOL_RESULT_CHARS", "12345")
    monkeypatch.setenv("XBOT_AGENT_TOOL_RESULT_ARTIFACT_DIR", "data/custom-tool-results")
    monkeypatch.setenv("XBOT_AGENT_SCHEDULE_ENABLED", "false")
    monkeypatch.setenv("XBOT_AGENT_SCHEDULE_TICK_SECONDS", "15")
    monkeypatch.setenv("XBOT_AGENT_SCHEDULE_MAX_DUE_PER_TICK", "3")
    monkeypatch.setenv("XBOT_AGENT_MEMBER_POLICY_ENABLED", "true")
    monkeypatch.setenv("XBOT_AGENT_MEMBER_WORKSPACE_ROOTS", "workspace,.agent-workspace")
    monkeypatch.setenv("XBOT_AGENT_MEMBER_ALLOW_TERMINAL", "false")
    monkeypatch.setenv("XBOT_AGENT_MEMBER_ALLOW_PUBLIC_WEB", "true")
    monkeypatch.setenv("XBOT_AGENT_MEMBER_BLOCK_PRIVATE_NETWORK", "true")
    monkeypatch.setenv("XBOT_WECHAT869_ENABLED", "true")
    monkeypatch.setenv("XBOT_WECHAT869_HOST", "wechat.local")
    monkeypatch.setenv("XBOT_WECHAT869_PORT", "8848")
    monkeypatch.setenv("XBOT_WECHAT869_TOKEN_KEY", "token")
    monkeypatch.setenv("XBOT_WECHAT869_ADMIN_WXIDS", "wxid_admin, xianan96928")
    monkeypatch.setenv("XBOT_WECHAT869_MEMBER_WXIDS", "wxid_member")
    monkeypatch.setenv("XBOT_WECHAT869_DEFAULT_PROFILE", "guest")
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
    monkeypatch.setenv("XBOT_QQ_ENABLED", "true")
    monkeypatch.setenv("XBOT_QQ_APP_ID", "qq-app")
    monkeypatch.setenv("XBOT_QQ_CLIENT_SECRET", "qq-secret")
    monkeypatch.setenv("XBOT_QQ_INTENTS", "33554432")
    monkeypatch.setenv("XBOT_QQ_GATEWAY_URL", "wss://qq.local/websocket")
    monkeypatch.setenv("XBOT_QQ_RECONNECT_SECONDS", "2.5")
    monkeypatch.setenv("XBOT_QQ_MAX_REPLY_CHARS", "1200")
    monkeypatch.setenv("XBOT_QQ_ADMIN_OPENIDS", "admin-1,admin-2")
    monkeypatch.setenv("XBOT_QQ_MEMBER_OPENIDS", "member-1")
    monkeypatch.setenv("XBOT_QQ_DEFAULT_PROFILE", "member")
    monkeypatch.setenv("XBOT_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("XBOT_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("XBOT_TELEGRAM_POLLING_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("XBOT_TELEGRAM_MEDIA_MAX_BYTES", "123456")
    monkeypatch.setenv("XBOT_TELEGRAM_ADMIN_USER_IDS", "42,43")
    monkeypatch.setenv("XBOT_TELEGRAM_MEMBER_USER_IDS", "44")
    monkeypatch.setenv("XBOT_TELEGRAM_DEFAULT_PROFILE", "member")
    settings = load_settings("configs/xbot.toml")
    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 18080
    assert settings.storage.url == "postgresql+asyncpg://u:p@db:5432/app"
    assert settings.storage.type == "postgresql"
    assert settings.storage.admin_url == "postgresql://postgres:admin@db:5432/postgres"
    assert settings.storage.auto_bootstrap is False
    assert settings.storage.run_migrations_on_startup is False
    assert settings.queue.redis_url == "redis://redis:6379/2"
    assert settings.queue.type == "redis"
    assert settings.conversation.store == "postgresql"
    assert settings.api.auth_enabled is True
    assert settings.api.token == "secret-token"
    assert settings.api.cors_origins == ["https://console.example.com", "http://127.0.0.1:5173"]
    assert settings.agent.llm.enabled is True
    assert settings.agent.llm.provider == "anthropic"
    assert settings.agent.llm.api_key == "test-key"
    assert settings.agent.llm.base_url == "https://api.anthropic.com"
    assert settings.agent.llm.model == "claude-3-5-sonnet-latest"
    assert settings.agent.llm.enabled_models == ["claude-3-5-sonnet-latest", "claude-3-haiku"]
    assert settings.agent.llm.timeout_seconds == 45
    assert settings.agent.llm.max_attempts == 4
    assert settings.agent.llm.retry_backoff_seconds == 0.5
    assert settings.agent.mode == "admin"
    assert settings.agent.admin_mode_allowed is True
    assert settings.agent.allow_shell is True
    assert settings.agent.max_tool_iterations == 12
    assert settings.agent.auto_delegate_channel_tasks is False
    assert settings.agent.max_inline_tool_result_chars == 12345
    assert settings.agent.tool_result_artifact_dir == "data/custom-tool-results"
    assert settings.agent.schedule.enabled is False
    assert settings.agent.schedule.tick_seconds == 15
    assert settings.agent.schedule.max_due_per_tick == 3
    assert settings.agent.member_policy.workspace_roots == ["workspace", ".agent-workspace"]
    assert settings.agent.member_policy.allow_terminal is False
    assert settings.agent.member_policy.allow_public_web is True
    assert settings.agent.member_policy.block_private_network is True
    assert settings.agent.mcp.enabled is True
    assert settings.adapters.wechat869.enabled is True
    assert settings.adapters.wechat869.host == "wechat.local"
    assert settings.adapters.wechat869.port == 8848
    assert settings.adapters.wechat869.token_key == "token"
    assert settings.adapters.wechat869.admin_wxids == ["wxid_admin", "xianan96928"]
    assert settings.adapters.wechat869.member_wxids == ["wxid_member"]
    assert settings.adapters.wechat869.default_profile == "guest"
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
    assert settings.adapters.qq.enabled is True
    assert settings.adapters.qq.app_id == "qq-app"
    assert settings.adapters.qq.client_secret == "qq-secret"
    assert settings.adapters.qq.intents == 1 << 25
    assert settings.adapters.qq.gateway_url == "wss://qq.local/websocket"
    assert settings.adapters.qq.reconnect_seconds == 2.5
    assert settings.adapters.qq.max_reply_chars == 1200
    assert settings.adapters.qq.admin_openids == ["admin-1", "admin-2"]
    assert settings.adapters.qq.member_openids == ["member-1"]
    assert settings.adapters.qq.default_profile == "member"
    assert settings.adapters.telegram.enabled is True
    assert settings.adapters.telegram.bot_token == "telegram-secret"
    assert settings.adapters.telegram.polling_timeout_seconds == 25
    assert settings.adapters.telegram.media_max_bytes == 123456
    assert settings.adapters.telegram.admin_user_ids == ["42", "43"]
    assert settings.adapters.telegram.member_user_ids == ["44"]
    assert settings.adapters.telegram.default_profile == "member"


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


def test_llm_model_pool_normalizes_duplicates_and_requires_default_membership():
    config = AgentLLMConfig(model="model-a", enabled_models=[" model-a ", "model-b", "model-b"])
    assert config.enabled_models == ["model-a", "model-b"]

    with pytest.raises(ValidationError, match="全局默认模型必须属于已启用模型"):
        AgentLLMConfig(model="model-a", enabled_models=["model-b"])
