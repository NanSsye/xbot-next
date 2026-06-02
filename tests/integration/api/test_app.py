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
    assert "/api/v1/agent/tasks" in paths
    assert "/api/v1/agent/tasks/{task_id}" in paths
    assert "/api/v1/agent/tasks/{task_id}/resume" in paths
    assert "/api/v1/agent/events" in paths
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
