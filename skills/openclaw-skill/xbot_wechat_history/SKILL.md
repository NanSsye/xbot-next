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
```

## Rules

- Only query; never write/update/delete.
- Prefer `--conversation` when current chat id is known.
- Summarize relevant history; do not expose database URL, password, IP, or raw internals to WeChat users.
- If no results, answer normally and say there is no visible prior context.
