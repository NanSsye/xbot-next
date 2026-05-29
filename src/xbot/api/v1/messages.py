from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from xbot.app.deps import get_context
from xbot.messaging.models import Message, MessageEnvelope
from xbot.runtime.context import AppContext

router = APIRouter()


class SimulateMessageRequest(BaseModel):
    content: str
    conversation_id: str = "default"
    sender_id: str = "api-user"
    sender_name: str | None = None


@router.post("/simulate")
async def simulate_message(
    payload: SimulateMessageRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    message = Message(
        platform="web",
        adapter="web",
        conversation_id=payload.conversation_id,
        sender_id=payload.sender_id,
        sender_name=payload.sender_name,
        content=payload.content,
        raw=payload.model_dump(),
    )
    await ctx.messages.add_message(message)
    envelope = MessageEnvelope.from_message(message)
    await ctx.messages.add_envelope(envelope)
    await ctx.message_queue.publish(envelope)
    return {
        "success": True,
        "data": {
            "message": message.model_dump(mode="json"),
            "envelope": envelope.model_dump(mode="json"),
            "queued": True,
        },
    }


@router.get("/recent")
async def recent_messages(limit: int = 50, ctx: AppContext = Depends(get_context)) -> dict:
    messages = await ctx.messages.recent_messages(limit)
    return {"success": True, "data": [m.model_dump(mode="json") for m in messages]}


@router.get("/recent-replies")
async def recent_replies(limit: int = 50, ctx: AppContext = Depends(get_context)) -> dict:
    replies = await ctx.messages.recent_replies(limit)
    return {"success": True, "data": [r.model_dump(mode="json") for r in replies]}
