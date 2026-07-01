# xbot WeChat Profile Skill

Use this skill when you need to create or update a WeChat user profile/persona and tags from xbot chat history.

## Data source

PostgreSQL tables:

- `conversation_messages`
- `message_attachments`
- `contacts`
- `user_profiles`

Credentials:

```bash
~/.openclaw/credentials/xbot_db.json
```

Override:

```bash
XBOT_HISTORY_DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DB
```

## Workflow

1. Read recent user context:

```bash
python profile_user.py context --user wxid_xxx --conversation "47440917520@chatroom" --limit 80
```

First profile can read a larger range:

```bash
python profile_user.py context --user wxid_xxx --conversation "47440917520@chatroom" --limit 300
```

Incremental daily update should read only new messages and include the previous saved profile:

```bash
python profile_user.py context \
  --user wxid_xxx \
  --conversation "wechat:wechat869:group:47440917520@chatroom" \
  --since "2026-06-30 00:00:00" \
  --until "2026-07-01 00:00:00" \
  --include-profile \
  --limit 300
```

2. Let AI write a concise persona and tags from the returned messages.
   - First time: use all returned messages.
   - Incremental update: use `previous_profile` plus only the returned new messages/images.

3. Save the AI-written result:

```bash
python profile_user.py save --user wxid_xxx --conversation "47440917520@chatroom" --summary "画像文本" --tags "活跃,技术,群管理"
```

4. Verify:

```bash
python profile_user.py get --user wxid_xxx --conversation "47440917520@chatroom"
```

## Rules

- Do not invent tags/profile without chat evidence.
- Do not re-read full history for incremental updates; use `--since` from last `updated_at`.
- Keep tags short, comma-separated, 3-8 tags.
- Summary should be natural Chinese, 80-300 chars.
- Do not expose database URL, password, IP, or internal table details to WeChat users.
- Only `save` writes `user_profiles`; all other actions are read-only.
