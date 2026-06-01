from xbot.agent.llm import AnthropicLLMProvider, LLMMessage, create_llm_provider
from xbot.core.config import AgentLLMConfig


def test_create_anthropic_provider() -> None:
    config = AgentLLMConfig(
        enabled=True,
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="test-key",
        model="claude-3-5-sonnet-latest",
    )

    provider = create_llm_provider(config)

    assert isinstance(provider, AnthropicLLMProvider)
    assert provider.status()["provider"] == "anthropic"


def test_anthropic_provider_builds_messages_payload_with_tools() -> None:
    provider = AnthropicLLMProvider(
        AgentLLMConfig(
            enabled=True,
            provider="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key",
            model="claude-3-5-sonnet-latest",
        )
    )

    payload = provider._build_payload(
        [
            LLMMessage(role="system", content="You are xbot."),
            LLMMessage(role="user", content="list files"),
            LLMMessage(
                role="assistant",
                content="I will inspect.",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "filesystem__list_dir", "arguments": '{"path":"."}'},
                    }
                ],
            ),
            LLMMessage(role="tool", tool_call_id="call_1", content='{"entries":[]}'),
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "filesystem__list_dir",
                    "description": "List directory",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ],
    )

    assert payload["system"] == "You are xbot."
    assert payload["messages"][0] == {"role": "user", "content": "list files"}
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["content"][1] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "filesystem__list_dir",
        "input": {"path": "."},
    }
    assert payload["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": '{"entries":[]}'}],
    }
    assert payload["tools"] == [
        {
            "name": "filesystem__list_dir",
            "description": "List directory",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]


def test_anthropic_provider_parses_tool_use_blocks() -> None:
    provider = AnthropicLLMProvider(
        AgentLLMConfig(
            enabled=True,
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet-latest",
        )
    )

    calls = provider._parse_tool_calls(
        [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "toolu_1", "name": "shell__exec", "input": {"command": "pwd"}},
        ]
    )

    assert len(calls) == 1
    assert calls[0].id == "toolu_1"
    assert calls[0].name == "shell__exec"
    assert calls[0].arguments == {"command": "pwd"}
