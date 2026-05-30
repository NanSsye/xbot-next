from xbot.app.main import create_app


def test_create_app():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/system/status" in paths
    assert "/api/v1/bot/status" in paths
    assert "/api/v1/adapters" in paths
    assert "/api/v1/adapters/wechat_ilink/login/qrcode" in paths
    assert "/api/v1/adapters/wechat_ilink/login/status" in paths
    assert "/api/v1/agent/tools" in paths
    assert "/api/v1/agent/llm/status" in paths
    assert "/api/v1/agent/tools/{tool_name}/execute" in paths
    assert "/api/v1/agent/policy/validate" in paths
    assert "/api/v1/agent/memory/{target}" in paths
    assert "/api/v1/agent/memory" in paths
    assert "/api/v1/agent/memory/flush" in paths
    assert "/api/v1/agent/wiki" in paths
    assert "/api/v1/agent/wiki/{wiki}/query" in paths
    assert "/api/v1/agent/curator" in paths
    assert "/api/v1/agent/curator/run" in paths
    assert "/api/v1/agent/curator/report" in paths
    assert "/api/v1/agent/curator/report/{report_id}" in paths
    assert "/api/v1/agent/curator/apply" in paths
    assert "/api/v1/agent/curator/{action}/{name}" in paths
    assert "/api/v1/agent/skills/agent-owned" in paths
    assert "/api/v1/agent/memories" in paths
    assert "/api/v1/messages/simulate" in paths
    assert "/api/v1/messages/recent" in paths
    assert "/api/v1/plugins/{name}/enable" in paths
    assert "/api/v1/plugins/{name}/disable" in paths
    assert "/api/v1/skills/{name}/enable" in paths
    assert "/api/v1/skills/{name}/disable" in paths
    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}" in paths
    assert "/api/v1/conversations/{conversation_id}/messages" in paths
    assert "/api/v1/conversations/{conversation_id}/state/{namespace}" in paths
