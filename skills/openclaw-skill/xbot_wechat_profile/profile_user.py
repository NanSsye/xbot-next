#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import psycopg
except Exception:
    psycopg = None

DEFAULT_DSN = "postgresql://xbot:xbot@host.docker.internal:8549/xbot"


def _load_dsn() -> str | None:
    path = os.path.expanduser("~/.openclaw/credentials/xbot_db.json")
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return (json.load(f) or {}).get("database_url")
    except Exception:
        return None
    return None


def _dsn(args) -> str:
    return args.database_url or os.environ.get("XBOT_HISTORY_DATABASE_URL") or _load_dsn() or DEFAULT_DSN


def _die(msg: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def _redact(dsn: str) -> str:
    try:
        p = urlparse(dsn)
        return f"postgresql://***:***@{p.hostname or 'host'}{':' + str(p.port) if p.port else ''}/{(p.path or '/').lstrip('/')}"
    except Exception:
        return "postgresql://***"


def _safe_limit(value: int) -> int:
    return max(1, min(int(value or 80), 300))


def _conversation_filter(conversation: str | None):
    if not conversation:
        return "", []
    return " AND conversation_id ILIKE %s", [f"%{conversation}%"]


def _time_filter(args):
    sql = ""
    params: list[object] = []
    if getattr(args, "since", None):
        sql += " AND created_at >= %s"
        params.append(args.since)
    if getattr(args, "until", None):
        sql += " AND created_at < %s"
        params.append(args.until)
    return sql, params


def _json_loads(value: str, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _row_time(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def cmd_context(conn, args) -> dict:
    extra, params = _conversation_filter(args.conversation)
    time_extra, time_params = _time_filter(args)
    params = [args.user, *params, *time_params, _safe_limit(args.limit)]
    sql = f"""
        SELECT message_id, conversation_id, sender_id, sender_name, type, content, created_at
        FROM conversation_messages
        WHERE platform='wechat' AND sender_id=%s {extra} {time_extra}
        ORDER BY created_at DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql, params)
        rows = list(reversed(cur.fetchall()))
        cur.execute(
            "SELECT user_id, nickname, remark, avatar_url FROM contacts WHERE platform='wechat' AND user_id=%s LIMIT 1",
            [args.user],
        )
        contact = cur.fetchone()
        profile = None
        if args.include_profile:
            profile_extra = " AND conversation_id=%s" if args.conversation else " AND conversation_id IS NULL"
            profile_params = [args.user] + ([args.conversation] if args.conversation else [])
            cur.execute(
                f"""
                SELECT summary, tags_json, stats_json, updated_at
                FROM user_profiles
                WHERE platform='wechat' AND user_id=%s {profile_extra}
                LIMIT 1
                """,
                profile_params,
            )
            profile = cur.fetchone()
        image_extra, image_params = _conversation_filter(args.conversation)
        image_time_extra, image_time_params = _time_filter(args)
        cur.execute(
            f"""
            SELECT kind, filename, url, local_path, created_at
            FROM message_attachments
            WHERE sender_id=%s AND kind='image' {image_extra} {image_time_extra}
            ORDER BY created_at DESC
            LIMIT 20
            """,
            [args.user, *image_params, *image_time_params],
        )
        images = cur.fetchall()
    return {
        "ok": True,
        "user_id": args.user,
        "conversation": args.conversation,
        "since": args.since,
        "until": args.until,
        "contact": {
            "user_id": contact[0],
            "nickname": contact[1],
            "remark": contact[2],
            "avatar_url": contact[3],
        } if contact else {"user_id": args.user},
        "previous_profile": {
            "summary": profile[0],
            "tags": _json_loads(profile[1], []),
            "stats": _json_loads(profile[2], {}),
            "updated_at": _row_time(profile[3]),
        } if profile else None,
        "messages": [
            {
                "time": _row_time(r[6]),
                "message_id": r[0],
                "conversation_id": r[1],
                "sender_name": r[3],
                "type": r[4],
                "content": r[5] or "",
            }
            for r in rows
        ],
        "images": [
            {"kind": r[0], "filename": r[1], "url": r[2], "local_path": r[3], "time": _row_time(r[4])}
            for r in images
        ],
        "instruction": "第一次画像可基于全部 messages；增量画像请基于 previous_profile + 本次时间范围 messages/images，输出更新后的 summary/tags 后调用 save 覆盖。",
    }


def cmd_get(conn, args) -> dict:
    extra = " AND conversation_id=%s" if args.conversation else " AND conversation_id IS NULL"
    params = [args.user] + ([args.conversation] if args.conversation else [])
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(
            f"""
            SELECT summary, tags_json, stats_json, updated_at
            FROM user_profiles
            WHERE platform='wechat' AND user_id=%s {extra}
            LIMIT 1
            """,
            params,
        )
        row = cur.fetchone()
    return {
        "ok": True,
        "found": bool(row),
        "user_id": args.user,
        "conversation_id": args.conversation,
        "profile": {
            "summary": row[0],
            "tags": _json_loads(row[1], []),
            "stats": _json_loads(row[2], {}),
            "updated_at": _row_time(row[3]),
        } if row else None,
    }


def cmd_save(conn, args) -> dict:
    summary = (args.summary or "").strip()
    if not summary:
        _die("summary required")
    tags = [x.strip() for x in (args.tags or "").replace("，", ",").split(",") if x.strip()]
    tags = tags[:12]
    stats = {"source": "openclaw_skill", "evidence": "wechat_history", "saved_at": datetime.utcnow().isoformat()}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_profiles (platform, adapter, user_id, conversation_id, summary, tags_json, stats_json, updated_at)
            VALUES ('wechat', %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (platform, adapter, user_id, conversation_id)
            DO UPDATE SET summary=EXCLUDED.summary, tags_json=EXCLUDED.tags_json, stats_json=EXCLUDED.stats_json, updated_at=now()
            """,
            [
                args.adapter,
                args.user,
                args.conversation,
                summary,
                json.dumps(tags, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False),
            ],
        )
    conn.commit()
    return {"ok": True, "saved": True, "user_id": args.user, "conversation_id": args.conversation, "tags": tags}


def main() -> int:
    ap = argparse.ArgumentParser(description="xbot WeChat profile/persona helper")
    ap.add_argument("--database-url")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--user", required=True, help="wxid/user id")
        p.add_argument("--conversation", help="exact conversation_id for save/get; contains match for context")

    p = sub.add_parser("context")
    common(p)
    p.add_argument("--limit", type=int, default=80)
    p.add_argument("--since", help="only messages/images created_at >= this time, e.g. '2026-06-30 00:00:00'")
    p.add_argument("--until", help="only messages/images created_at < this time")
    p.add_argument("--include-profile", action="store_true", help="include existing saved profile for incremental update")

    p = sub.add_parser("get")
    common(p)

    p = sub.add_parser("save")
    common(p)
    p.add_argument("--adapter", default="wechat869")
    p.add_argument("--summary", required=True)
    p.add_argument("--tags", default="")

    args = ap.parse_args()
    if psycopg is None:
        _die("Missing dependency psycopg. Install with: python -m pip install psycopg[binary]")
    dsn = _dsn(args)
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            if args.cmd == "context":
                out = cmd_context(conn, args)
            elif args.cmd == "get":
                out = cmd_get(conn, args)
            elif args.cmd == "save":
                out = cmd_save(conn, args)
            else:
                _die("unknown command")
    except Exception as exc:
        _die(f"database failed ({_redact(dsn)}): {exc}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
