#!/usr/bin/env python3
"""Read-only xbot WeChat history query helper for OpenClaw/Hermes skills."""
from __future__ import annotations

import argparse
import json
import os
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
from datetime import datetime, timedelta
from urllib.parse import urlparse

try:
    import psycopg
except Exception:
    psycopg = None

DEFAULT_DSN = "postgresql://xbot:xbot@host.docker.internal:8549/xbot"

CREDENTIALS_PATH = os.path.expanduser("~/.openclaw/credentials/xbot_db.json")

def _load_creds_dsn() -> str | None:
    """Read database_url from credentials file if it exists."""
    try:
        import json as _json
        cred_path = os.path.expanduser("~/.openclaw/credentials/xbot_db.json")
        if os.path.exists(cred_path):
            with open(cred_path) as f:
                data = _json.load(f)
            return data.get("database_url")
    except Exception:
        pass
    return None


def _die(msg: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def _safe_limit(value: int) -> int:
    return max(1, min(int(value or 30), 5000))


def _day_range(days_ago: int) -> tuple[str, str]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days_ago)
    end = start + timedelta(days=1)
    return start.isoformat(sep=" ", timespec="seconds"), end.isoformat(sep=" ", timespec="seconds")


def _redact_dsn(dsn: str) -> str:
    try:
        p = urlparse(dsn)
        host = p.hostname or "host"
        port = f":{p.port}" if p.port else ""
        db = (p.path or "/").lstrip("/")
        return f"postgresql://***:***@{host}{port}/{db}"
    except Exception:
        return "postgresql://***"


def main() -> int:
    ap = argparse.ArgumentParser(description="Query xbot WeChat chat history")
    ap.add_argument("--database-url", default=os.environ.get("XBOT_HISTORY_DATABASE_URL") or _load_creds_dsn() or DEFAULT_DSN)
    ap.add_argument("--conversation", help="conversation_id/raw chatroom wxid, supports contains match")
    ap.add_argument("--sender", help="sender wxid, exact match")
    ap.add_argument("--q", help="keyword search in content/raw_json")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--since", help="created_at >= this time, e.g. '2026-06-30 00:00:00'")
    ap.add_argument("--until", help="created_at < this time, e.g. '2026-07-01 00:00:00'")
    ap.add_argument("--today", action="store_true", help="query today from 00:00:00 local time")
    ap.add_argument("--yesterday", action="store_true", help="query yesterday from 00:00:00 to today 00:00:00")
    ap.add_argument("--all", action="store_true", help="do not apply LIMIT; use carefully")
    args = ap.parse_args()

    if psycopg is None:
        _die("Missing dependency psycopg. Install with: python -m pip install psycopg[binary]")

    if args.today and args.yesterday:
        _die("--today and --yesterday cannot be used together")
    if args.today:
        args.since, args.until = _day_range(0)
    if args.yesterday:
        args.since, args.until = _day_range(1)
    limit = _safe_limit(args.limit)
    where = ["platform = 'wechat'"]
    params: list[object] = []

    if args.conversation:
        where.append("conversation_id ILIKE %s")
        params.append(f"%{args.conversation}%")
    if args.sender:
        where.append("sender_id = %s")
        params.append(args.sender)
    if args.q:
        where.append("(content ILIKE %s OR raw_json ILIKE %s)")
        like = f"%{args.q}%"
        params.extend([like, like])
    if args.since:
        where.append("created_at >= %s")
        params.append(args.since)
    if args.until:
        where.append("created_at < %s")
        params.append(args.until)

    sql = f"""
        SELECT conversation_id, message_id, sender_id, sender_name, type, content, created_at
        FROM conversation_messages
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
    """
    if not args.all:
        sql += " LIMIT %s"
        params.append(limit)

    try:
        with psycopg.connect(args.database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception as exc:
        _die(f"query failed ({_redact_dsn(args.database_url)}): {exc}")

    items = []
    for row in reversed(rows):
        conversation_id, message_id, sender_id, sender_name, typ, content, created_at = row
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat(sep=" ", timespec="seconds")
        items.append({
            "time": str(created_at),
            "conversation_id": conversation_id,
            "message_id": message_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "type": typ,
            "content": content or "",
        })

    print(json.dumps({
        "ok": True,
        "count": len(items),
        "limited": not args.all,
        "limit": None if args.all else limit,
        "since": args.since,
        "until": args.until,
        "items": items,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



