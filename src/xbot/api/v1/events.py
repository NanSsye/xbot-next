from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.runtime import AgentRuntimeEvent
from xbot.app.security import authenticate_websocket

router = APIRouter()


@router.websocket("/ws")
async def event_stream(websocket: WebSocket) -> None:
    if not await authenticate_websocket(websocket):
        return
    await websocket.accept()
    ctx = websocket.app.state.context
    lock = asyncio.Lock()
    client_id = str(uuid4())

    async def send_json(payload: dict) -> None:
        async with lock:
            await websocket.send_json(payload)

    async def on_agent_event(event: AgentRuntimeEvent) -> None:
        await send_json(
            {
                "id": str(uuid4()),
                "type": "agent.event",
                "topic": f"agent:{event.task_id}",
                "data": event.model_dump(mode="json"),
                "created_at": datetime.utcnow().isoformat(),
            }
        )


    async def on_message_created(payload: dict) -> None:
        await send_json(
            {
                "id": str(uuid4()),
                "type": "message.created",
                "topic": "messages",
                "data": payload,
                "created_at": datetime.utcnow().isoformat(),
            }
        )

    async def on_background_task(record: BackgroundTaskRecord) -> None:
        await send_json(
            {
                "id": str(uuid4()),
                "type": "background_task.updated",
                "topic": f"background_task:{record.id}",
                "data": record.model_dump(mode="json"),
                "created_at": datetime.utcnow().isoformat(),
            }
        )

    unsubscribe_agent = ctx.agent.subscribe_events(on_agent_event)
    unsubscribe_background = ctx.agent.background.subscribe(on_background_task)
    unsubscribe_message = ctx.events.subscribe("message.created", on_message_created)
    await send_json(
        {
            "id": str(uuid4()),
            "type": "ui.connected",
            "topic": "ui",
            "data": {"client_id": client_id},
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await send_json(
                    {
                        "id": str(uuid4()),
                        "type": "pong",
                        "topic": "ui",
                        "data": {},
                        "created_at": datetime.utcnow().isoformat(),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe_agent()
        unsubscribe_background()
        unsubscribe_message()
