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
from datetime import datetime
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
    return max(1, min(int(value or 30), 200))


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
    args = ap.parse_args()

    if psycopg is None:
        _die("Missing dependency psycopg. Install with: python -m pip install psycopg[binary]")

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

    sql = f"""
        SELECT conversation_id, message_id, sender_id, sender_name, type, content, created_at
        FROM conversation_messages
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT %s
    """
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

    print(json.dumps({"ok": True, "count": len(items), "items": items}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



