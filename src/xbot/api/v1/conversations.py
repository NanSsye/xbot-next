from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("")
async def list_conversations(limit: int = 100, ctx: AppContext = Depends(get_context)) -> dict:
    conversations = await ctx.conversations.list_conversations(limit)
    return {"success": True, "data": [item.model_dump(mode="json") for item in conversations]}


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    conversation = await ctx.conversations.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return {"success": True, "data": conversation.model_dump(mode="json")}


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str, limit: int = 20, ctx: AppContext = Depends(get_context)
) -> dict:
    messages = await ctx.conversations.get_messages(conversation_id, limit)
    return {"success": True, "data": [item.model_dump(mode="json") for item in messages]}


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    deleted = await ctx.conversations.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return {"success": True, "data": {"id": conversation_id, "deleted": True}}


@router.get("/{conversation_id}/state/{namespace}")
async def get_conversation_state(
    conversation_id: str, namespace: str, ctx: AppContext = Depends(get_context)
) -> dict:
    state = await ctx.conversations.get_state(conversation_id, namespace)
    return {"success": True, "data": state}


@router.put("/{conversation_id}/state/{namespace}")
async def set_conversation_state(
    conversation_id: str,
    namespace: str,
    value: dict,
    ctx: AppContext = Depends(get_context),
) -> dict:
    await ctx.conversations.set_state(conversation_id, namespace, value)
    return {"success": True, "data": value}
