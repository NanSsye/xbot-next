from __future__ import annotations

import json
import base64
import mimetypes
from pathlib import Path
from uuid import uuid4
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select

from xbot.adapters.wechat869.client import Wechat869Client
from xbot.app.deps import get_context
from xbot.messaging.models import Message, Reply
from xbot.runtime.context import AppContext
from xbot.storage.models import (
    ContactRecord,
    ConversationMemberRecord,
    ConversationMessageRecord,
    ConversationRecord,
    MessageAttachmentRecord,
    UserProfileRecord,
)

router = APIRouter()


class WechatProfileUpdate(BaseModel):
    conversation_id: str | None = None
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


def _decode_offset_cursor(cursor: str) -> int:
    if not cursor:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        return max(0, int(payload.get("offset", 0)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid cursor") from exc


def _encode_offset_cursor(offset: int) -> str:
    raw = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _wechat869_client(ctx: AppContext) -> Wechat869Client:
    cfg = ctx.settings.adapters.wechat869
    return Wechat869Client(
        host=cfg.host,
        port=cfg.port,
        admin_key=cfg.admin_key,
        token_key=cfg.token_key,
        ws_url=cfg.ws_url,
    )


def _raw_conversation_id(conversation_id: str) -> str:
    if conversation_id.startswith("wechat:") and ":" in conversation_id:
        return conversation_id.split(":")[-1]
    return conversation_id


def _pick_text(data, keys) -> str:
    if not isinstance(data, dict):
        return ""
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("str") or value.get("string") or value.get("value")
        if value not in (None, ""):
            return str(value).strip()
    return ""



def _json(text: str, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def _contact_dict(record: ContactRecord | None, user_id: str, fallback_name: str | None = None) -> dict:
    return {
        "user_id": user_id,
        "nickname": (record.nickname if record else None) or fallback_name or user_id,
        "remark": record.remark if record else None,
        "avatar_url": record.avatar_url if record else None,
        "raw": _json(record.raw_json, {}) if record else {},
    }


def _public_media_url(path: str | None) -> str | None:
    value = str(path or "").replace("\\", "/").strip()
    if not value:
        return None
    if value.startswith(("http://", "https://", "/files/", "/media/")):
        return value
    if "/files/" in value:
        return value[value.index("/files/"):]
    if "/data/" in value:
        return "/media/" + value[value.index("/data/") + len("/data/"):]
    if value.startswith("files/"):
        return "/" + value
    if value.startswith("data/"):
        return "/media/" + value[len("data/"):]
    return None


def _message_dict(
    record: ConversationMessageRecord,
    attachments: list[MessageAttachmentRecord] | None = None,
    contact: ContactRecord | None = None,
) -> dict:
    raw = _json(record.raw_json, {})
    return {
        "id": record.message_id,
        "conversation_id": record.conversation_id,
        "platform": record.platform,
        "adapter": record.adapter,
        "sender_id": record.sender_id,
        "sender_name": (contact.nickname if contact else None) or record.sender_name,
        "sender_avatar_url": contact.avatar_url if contact else None,
        "type": record.type,
        "content": record.content,
        "raw": raw,
        "timestamp": record.created_at.isoformat(),
        "attachments": [_attachment_dict(x) for x in (attachments or [])],
    }


def _attachment_dict(record: MessageAttachmentRecord) -> dict:
    return {
        "id": record.id,
        "message_id": record.message_id,
        "conversation_id": record.conversation_id,
        "sender_id": record.sender_id,
        "kind": record.kind,
        "filename": record.filename,
        "mime": record.mime,
        "size": record.size,
        "local_path": record.local_path,
        "url": _public_media_url(record.url) or _public_media_url(record.local_path),
        "sha256": record.sha256,
        "download_status": record.download_status,
        "quoted": record.quoted,
        "metadata": _json(record.metadata_json, {}),
        "created_at": record.created_at.isoformat(),
    }


@router.get("/conversations")
async def list_wechat_conversations(limit: int = 100, ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session:
        rows = (await session.execute(
            select(ConversationRecord)
            .where(ConversationRecord.platform == "wechat")
            .order_by(ConversationRecord.updated_at.desc())
            .limit(limit)
        )).scalars().all()
        data = []
        for row in rows:
            last = (await session.execute(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == row.id)
                .order_by(ConversationMessageRecord.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            count = await session.scalar(select(func.count(ConversationMessageRecord.id)).where(ConversationMessageRecord.conversation_id == row.id))
            avatar_members = []
            conversation_avatar = getattr(row, "avatar_url", None)
            conversation_title = row.title or row.raw_id
            if row.scope == "group":
                if last and row.title and row.title == last.sender_name:
                    conversation_title = row.raw_id
                member_rows = (await session.execute(
                    select(ContactRecord.avatar_url)
                    .join(ConversationMemberRecord, and_(ConversationMemberRecord.user_id == ContactRecord.user_id, ConversationMemberRecord.conversation_id == row.id))
                    .where(ContactRecord.platform == row.platform, ContactRecord.adapter == row.adapter, ContactRecord.avatar_url.is_not(None))
                    .limit(9)
                )).all()
                avatar_members = [x[0] for x in member_rows if x[0]]
                if row.title:
                    title_is_member = await session.scalar(
                        select(ContactRecord.id)
                        .join(ConversationMemberRecord, and_(ConversationMemberRecord.user_id == ContactRecord.user_id, ConversationMemberRecord.conversation_id == row.id))
                        .where(ContactRecord.platform == row.platform, ContactRecord.adapter == row.adapter, ContactRecord.nickname == row.title)
                        .limit(1)
                    )
                    if title_is_member:
                        conversation_title = row.raw_id
            else:
                contact = (await session.execute(
                    select(ContactRecord).where(
                        ContactRecord.platform == row.platform,
                        ContactRecord.adapter == row.adapter,
                        ContactRecord.user_id == row.raw_id,
                    ).limit(1)
                )).scalar_one_or_none()
                if contact:
                    conversation_avatar = conversation_avatar or contact.avatar_url
                    conversation_title = contact.nickname or contact.remark or row.title or row.raw_id
            data.append({
                "id": row.id,
                "platform": row.platform,
                "adapter": row.adapter,
                "scope": row.scope,
                "raw_id": row.raw_id,
                "title": conversation_title,
                "avatar_url": conversation_avatar,
                "avatar_members": avatar_members,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "message_count": int(count or 0),
                "last_message": _message_dict(last) if last else None,
            })
        return {"success": True, "data": data}


@router.get("/conversations/{conversation_id}/messages")
async def list_wechat_messages(conversation_id: str, limit: int = 200, ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session:
        records = list((await session.execute(
            select(ConversationMessageRecord)
            .where(ConversationMessageRecord.conversation_id == conversation_id)
            .order_by(ConversationMessageRecord.created_at.desc())
            .limit(limit)
        )).scalars().all())
        records.reverse()
        ids = [x.message_id for x in records]
        attach_map: dict[str, list[MessageAttachmentRecord]] = {x: [] for x in ids}
        if ids:
            attachments = (await session.execute(
                select(MessageAttachmentRecord).where(MessageAttachmentRecord.message_id.in_(ids)).order_by(MessageAttachmentRecord.id.asc())
            )).scalars().all()
            for item in attachments:
                attach_map.setdefault(item.message_id, []).append(item)
        sender_ids = {x.sender_id for x in records if x.sender_id}
        contacts = {}
        if sender_ids:
            for c in (await session.execute(
                select(ContactRecord).where(ContactRecord.platform == "wechat", ContactRecord.user_id.in_(sender_ids))
            )).scalars().all():
                contacts[c.user_id] = c
        return {"success": True, "data": [_message_dict(x, attach_map.get(x.message_id, []), contacts.get(x.sender_id)) for x in records]}


@router.get("/conversations/{conversation_id}/members")
async def list_wechat_members(conversation_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session:
        conv = await session.get(ConversationRecord, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        sender_counts = (await session.execute(
            select(ConversationMessageRecord.sender_id, func.count(ConversationMessageRecord.id), func.max(ConversationMessageRecord.created_at))
            .where(ConversationMessageRecord.conversation_id == conversation_id)
            .group_by(ConversationMessageRecord.sender_id)
        )).all()
        known = (await session.execute(
            select(ConversationMemberRecord).where(ConversationMemberRecord.conversation_id == conversation_id)
        )).scalars().all()
        ids = {x.user_id for x in known} | {x[0] for x in sender_counts}
        contacts = {}
        if ids:
            for c in (await session.execute(
                select(ContactRecord).where(ContactRecord.platform == conv.platform, ContactRecord.adapter == conv.adapter, ContactRecord.user_id.in_(ids))
            )).scalars().all():
                contacts[c.user_id] = c
        count_map = {x[0]: int(x[1] or 0) for x in sender_counts}
        last_map = {x[0]: x[2] for x in sender_counts}
        member_names = {x.user_id: x.display_name for x in known}
        data = []
        for user_id in sorted(ids, key=lambda x: count_map.get(x, 0), reverse=True):
            contact = _contact_dict(contacts.get(user_id), user_id, member_names.get(user_id))
            contact.update({
                "conversation_id": conversation_id,
                "message_count": count_map.get(user_id, 0),
                "last_active_at": last_map.get(user_id).isoformat() if last_map.get(user_id) else None,
            })
            data.append(contact)
        return {"success": True, "data": data}


@router.get("/conversations/{conversation_id}/profiles")
async def list_wechat_member_profiles(
    conversation_id: str,
    limit: int = 30,
    cursor: str = "",
    ctx: AppContext = Depends(get_context),
) -> dict:
    page_size = max(1, min(100, limit))
    offset = _decode_offset_cursor(cursor)
    async with ctx.storage.session_factory() as session:
        conv = await session.get(ConversationRecord, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        sender_rows = (await session.execute(
            select(
                ConversationMessageRecord.sender_id,
                func.count(ConversationMessageRecord.id),
                func.max(ConversationMessageRecord.created_at),
            )
            .where(ConversationMessageRecord.conversation_id == conversation_id)
            .group_by(ConversationMessageRecord.sender_id)
        )).all()
        known = (await session.execute(
            select(ConversationMemberRecord).where(
                ConversationMemberRecord.conversation_id == conversation_id
            )
        )).scalars().all()
        count_map = {row[0]: int(row[1] or 0) for row in sender_rows if row[0]}
        last_map = {row[0]: row[2] for row in sender_rows if row[0]}
        member_names = {row.user_id: row.display_name for row in known}
        user_ids = sorted(
            set(member_names) | set(count_map),
            key=lambda user_id: (-count_map.get(user_id, 0), user_id),
        )
        total = len(user_ids)
        page_ids = user_ids[offset:offset + page_size]
        contacts = {}
        profiles_by_user: dict[str, list[UserProfileRecord]] = {}
        image_counts = {}
        if page_ids:
            contacts = {
                row.user_id: row
                for row in (await session.execute(
                    select(ContactRecord).where(
                        ContactRecord.platform == conv.platform,
                        ContactRecord.adapter == conv.adapter,
                        ContactRecord.user_id.in_(page_ids),
                    )
                )).scalars().all()
            }
            raw_id = _raw_conversation_id(conversation_id)
            profile_rows = (await session.execute(
                select(UserProfileRecord).where(
                    UserProfileRecord.platform == conv.platform,
                    UserProfileRecord.adapter == conv.adapter,
                    UserProfileRecord.user_id.in_(page_ids),
                    or_(
                        UserProfileRecord.conversation_id == conversation_id,
                        UserProfileRecord.conversation_id == raw_id,
                        UserProfileRecord.conversation_id.is_(None),
                    ),
                )
            )).scalars().all()
            for row in profile_rows:
                profiles_by_user.setdefault(row.user_id, []).append(row)
            image_counts = {
                row[0]: int(row[1] or 0)
                for row in (await session.execute(
                    select(MessageAttachmentRecord.sender_id, func.count(MessageAttachmentRecord.id))
                    .where(
                        MessageAttachmentRecord.conversation_id == conversation_id,
                        MessageAttachmentRecord.sender_id.in_(page_ids),
                        MessageAttachmentRecord.kind == "image",
                    )
                    .group_by(MessageAttachmentRecord.sender_id)
                )).all()
            }

        def pick_profile(user_id: str) -> UserProfileRecord | None:
            raw_id = _raw_conversation_id(conversation_id)
            rank = {conversation_id: 0, raw_id: 1, None: 2}
            rows = profiles_by_user.get(user_id, [])
            return min(rows, key=lambda row: (rank.get(row.conversation_id, 3), -(row.updated_at.timestamp() if row.updated_at else 0))) if rows else None

        items = []
        for user_id in page_ids:
            contact = contacts.get(user_id)
            profile = pick_profile(user_id)
            items.append({
                "contact": _contact_dict(contact, user_id, member_names.get(user_id)),
                "stats": {"message_count": count_map.get(user_id, 0), "image_count": image_counts.get(user_id, 0)},
                "profile": {
                    "summary": profile.summary if profile else "暂无 AI 用户画像。",
                    "tags": _json(profile.tags_json, []) if profile else [],
                    "updated_at": profile.updated_at.isoformat() if profile and profile.updated_at else None,
                },
                "recent_messages": [],
                "images": [],
                "last_active_at": last_map.get(user_id).isoformat() if last_map.get(user_id) else None,
            })
        next_offset = offset + len(page_ids)
        return {"success": True, "data": {
            "items": items,
            "total": total,
            "next_cursor": _encode_offset_cursor(next_offset) if next_offset < total else None,
        }}


@router.get("/users")
async def list_wechat_users(limit: int = 500, q: str = "", ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session:
        profile_rows = (await session.execute(
            select(UserProfileRecord)
            .where(UserProfileRecord.platform == "wechat")
            .order_by(UserProfileRecord.updated_at.desc())
            .limit(limit)
        )).scalars().all()
        user_ids = {x.user_id for x in profile_rows}
        msg_counts = (await session.execute(
            select(ConversationMessageRecord.sender_id, func.count(ConversationMessageRecord.id), func.max(ConversationMessageRecord.created_at))
            .where(ConversationMessageRecord.platform == "wechat")
            .group_by(ConversationMessageRecord.sender_id)
            .limit(limit)
        )).all()
        user_ids |= {x[0] for x in msg_counts if x[0]}
        if q.strip():
            text = f"%{q.strip()}%"
            contact_hits = (await session.execute(
                select(ContactRecord.user_id).where(
                    ContactRecord.platform == "wechat",
                    or_(ContactRecord.user_id.ilike(text), ContactRecord.nickname.ilike(text), ContactRecord.remark.ilike(text)),
                ).limit(limit)
            )).all()
            user_ids |= {x[0] for x in contact_hits}
        contacts = {}
        if user_ids:
            for c in (await session.execute(select(ContactRecord).where(ContactRecord.platform == "wechat", ContactRecord.user_id.in_(user_ids)))).scalars().all():
                contacts[c.user_id] = c
        count_map = {x[0]: int(x[1] or 0) for x in msg_counts}
        image_counts = {}
        if user_ids:
            for sender_id, count in (await session.execute(
                select(MessageAttachmentRecord.sender_id, func.count(MessageAttachmentRecord.id))
                .where(MessageAttachmentRecord.sender_id.in_(user_ids), MessageAttachmentRecord.kind == "image")
                .group_by(MessageAttachmentRecord.sender_id)
            )).all():
                image_counts[sender_id] = int(count or 0)
        profile_map = {}
        for row in profile_rows:
            old = profile_map.get(row.user_id)
            if old is None or (old.conversation_id is not None and row.conversation_id is None):
                profile_map[row.user_id] = row
        data = []
        needle = q.strip().lower()
        def sort_time(uid: str) -> datetime:
            profile = profile_map.get(uid)
            return profile.updated_at if profile and profile.updated_at else datetime.min

        for user_id in sorted(user_ids, key=sort_time, reverse=True)[:limit]:
            profile = profile_map.get(user_id)
            tags = [str(x) for x in (_json(profile.tags_json, []) if profile else []) if str(x).strip()]
            contact = contacts.get(user_id)
            summary = profile.summary if profile else "暂无 AI 用户画像。"
            haystack = " ".join(str(x or "") for x in [
                user_id,
                contact.nickname if contact else "",
                contact.remark if contact else "",
                summary,
                " ".join(tags),
            ]).lower()
            if needle and needle not in haystack:
                continue
            data.append({
                "contact": _contact_dict(contact, user_id),
                "stats": {"message_count": count_map.get(user_id, 0), "image_count": image_counts.get(user_id, 0)},
                "profile": {"summary": summary, "tags": tags, "updated_at": profile.updated_at.isoformat() if profile else None},
                "recent_messages": [],
                "images": [],
            })
        return {"success": True, "data": data}


@router.get("/users/{user_id}")
async def get_wechat_user(user_id: str, conversation_id: str | None = None, ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session:
        contact = (await session.execute(select(ContactRecord).where(ContactRecord.platform == "wechat", ContactRecord.user_id == user_id).limit(1))).scalar_one_or_none()
        filters = [ConversationMessageRecord.sender_id == user_id, ConversationMessageRecord.platform == "wechat"]
        if conversation_id:
            filters.append(ConversationMessageRecord.conversation_id == conversation_id)
        msg_count = int(await session.scalar(select(func.count(ConversationMessageRecord.id)).where(*filters)) or 0)
        image_count = int(await session.scalar(select(func.count(MessageAttachmentRecord.id)).where(MessageAttachmentRecord.sender_id == user_id, MessageAttachmentRecord.kind == "image", *( [MessageAttachmentRecord.conversation_id == conversation_id] if conversation_id else [] ))) or 0)
        recent = list((await session.execute(select(ConversationMessageRecord).where(*filters).order_by(ConversationMessageRecord.created_at.desc()).limit(50))).scalars().all())
        recent.reverse()
        images = (await session.execute(select(MessageAttachmentRecord).where(MessageAttachmentRecord.sender_id == user_id, MessageAttachmentRecord.kind == "image", *( [MessageAttachmentRecord.conversation_id == conversation_id] if conversation_id else [] )).order_by(MessageAttachmentRecord.created_at.desc()).limit(60))).scalars().all()
        profile_filters = [UserProfileRecord.platform == "wechat", UserProfileRecord.user_id == user_id]
        if conversation_id:
            raw_conversation_id = _raw_conversation_id(conversation_id)
            profile_filters.append(
                or_(
                    UserProfileRecord.conversation_id == conversation_id,
                    UserProfileRecord.conversation_id == raw_conversation_id,
                    UserProfileRecord.conversation_id.is_(None),
                )
            )
            profile_order = case(
                (UserProfileRecord.conversation_id == conversation_id, 0),
                (UserProfileRecord.conversation_id == raw_conversation_id, 1),
                else_=2,
            )
        else:
            profile_filters.append(UserProfileRecord.conversation_id.is_(None))
            profile_order = UserProfileRecord.updated_at.desc()
        profile = (await session.execute(
            select(UserProfileRecord)
            .where(*profile_filters)
            .order_by(profile_order, UserProfileRecord.updated_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        summary = profile.summary if profile else "暂无 AI 用户画像。"
        tags = _json(profile.tags_json, []) if profile else []
        return {
            "success": True,
            "data": {
                "contact": _contact_dict(contact, user_id),
                "stats": {"message_count": msg_count, "image_count": image_count},
                "profile": {"summary": summary, "tags": tags, "updated_at": profile.updated_at.isoformat() if profile else None},
                "recent_messages": [_message_dict(x) for x in recent],
                "images": [_attachment_dict(x) for x in images],
            },
        }


@router.put("/users/{user_id}/profile")
async def update_wechat_user_profile(user_id: str, payload: WechatProfileUpdate, ctx: AppContext = Depends(get_context)) -> dict:
    tags = []
    seen = set()
    for tag in payload.tags:
        value = str(tag or "").strip()
        if value and value not in seen:
            tags.append(value[:32])
            seen.add(value)
    tags = tags[:20]
    summary = str(payload.summary or "").strip()
    conversation_id = payload.conversation_id or None
    async with ctx.storage.session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(UserProfileRecord).where(
                    UserProfileRecord.platform == "wechat",
                    UserProfileRecord.adapter == "wechat869",
                    UserProfileRecord.user_id == user_id,
                    UserProfileRecord.conversation_id.is_(None) if conversation_id is None else UserProfileRecord.conversation_id == conversation_id,
                ).limit(1)
            )
            record = result.scalar_one_or_none()
            if record:
                record.summary = summary
                record.tags_json = json.dumps(tags, ensure_ascii=False)
                record.updated_at = _beijing_now()
            else:
                session.add(UserProfileRecord(
                    platform="wechat",
                    adapter="wechat869",
                    user_id=user_id,
                    conversation_id=conversation_id,
                    summary=summary,
                    tags_json=json.dumps(tags, ensure_ascii=False),
                    stats_json=json.dumps({"source": "manual_ui"}, ensure_ascii=False),
                    updated_at=_beijing_now(),
                ))
    return await get_wechat_user(user_id, conversation_id=conversation_id, ctx=ctx)


def _build_profile_summary(messages: list[ConversationMessageRecord]) -> str:
    texts = [str(x.content or "").strip() for x in messages if str(x.content or "").strip()]
    if not texts:
        return "暂无足够文本生成画像。"
    total = len(texts)
    sample = "；".join(texts[-5:])[:220]
    return f"基于最近 {total} 条文本发言：常见表达片段：{sample}"


def _guess_tags(messages: list[ConversationMessageRecord]) -> list[str]:
    words = Counter()
    for msg in messages:
        for token in str(msg.content or "").replace("，", " ").replace("。", " ").split():
            token = token.strip()[:16]
            if len(token) >= 2:
                words[token] += 1
    return [x for x, _ in words.most_common(8)]


@router.post("/conversations/{conversation_id}/send")
async def send_wechat_message(
    conversation_id: str,
    text: str = Form(""),
    file: UploadFile | None = File(None),
    ctx: AppContext = Depends(get_context),
) -> dict:
    async with ctx.storage.session_factory() as session:
        conv = await session.get(ConversationRecord, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
    now = _beijing_now()
    bot_id = ctx.settings.adapters.wechat869.bot_wxid or "xbot"
    bot_name = ctx.settings.adapters.wechat869.bot_nickname or "xbot"
    attachment = None
    msg_type = "text"
    content = text.strip()
    reply_content = content
    if file is not None:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        root = Path("files") / "wechat_outbox" / f"{now:%Y%m%d}"
        root.mkdir(parents=True, exist_ok=True)
        filename = Path(file.filename or "upload.bin").name
        target = root / f"{uuid4().hex}_{filename}"
        target.write_bytes(data)
        mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        kind = "image" if mime.startswith("image/") else "file"
        msg_type = kind
        reply_content = str(target)
        content = content or f"[{kind}] {filename}"
        attachment = {
            "kind": kind,
            "filename": filename,
            "mime": mime,
            "size": len(data),
            "local_path": str(target).replace("\\", "/"),
            "url": "/" + str(target).replace("\\", "/"),
            "download_status": "downloaded",
            "quoted": False,
            "metadata": {"source": "control_ui"},
        }
    await ctx.engine.send_reply(Reply(platform="wechat", adapter="wechat869", conversation_id=conversation_id, type=msg_type, content=reply_content))
    message = Message(
        platform="wechat",
        adapter="wechat869",
        conversation_id=conversation_id,
        sender_id=bot_id,
        sender_name=bot_name,
        type=msg_type,
        content=content,
        raw={"direction": "outgoing", "scope": "group" if ":group:" in conversation_id else "private", "attachments": [attachment] if attachment else []},
        timestamp=now,
    )
    async with ctx.storage.session_factory() as session:
        async with session.begin():
            repo = ctx.storage.conversations(session)
            await repo.append_message(conversation_id, message)
            conv = await session.get(ConversationRecord, conversation_id)
            if conv:
                conv.updated_at = now
    async with ctx.storage.session_factory() as session:
        record = (await session.execute(
            select(ConversationMessageRecord)
            .where(ConversationMessageRecord.conversation_id == conversation_id, ConversationMessageRecord.message_id == message.id)
            .limit(1)
        )).scalar_one_or_none()
        attachments = (await session.execute(
            select(MessageAttachmentRecord).where(MessageAttachmentRecord.message_id == message.id).order_by(MessageAttachmentRecord.id.asc())
        )).scalars().all()
        contact = (await session.execute(
            select(ContactRecord).where(ContactRecord.platform == "wechat", ContactRecord.user_id == message.sender_id).limit(1)
        )).scalar_one_or_none()
        data = _message_dict(record, attachments, contact) if record else message.model_dump(mode="json")
    await ctx.events.publish("message.created", {"message": data})
    return {"success": True, "data": data}


@router.post("/sync")
async def sync_wechat_metadata(ctx: AppContext = Depends(get_context)) -> dict:
    client = _wechat869_client(ctx)
    updated_conversations = 0
    updated_contacts = 0
    async with ctx.storage.session_factory() as session:
        async with session.begin():
            convs = (await session.execute(select(ConversationRecord).where(ConversationRecord.platform == "wechat"))).scalars().all()
            for conv in convs:
                raw_id = conv.raw_id or _raw_conversation_id(conv.id)
                if conv.adapter == "wechat869" and conv.scope == "group":
                    try:
                        info = await client.call_path("/group/GetChatRoomInfo", body={"ChatRoomWxIdList": [raw_id]})
                        contact_list = info.get("contactList") or info.get("ContactList") or [] if isinstance(info, dict) else []
                        first = contact_list[0] if contact_list else {}
                        title = _pick_text(first, ("nickName", "NickName", "remark", "Remark"))
                        if title:
                            conv.title = title
                            updated_conversations += 1
                    except Exception:
                        pass
                    try:
                        members = await client.get_chatroom_member_list(raw_id)
                        for m in members:
                            user_id = _pick_text(m, ("UserName", "userName", "user_name", "Wxid", "wxid"))
                            if not user_id or user_id.endswith("@chatroom"):
                                continue
                            nickname = _pick_text(m, ("NickName", "nickName", "nick_name", "DisplayName"))
                            avatar = _pick_text(m, ("BigHeadImgUrl", "bigHeadImgUrl", "big_head_img_url", "SmallHeadImgUrl", "smallHeadImgUrl"))
                            result = await session.execute(select(ContactRecord).where(ContactRecord.platform == "wechat", ContactRecord.adapter == conv.adapter, ContactRecord.user_id == user_id))
                            rec = result.scalar_one_or_none()
                            if rec:
                                rec.nickname = nickname or rec.nickname
                                rec.avatar_url = avatar or rec.avatar_url
                                rec.last_seen_at = datetime.utcnow()
                            else:
                                session.add(ContactRecord(platform="wechat", adapter=conv.adapter, user_id=user_id, nickname=nickname or user_id, avatar_url=avatar or None, raw_json=json.dumps(m, ensure_ascii=False), first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
                            exists = await session.scalar(select(ConversationMemberRecord.id).where(ConversationMemberRecord.conversation_id == conv.id, ConversationMemberRecord.user_id == user_id).limit(1))
                            if not exists:
                                session.add(ConversationMemberRecord(conversation_id=conv.id, user_id=user_id, display_name=nickname or user_id, role="member", joined_at=datetime.utcnow()))
                            updated_contacts += 1
                    except Exception:
                        pass
    return {"success": True, "data": {"updated_conversations": updated_conversations, "updated_contacts": updated_contacts}}
