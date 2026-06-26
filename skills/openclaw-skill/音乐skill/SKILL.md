---
name: lucky-music
description: 聚合点歌（QQ音乐 + Lucky），通过 869 直接发送微信音乐卡片，支持 --to 指定发送目标
allowed-tools: Bash(python3:*) Read Write
---

# lucky-music（聚合版）

双源搜索（QQ音乐列表 + Lucky 单曲兜底），通过 869 协议直接发送微信音乐卡片。

## 核心脚本

```
/root/.openclaw/skills/音乐skill/lucky_music.py
```

## 搜索 API

- **Lucky：** `https://cer.luckying.love/music/Lucky.php?Love=<歌名>`
- **QQ音乐：** `https://qqmusic.aitell.vip/API/music_open_api.php?msg=<歌名>`

## 用法

```bash
# 搜索并直接发送音乐卡片（默认选第1首）
python3 lucky_music.py "晴天" --to "wxid_xxx"

# 选择歌单中第3首发送
python3 lucky_music.py "周杰伦" --to "xxx@chatroom" --index 3

# 仅展示歌单（不发送，用于调试）
python3 lucky_music.py "晴天" --list

# 指定搜索数量
python3 lucky_music.py "告白气球" --to "wxid_xxx" --limit 5
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `song` | 歌曲名（位置参数） |
| `--to` | 发送目标 wxid（群聊以 `@chatroom` 结尾） |
| `--index` | 选择歌单中第几首，默认 1 |
| `--limit` | 搜索数量，默认 10 |
| `--list` | 仅打印歌单，不发送 |

## 流程

1. 并发请求 QQ音乐列表 + Lucky 单曲，合并去重
2. 用户指定 `--index` 或默认选第 1 首
3. 自动补全播放链接（QQ音乐详情 → Lucky 兜底）
4. 通过 869 的 `send-music-card` 子命令发送微信音乐卡片

## 发送依赖

- 869 配置：`/home/nans/.openclaw/credentials/wechat-869.json`
- 发送脚本：`/root/.openclaw/skills/微信发送skill/send_869_media.py send-music-card`

## 支持触发词

- 点歌 \<歌名\>
- 来一首 \<歌名\>
- 放歌 \<歌名\>
- 听一下 \<歌名\>
- 我想听 \<歌名\>