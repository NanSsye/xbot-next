import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from xbot.agent.hermes_runtime import hermes_source_dir
from xbot.agent.runtime import AgentRuntime
from xbot.core.config import AgentConfig


@pytest.fixture
def local_model() -> Iterator[tuple[str, list[dict]]]:
    requests = []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path != "/v1/chat/completions":
                self.send_response(404)
                self.end_headers()
                return
            requests.append(body)
            if any(message["content"] == "拒绝请求" for message in body["messages"] if message["role"] == "user"):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"stub-private-error","type":"authentication_error"}}')
                return

            streaming = body.get("stream")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.end_headers()
            base = {"id": "local-test", "created": 0, "model": body["model"]}
            if streaming:
                for delta, reason in [
                    ({"role": "assistant", "content": "本地"}, None),
                    ({"content": "回复"}, None),
                    ({}, "stop"),
                ]:
                    chunk = dict(base, object="chat.completion.chunk", choices=[
                        {"index": 0, "delta": delta, "finish_reason": reason},
                    ])
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(json.dumps(dict(base, object="chat.completion", choices=[
                    {"index": 0, "message": {"role": "assistant", "content": "本地回复"}, "finish_reason": "stop"},
                ])).encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Model) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", requests
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.anyio
async def test_pinned_hermes_streams_and_restores_isolated_sessions(monkeypatch, tmp_path, local_model):
    base_url, requests = local_model
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "data" / "hermes"))
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "local-test")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    assert hermes_source_dir().name == "v0.23.4"
    config = AgentConfig(llm={
        "enabled": True, "base_url": base_url, "api_key": "local-test",
        "model": "gpt-4.1-mini", "context_window_tokens": 128_000,
    })
    runtime = AgentRuntime(config, None, None)
    events = []
    runtime.subscribe_events(events.append)
    first = "terminal:control-ui:" + "a" * 32
    second = "terminal:control-ui:" + "b" * 32
    for source, text in [(first, "第一轮"), (first, "第二轮"), (second, "独立轮")]:
        context = {"persona_prompt": "只属于会话甲的人设"} if source == first else None
        result = await runtime.run_task(text, source, channel_context=context)
        assert (result.status, result.output) == ("completed", "本地回复")
        assert any(event.task_id == result.task_id and event.type == "llm.delta" for event in events)
    assert any(event.type == "hermes.resumed" for event in events)
    streamed = [body["messages"] for body in requests if body.get("stream")]
    prompts = [[message["content"] for message in messages if message["role"] == "user"] for messages in streamed]
    followup = prompts.index(["第一轮", "第二轮"])
    isolated = prompts.index(["独立轮"])
    assert "只属于会话甲的人设" in json.dumps(streamed[followup], ensure_ascii=False)
    assert "只属于会话甲的人设" not in json.dumps(streamed[isolated], ensure_ascii=False)

    result = await runtime.run_task("拒绝请求", second)
    assert result.status == "failed"
    assert "stub-private-error" not in result.output
