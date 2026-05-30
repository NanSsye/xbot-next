from xbot.cli.setup import run_setup


def test_setup_yes_writes_local_ilink_env(tmp_path):
    env_path = tmp_path / ".env"

    run_setup(profile="local", wechat="ilink", env_path=str(env_path), yes=True)

    content = env_path.read_text(encoding="utf-8")
    assert "XBOT_STORAGE_TYPE=sqlite" in content
    assert "XBOT_DATABASE_URL=sqlite+aiosqlite:///data/xbot.db" in content
    assert "XBOT_CONVERSATION_STORE=sqlite" in content
    assert "XBOT_QUEUE_TYPE=memory" in content
    assert "XBOT_WECHAT_ILINK_ENABLED=true" in content
    assert "XBOT_WECHAT869_ENABLED=false" in content


def test_setup_yes_writes_production_both_env(tmp_path):
    env_path = tmp_path / ".env"

    run_setup(profile="production", wechat="both", env_path=str(env_path), yes=True)

    content = env_path.read_text(encoding="utf-8")
    assert "XBOT_STORAGE_TYPE=postgresql" in content
    assert "XBOT_CONVERSATION_STORE=postgresql" in content
    assert "XBOT_QUEUE_TYPE=redis" in content
    assert "XBOT_WECHAT_ILINK_ENABLED=true" in content
    assert "XBOT_WECHAT869_ENABLED=true" in content
