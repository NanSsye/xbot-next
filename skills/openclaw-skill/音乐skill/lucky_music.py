#!/usr/bin/env python3
"""
聚合点歌：QQ音乐 + Lucky 双源搜索，直接通过 869 发送音乐卡片
用法：
  python3 lucky_music.py "晴天" --to "wxid_xxx"
  python3 lucky_music.py "晴天" --to "wxid_xxx" --index 3
  python3 lucky_music.py "晴天" --to "xxx@chatroom" --list   # 仅展示列表，不发送
"""
from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# ──────────────────────────────── 配置 ─────────────────────────────────────

LUCKY_API = "https://cer.luckying.love/music/Lucky.php"
QQMUSIC_API = "https://qqmusic.aitell.vip/API/music_open_api.php"
SEND_869_SCRIPT = "/root/.openclaw/skills/微信发送skill/send_869_media.py"
CREDENTIALS_PATH = Path("/home/nans/.openclaw/credentials/wechat-869.json")
TIMEOUT = 15


@dataclass
class SongResult:
    title: str
    singer: str
    source: str
    album: str = ""
    songmid: str = ""
    link: str = ""
    music_url: str = ""
    cover: str = ""
    lyrics: str = ""


# ──────────────────────────────── 工具函数 ────────────────────────────────

def normalize_text(text: str) -> str:
    import re, unicodedata
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = re.sub(r"[\s·・,，.。:：;；!！?？'\"“”‘’《》<>（）()【】\[\]\-_/]+", "", text)
    return text


def parse_lrc_meta(lyric: str) -> dict:
    import re
    meta = {"ar": "", "ti": "", "al": ""}
    if not lyric:
        return meta
    for line in lyric.split("\n"):
        m = re.match(r"\[(\w+):([^\]]+)\]", line.strip())
        if m and m.group(1) in meta and not meta[m.group(1)]:
            meta[m.group(1)] = m.group(2).strip()
    return meta


def clean_lyrics(lyric: str, max_lines: int = 6) -> str:
    if not lyric:
        return "暂无歌词"
    import re
    lines = []
    for line in lyric.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[ti:") or line.startswith("[ar:") or line.startswith("[al:") \
                or line.startswith("[by:") or line.startswith("[offset:"):
            continue
        if "Lucky" in line or "luckying" in line:
            continue
        if re.match(r"^\[\d+:\d+\.\d+\].*", line):
            pos = line.find("]")
            text = line[pos + 1:].strip()
            if text:
                lines.append(text)
        elif line:
            lines.append(line)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines) if lines else "暂无歌词"


def load_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(f"869 配置文件不存在：{CREDENTIALS_PATH}")
    return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))


def send_via_869(
    *,
    to_wxid: str,
    title: str,
    singer: str,
    url: str,
    music_url: str,
    cover_url: str = "",
    lyric: str = "",
) -> dict:
    """通过 send_869_media.py send-music-card 发送音乐卡片。"""
    cmd = [
        sys.executable, SEND_869_SCRIPT,
        "send-music-card",
        "--to", to_wxid,
        "--title", title,
        "--singer", singer,
        "--url", url,
        "--music-url", music_url,
    ]
    if cover_url:
        cmd += ["--cover-url", cover_url]
    if lyric:
        cmd += ["--lyric", lyric]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip()}
    try:
        return json.loads(result.stdout.strip())
    except Exception:
        return {"ok": False, "raw": result.stdout.strip()}


# ──────────────────────────────── HTTP 工具 ──────────────────────────────

def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url: str, params: Optional[dict] = None) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    ctx = create_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"error": str(e)}


# ──────────────────────────────── Lucky 单曲 ─────────────────────────────

def fetch_lucky(song_name: str) -> Optional[SongResult]:
    data = http_get(LUCKY_API, {"Love": song_name})
    if data.get("code") != 200:
        return None
    music_url = data.get("music_url") or data.get("link", "")
    if not music_url:
        return None
    lyric = data.get("lyric", "") or ""
    meta = parse_lrc_meta(lyric)
    title = meta.get("ti", "").strip()
    if not title:
        return None
    return SongResult(
        title=title,
        singer=meta.get("ar") or "未知歌手",
        source="Lucky",
        album=meta.get("al") or "",
        link=music_url,
        music_url=music_url,
        cover=data.get("cover", ""),
        lyrics=lyric,
    )


# ──────────────────────────────── QQ音乐列表 ─────────────────────────────

def fetch_qqmusic_list(song_name: str) -> list[SongResult]:
    data = http_get(QQMUSIC_API, {"msg": song_name})
    if data.get("code") != 0:
        return []
    songs = []
    if data.get("mode") == "list":
        for item in data.get("data", {}).get("songs", []):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            songs.append(SongResult(
                title=name,
                singer=str(item.get("singer") or "未知歌手").strip(),
                album=str(item.get("album") or "").strip(),
                songmid=str(item.get("songmid") or "").strip(),
                source="QQ音乐",
            ))
    return songs


