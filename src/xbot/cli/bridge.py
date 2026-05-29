from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import anyio

from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.runtime import AgentRuntimeEvent
from xbot.cli.chat import build_terminal_agent_input
from xbot.core.config import Settings, load_settings
from xbot.core.logging import configure_terminal_logging
from xbot.runtime.context import AppContext, build_context
from xbot.storage.bootstrap import ensure_storage_ready


@dataclass(slots=True)
class TerminalBridgeOptions:
    session_id: str
    cwd: Path


class TerminalBridgeSession:
    def __init__(self, ctx: AppContext, options: TerminalBridgeOptions) -> None:
        self.ctx = ctx
        self.options = options
        self.source = f"terminal:bridge:{options.session_id}"
        self._background_unsubscribe = None

    async def start(self) -> None:
        if self.ctx.settings.plugins.auto_load:
            await self.ctx.plugins.load_all()
        if self.ctx.settings.skills.auto_load:
            await self.ctx.skills.load_all()
        if self.ctx.settings.agent.enabled:
            await self.ctx.agent.start()
        self._background_unsubscribe = self.ctx.agent.background.subscribe(self._on_background_task)
        await self.emit(
            "ready",
            {
                "session_id": self.options.session_id,
                "cwd": str(self.options.cwd),
                "source": self.source,
                "llm": self.ctx.agent.llm_status(),
                "tools": len(self.ctx.agent.visible_tools(source=self.source)),
                "plugins": len([item for item in self.ctx.plugins.list_plugins() if item.get("enabled")]),
                "skills": len([item for item in self.ctx.skills.list_skills() if item.get("enabled")]),
            },
        )

    async def stop(self) -> None:
        if self._background_unsubscribe:
            self._background_unsubscribe()
            self._background_unsubscribe = None
        await self.ctx.agent.stop()
        await self.ctx.message_queue.close()
        await self.ctx.storage.close()

    async def run(self) -> None:
        while True:
            line = await anyio.to_thread.run_sync(sys.stdin.readline)
            if not line:
                return
            try:
                payload = json.loads(line)
            except ValueError as exc:
                await self.emit("error", {"error": f"invalid json: {exc}"})
                continue
            if payload.get("type") in {"exit", "quit"}:
                await self.emit("bye", {})
                return
            if payload.get("type") != "message":
                await self.emit("error", {"error": "unsupported message type"})
                continue
            await self.run_turn(str(payload.get("content") or ""))

    async def run_turn(self, content: str) -> None:
        event_queue: asyncio.Queue[AgentRuntimeEvent] = asyncio.Queue()

        async def on_event(event: AgentRuntimeEvent) -> None:
            await event_queue.put(event)

        unsubscribe = self.ctx.agent.subscribe_events(on_event)
        task = asyncio.create_task(
            self.ctx.agent.run_task(
                build_terminal_agent_input(
                    content,
                    session_id=self.options.session_id,
                    cwd=self.options.cwd,
                ),
                source=self.source,
            )
        )
        try:
            while not task.done() or not event_queue.empty():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                await self.emit(
                    "agent_event",
                    {
                        "task_id": event.task_id,
                        "event_type": event.type,
                        "content": event.content,
                        "created_at": event.created_at.isoformat(),
                    },
                )
            result = await task
        finally:
            unsubscribe()
        await self.emit(
            "final",
            {
                "task_id": result.task_id,
                "source": result.source,
                "status": result.status,
                "output": result.output,
            },
        )

    async def _on_background_task(self, record: BackgroundTaskRecord) -> None:
        await self.emit(
            "background_task",
            {
                "id": record.id,
                "status": record.status,
                "description": record.description,
                "error": record.error,
                "result": record.result,
            },
        )

    async def emit(self, event_type: str, payload: dict) -> None:
        data = {"type": event_type, **payload}
        await anyio.to_thread.run_sync(
            lambda: print(json.dumps(data, ensure_ascii=False, default=str), flush=True)
        )


async def run_terminal_bridge(
    *,
    config_file: str | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
) -> None:
    resolved_cwd = Path(cwd or os.getcwd()).resolve()
    settings: Settings = load_settings(config_file)
    configure_terminal_logging(debug=False, cwd=resolved_cwd)
    await ensure_storage_ready(settings)
    ctx = build_context(settings)
    session = TerminalBridgeSession(
        ctx,
        TerminalBridgeOptions(session_id=session_id or str(uuid4()), cwd=resolved_cwd),
    )
    await session.start()
    try:
        await session.run()
    finally:
        await session.stop()
