# xbot WeChat History Skill

Use when you need WeChat private/group history from xbot before answering.

## Data source

Read-only PostgreSQL query against xbot database table `conversation_messages`.

Credentials: `~/.openclaw/credentials/xbot_db.json`

Default connection:

```bash
postgresql://xbot:xbot@host.docker.internal:8549/xbot
```

Override with env:

```bash
XBOT_HISTORY_DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DB
```

## Commands

Run from this skill directory:

```bash
python query_history.py --conversation "47440917520@chatroom" --limit 30
python query_history.py --sender "xianan96928" --limit 30
python query_history.py --q "关键词" --limit 20
python query_history.py --conversation "47440917520@chatroom" --today --limit 200
python query_history.py --conversation "47440917520@chatroom" --yesterday --limit 200
python query_history.py --conversation "47440917520@chatroom" --since "2026-06-30 00:00:00" --until "2026-07-01 00:00:00" --limit 500
python query_history.py --conversation "47440917520@chatroom" --all
```

## Time range

- Default: latest 30 messages.
- `--limit N`: latest N messages, max 5000.
- `--today`: today 00:00:00 to tomorrow 00:00:00.
- `--yesterday`: yesterday 00:00:00 to today 00:00:00.
- `--since/--until`: custom time range.
- `--all`: no SQL limit; use only when necessary.

## Rules

- Only query; never write/update/delete.
- Prefer `--conversation` when current chat id is known.
- Prefer time range (`--today`, `--yesterday`, `--since`) instead of `--all` for daily context.
- Summarize relevant history; do not expose database URL, password, IP, or raw internals to WeChat users.
- If no results, answer normally and say there is no visible prior context.