def fetch_qqmusic_detail(query: str) -> Optional[SongResult]:
    data = http_get(QQMUSIC_API, {"msg": query, "n": "1"})
    if data.get("code") != 0:
        return None
    detail = data.get("data", {}).get("detail", {})
    pick = data.get("data", {}).get("picked", {})
    if not isinstance(detail, dict):
        return None

    playable = data.get("data", {}).get("playable_links", [])
    music_url = ""
    for quality in ("flac", "mp3_320", "hq_aac", "mp3_128", "standard_aac"):
        for link in playable or []:
            if isinstance(link, dict) and link.get("quality") == quality and link.get("url"):
                music_url = link["url"]
                break
        if music_url:
            break
    if not music_url:
        music_url = data.get("data", {}).get("best_playable", {}).get("url", "")

    album_obj = detail.get("album_obj", {})
    pmid = album_obj.get("pmid", "") if isinstance(album_obj, dict) else ""
    cover = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{pmid}.jpg" if pmid else ""

    return SongResult(
        title=str(pick.get("name") or detail.get("name") or query),
        singer=str(pick.get("singer") or detail.get("singer") or "未知歌手"),
        album=str(album_obj.get("name") if isinstance(album_obj, dict) else detail.get("album") or ""),
        songmid=str(pick.get("songmid") or detail.get("mid") or ""),
        source="QQ音乐",
        link=music_url,
        music_url=music_url,
        cover=cover,
        lyrics=str(detail.get("lyric_lrc") or ""),
    )


# ──────────────────────────────── 聚合搜索 ───────────────────────────────

def aggregate_search(song_name: str, limit: int = 10) -> list[SongResult]:
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_qq = ex.submit(fetch_qqmusic_list, song_name)
        f_lucky = ex.submit(fetch_lucky, song_name)
        qq_songs = f_qq.result()
        lucky_song = f_lucky.result()

    deduped: list[SongResult] = []
    seen: set[tuple] = set()
    for song in qq_songs:
        key = (normalize_text(song.title), normalize_text(song.singer))
        if key in seen:
            continue
        deduped.append(song)
        seen.add(key)
        if len(deduped) >= limit:
            break

    if lucky_song and len(deduped) < limit:
        key = (normalize_text(lucky_song.title), normalize_text(lucky_song.singer))
        if key not in seen:
            deduped.append(lucky_song)

    return deduped


# ──────────────────────────────── 补全播放链接 ────────────────────────────

def enrich_song(song: SongResult) -> SongResult:
    """如果歌曲没有播放链接，尝试从 QQ音乐详情补全。"""
    if song.music_url and song.link:
        return song
    if song.source == "QQ音乐" and not song.music_url:
        detail = fetch_qqmusic_detail(" ".join(p for p in (song.title, song.singer) if p))
        if detail and detail.music_url:
            return detail
    if song.source == "Lucky" and not song.music_url:
        refreshed = fetch_lucky(song.title)
        if refreshed:
            return refreshed
    return song


# ──────────────────────────────── 格式化输出 ─────────────────────────────

def format_playlist(keyword: str, songs: list[SongResult]) -> str:
    lines = [f"🎵 关键词：{keyword}", f"共找到 {len(songs)} 首\n"]
    for i, s in enumerate(songs, 1):
        url_hint = "✅" if s.music_url else "⚠️"
        lines.append(f"{url_hint} {i}. {s.title} - {s.singer} [{s.source}]")
    return "\n".join(lines)


# ──────────────────────────────── 主入口 ─────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="聚合点歌（QQ音乐 + Lucky），直接通过 869 发音乐卡片")
    parser.add_argument("song", nargs="+", help="歌曲名")
    parser.add_argument("--to", help="发送目标 wxid（群聊以 @chatroom 结尾）")
    parser.add_argument("--limit", type=int, default=10, help="搜索数量，默认10")
    parser.add_argument("--index", type=int, default=1, help="选择第几首，默认1")
    parser.add_argument(
        "--list",
        action="store_true",
        help="仅展示歌单，不发送卡片（用于调试）",
    )
    args = parser.parse_args(argv)

    song_name = " ".join(args.song).strip()
    to_wxid = str(args.to or "").strip()

    songs = aggregate_search(song_name, limit=args.limit)
    if not songs:
        print("未找到相关歌曲")
        return 1

    idx = max(0, min(args.index - 1, len(songs) - 1))
    selected = songs[idx]

    # 补全播放链接
    selected = enrich_song(selected)

    lyric_preview = clean_lyrics(selected.lyrics)

    if args.list:
        print(format_playlist(song_name, songs))
        return 0

    if not to_wxid:
        print("错误：需要 --to 指定发送目标")
        return 1

    if not selected.music_url:
        print(f"⚠️ 第 {args.index} 首无可用播放链接，跳过")
        return 1

    print(f"🎵 正在发送：{selected.title} - {selected.singer}")
    send_result = send_via_869(
        to_wxid=to_wxid,
        title=selected.title,
        singer=selected.singer,
        url=selected.link or selected.music_url,
        music_url=selected.music_url,
        cover_url=selected.cover,
        lyric=lyric_preview,
    )

    result = {
        "keyword": song_name,
        "count": len(songs),
        "selected_index": args.index,
        "song": asdict(selected),
        "lyric_preview": lyric_preview,
        "send_result": send_result,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))