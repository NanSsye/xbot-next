from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext
from xbot.storage.models import (
    ConversationRecord,
    GroupKnowledgeBaseRecord,
    GroupKnowledgeRunRecord,
)

router = APIRouter()


class KnowledgeToggle(BaseModel):
    enabled: bool


def _base_dict(base: GroupKnowledgeBaseRecord, conversation: ConversationRecord | None) -> dict:
    return {
        "conversation_id": base.conversation_id,
        "title": (conversation.title or conversation.raw_id) if conversation else base.conversation_id,
        "platform": conversation.platform if conversation else "unknown",
        "adapter": conversation.adapter if conversation else "unknown",
        "enabled": base.enabled,
        "interval_seconds": base.interval_seconds,
        "cursor_record_id": base.cursor_record_id,
        "status": base.status,
        "last_run_at": base.last_run_at.isoformat() if base.last_run_at else None,
        "next_run_at": base.next_run_at.isoformat() if base.next_run_at else None,
        "last_error": base.last_error,
        "page_count": base.page_count,
        "source_count": base.source_count,
        "file_count": base.file_count,
        "person_count": base.person_count,
        "updated_at": base.updated_at.isoformat(),
    }


@router.get("/bases")
async def list_bases(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.knowledge.sync_group_bases()
    async with ctx.storage.session_factory() as session:
        rows = (await session.execute(
            select(GroupKnowledgeBaseRecord, ConversationRecord)
            .outerjoin(ConversationRecord, ConversationRecord.id == GroupKnowledgeBaseRecord.conversation_id)
            .order_by(GroupKnowledgeBaseRecord.updated_at.desc())
        )).all()
    return {"success": True, "data": [_base_dict(base, conversation) for base, conversation in rows]}


@router.get("/bases/{conversation_id}")
async def get_base(conversation_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.knowledge.sync_group_bases()
    async with ctx.storage.session_factory() as session:
        base = await session.get(GroupKnowledgeBaseRecord, conversation_id)
        conversation = await session.get(ConversationRecord, conversation_id)
    if base is None:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    return {"success": True, "data": _base_dict(base, conversation)}


@router.put("/bases/{conversation_id}")
async def toggle_base(conversation_id: str, payload: KnowledgeToggle, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        await ctx.knowledge.set_enabled(conversation_id, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await get_base(conversation_id, ctx)


@router.post("/bases/{conversation_id}/run")
async def run_base(conversation_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.knowledge.sync_group_bases()
    async with ctx.storage.session_factory() as session:
        if await session.get(GroupKnowledgeBaseRecord, conversation_id) is None:
            raise HTTPException(status_code=404, detail="knowledge base not found")
    started = ctx.knowledge.trigger(conversation_id)
    return {"success": True, "data": {"conversation_id": conversation_id, "started": started}}


@router.get("/bases/{conversation_id}/pages")
async def list_pages(
    conversation_id: str,
    q: str = "",
    limit: int = Query(200, ge=1, le=500),
    ctx: AppContext = Depends(get_context),
) -> dict:
    rows = await ctx.knowledge.search(conversation_id, q, limit=limit)
    return {"success": True, "data": rows}


@router.get("/bases/{conversation_id}/page")
async def read_page(
    conversation_id: str,
    path: str = Query(..., min_length=1, max_length=1024),
    ctx: AppContext = Depends(get_context),
) -> dict:
    try:
        content = await asyncio.to_thread(ctx.knowledge.read_page, conversation_id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="knowledge page not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": {"conversation_id": conversation_id, "relative_path": path, "content": content}}


@router.get("/bases/{conversation_id}/runs")
async def list_runs(
    conversation_id: str,
    limit: int = Query(30, ge=1, le=100),
    ctx: AppContext = Depends(get_context),
) -> dict:
    async with ctx.storage.session_factory() as session:
        rows = (await session.execute(
            select(GroupKnowledgeRunRecord)
            .where(GroupKnowledgeRunRecord.conversation_id == conversation_id)
            .order_by(GroupKnowledgeRunRecord.started_at.desc())
            .limit(limit)
        )).scalars().all()
    return {"success": True, "data": [{
        "id": row.id, "conversation_id": row.conversation_id, "status": row.status,
        "from_cursor": row.from_cursor, "to_cursor": row.to_cursor,
        "message_count": row.message_count, "file_count": row.file_count,
        "page_change_count": row.page_change_count, "model": row.model,
        "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
        "error": row.error, "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    } for row in rows]}


@router.get("/bases/{conversation_id}/download")
async def download_vault(conversation_id: str, ctx: AppContext = Depends(get_context)) -> FileResponse:
    async with ctx.storage.session_factory() as session:
        if await session.get(GroupKnowledgeBaseRecord, conversation_id) is None:
            raise HTTPException(status_code=404, detail="knowledge base not found")
    path = await asyncio.to_thread(ctx.knowledge.make_archive, conversation_id)
    return FileResponse(path, media_type="application/zip", filename="xbot-group-vault.zip")
