"""wxsph_video Plugin - 自动识别短视频链接，解析并发送视频卡片/音乐文件

检测群聊/私聊中的短视频链接（抖音、快手、B站、小红书、微信视频号等 20+ 平台），
默认发可播放视频卡片；如果消息含"音乐/音频/歌曲/MP3"等关键词，则提取音乐发 MP3 文件。
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import aiohttp

from loguru import logger

from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext

API_URL = "https://api.bugpk.com/api/short_videos"

# 深度解析触发：消息以"视频解析"开头
DEEP_PARSE_TRIGGER = re.compile(r"^\s*(视频解析|解析视频|帮我解析|看看这(个|视频).*说了|分析(一下)?这(个|视频))")

# 常见短视频平台域名
PLATFORM_HOSTS = [
    r"v\.douyin\.com", r"www\.douyin\.com", r"iesdouyin\.com",
    r"v\.kuaishou\.com", r"www\.kuaishou\.com", r"kuaishou\.com",
    r"www\.bilibili\.com", r"b23\.tv", r"bilibili\.com",
    r"www\.xiaohongshu\.com", r"xhslink\.com",
    r"weixin\.qq\.com/sph", r"channelsight\.weixin\.qq\.com/sph",
    r"www\.douyin\.com", r"douyin\.com",
    r"www\.pearvideo\.com", r"www\.acfun\.cn",
    r"www\.zhihu\.com", r"www\.weibo\.com",
    r"www\.youtube\.com", r"youtu\.be", r"youtube\.com",
    r"www\.tiktok\.com", r"tiktok\.com",
    r"www\.ixigua\.com", r"www\.haokan\.com",
]
_HOST_PATTERN = "|".join(PLATFORM_HOSTS)
LINK_PATTERN = re.compile(r"https?://(?:[a-zA-Z0-9.-]*?\.)?(?:%s)/[^\s\u4e00-\u9fff，。；！？、]+" % _HOST_PATTERN, re.IGNORECASE)

# 音乐提取关键词
MUSIC_KEYWORDS = re.compile(r"音乐|音频|歌曲|听歌|提取音乐|MP3|mp3|歌$|歌声|原声|BGM|背景音乐|提取音频|提取音乐|只要音乐")
MP3_CONVERT_TRIGGER = re.compile(r"(?:转(?:成|为)?|提取(?:成|为)?)\s*mp3|视频转音频", re.IGNORECASE)


class WxsphVideoPlugin(PluginBase):
    name = "wxsph_video"
    version = "0.4.4"

    def __init__(self) -> None:
        self._send_reply_fn = None
        self._enabled = True
        self._session: aiohttp.ClientSession | None = None
        self._proxy = os.environ.get("WXSPH_VIDEO_PROXY", "").strip() or None
        self._wechat_cfg = None
        self._conversations = None

    async def on_load(self, ctx: PluginContext) -> None:
        self._send_reply_fn = ctx.send_reply
        self._conversations = ctx.conversations
        self._session = aiohttp.ClientSession()
        try:
            settings = getattr(ctx, "settings", None)
            adapters = getattr(settings, "adapters", None) if settings else None
            if adapters and hasattr(adapters, "wechat869"):
                self._wechat_cfg = adapters.wechat869
        except Exception:
            self._wechat_cfg = None
        logger.info("<green>WxsphVideoPlugin</green> 已加载 (v{} 视频+音乐)", self.version)

    async def on_unload(self) -> None:
        if self._session:
            await self._session.close()
        logger.info("<green>WxsphVideoPlugin</green> 已卸载")

    async def on_message(self, message: Message, ctx: PluginContext) -> bool:
        if not self._enabled:
            return False

        content = (message.content or "").strip()
        if not content:
            return False

        if MP3_CONVERT_TRIGGER.search(content):
            return await self._convert_quoted_video(message)

        # 检测链接
        match = LINK_PATTERN.search(content)
        if not match:
            return False

        share_url = match.group(0).rstrip(".,;!?，。；！？、")
        logger.info("WxsphVideoPlugin 检测到链接: {}", share_url)

        # 检测是否深度解析模式
        is_deep_parse = bool(DEEP_PARSE_TRIGGER.match(content))

        # 检查是否要音乐
        want_music = bool(MUSIC_KEYWORDS.search(content))

        # 解析
        title, cover, video_url, music_info = await self._parse(share_url)
        if not video_url:
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text",
                        content=f"解析失败，直接点链接看吧：{share_url}",
                    )
                )
            return True

        if want_music:
            await self._handle_music(message, video_url, title, cover, music_info)
        elif is_deep_parse:
            await self._handle_deep_parse(message, video_url, title, cover, share_url)
        else:
            await self._send_link_card(message, video_url, title, cover)
        return True

    async def _convert_quoted_video(self, message: Message) -> bool:
        attachment = await self._quoted_video_attachment(message)
        if attachment is None:
            await self._send_text(message, "请引用一条视频消息，再发送“转mp3”。")
            return True
        source = str(
            attachment.get("local_path")
            or attachment.get("url")
            or attachment.get("remote_url")
            or ""
        ).strip()
        if not source:
            await self._send_text(message, "引用的视频暂时无法下载，请重新发送后再试。")
            return True
        if source.startswith(("http://", "https://")):
            mp3_path = await self._extract_audio_from_video(source, "引用视频")
        else:
            mp3_path = await self._extract_audio_from_local_video(source)
        if not mp3_path:
            await self._send_text(message, "视频转 MP3 失败，请稍后重试。")
            return True
        filename = str(attachment.get("filename") or "视频")
        title = f"{Path(filename).stem or '视频'}.mp3"
        await self._send_music_file(message, mp3_path, title)
        return True

    async def _quoted_video_attachment(self, message: Message) -> dict | None:
        raw = message.raw if isinstance(message.raw, dict) else {}
        direct = self._video_from_attachments(self._quoted_attachments(raw))
        if direct is not None:
            return direct
        quoted_id = self._quoted_message_id(raw)
        if not quoted_id or self._conversations is None:
            return None
        messages = await self._conversations.get_messages(message.conversation_id, limit=100)
        for item in reversed(messages):
            if item.id != quoted_id:
                continue
            item_raw = item.raw if isinstance(item.raw, dict) else {}
            return self._video_from_attachments(item_raw.get("attachments"))
        return None

    @staticmethod
    def _quoted_attachments(raw: dict) -> list[dict]:
        attachments: list[dict] = []
        for key in ("quote_attachments", "quoted_attachments"):
            value = raw.get(key)
            if isinstance(value, list):
                attachments.extend(item for item in value if isinstance(item, dict))
        quote = raw.get("quote")
        if isinstance(quote, dict) and isinstance(quote.get("attachments"), list):
            attachments.extend(item for item in quote["attachments"] if isinstance(item, dict))
        return attachments

    @staticmethod
    def _quoted_message_id(raw: dict) -> str:
        for value in (raw.get("message_reference"), raw.get("reference"), raw.get("quote")):
            if not isinstance(value, dict):
                continue
            for key in ("message_id", "msg_id", "id"):
                message_id = str(value.get(key) or "").strip()
                if message_id:
                    return message_id
        return str(raw.get("quote_message_id") or "").strip()

    @staticmethod
    def _video_from_attachments(value: object) -> dict | None:
        if not isinstance(value, list):
            return None
        for item in value:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or item.get("type") or "").lower()
            mime = str(item.get("mime") or item.get("content_type") or "").lower()
            filename = str(item.get("filename") or item.get("name") or "").lower()
            if kind == "video" or mime.startswith("video/") or filename.endswith(".mp4"):
                return item
        return None

    async def _send_text(self, message: Message, content: str) -> None:
        if self._send_reply_fn:
            await self._send_reply_fn(
                Reply(
                    platform=message.platform,
                    adapter=message.adapter,
                    conversation_id=message.conversation_id,
                    type="text",
                    content=content,
                    quote_message_id=message.id if message.adapter in {"qq", "telegram"} else None,
                )
            )

    async def _handle_deep_parse(self, message: Message, video_url: str, title: str | None, cover: str | None, share_url: str) -> None:
        """深度解析：下载视频 → 抽关键帧 → 视觉模型分析 → 输出内容总结"""
        try:
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text", content="⏳ 正在解析视频内容，请稍候…",
                    )
                )
            frames = await self._download_and_sample_frames(video_url)
            if not frames:
                if self._send_reply_fn:
                    await self._send_reply_fn(
                        Reply(
                            platform=message.platform, adapter=message.adapter,
                            conversation_id=message.conversation_id,
                            type="text", content=f"❌ 视频下载失败（可能链接已失效或被平台拦截）。\n直链：{video_url}",
                        )
                    )
                return
            summary = await self._analyze_frames(frames, title)
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text", content=summary,
                    )
                )
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 深度解析异常: {}", exc)
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text", content=f"❌ 解析出错：{exc}",
                    )
                )

    async def _download_and_sample_frames(self, video_url: str) -> list[str]:
        """下载视频并抽取关键帧，返回帧图片路径列表"""
        if not self._session:
            return []
        try:
            safe_name = f"deep_{abs(hash(video_url)) % 10000000}.mp4"
            video_path = Path("/tmp/wxsph_deep") / safe_name
            video_path.parent.mkdir(parents=True, exist_ok=True)
            if not video_path.exists():
                async with self._session.get(video_url, proxy=self._proxy, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        return []
                    with open(video_path, "wb") as f:
                        while True:
                            chunk = await resp.content.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
            if video_path.stat().st_size < 1024:
                return []

            # 用 ffprobe 拿时长
            import json as _json
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
                capture_output=True, text=True, timeout=30,
            )
            duration = 0.0
            try:
                info = _json.loads(probe.stdout)
                duration = float(info.get("format", {}).get("duration", "0"))
            except Exception:
                pass
            if duration <= 0:
                duration = 10.0

            # 抽 4 个关键帧：10%, 35%, 65%, 90%
            ratios = [0.1, 0.35, 0.65, 0.9]
            frame_paths = []
            for i, ratio in enumerate(ratios):
                t = duration * ratio
                out = Path("/tmp/wxsph_deep") / f"frame_{safe_name}_{i}.jpg"
                cmd = ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video_path),
                       "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "3", str(out)]
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if out.exists() and out.stat().st_size > 1024:
                    frame_paths.append(str(out))
            # 至少保证有一帧（兜底抽第一帧）
            if not frame_paths:
                out = Path("/tmp/wxsph_deep") / f"frame_{safe_name}_first.jpg"
                subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
                                "-vf", "scale=720:-2", "-q:v", "3", str(out)],
                               capture_output=True, text=True, timeout=30)
                if out.exists() and out.stat().st_size > 1024:
                    frame_paths.append(str(out))
            return frame_paths
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 下载抽帧异常: {}", exc)
            return []

    async def _analyze_frames(self, frame_paths: list[str], title: str | None) -> str:
        """调用视觉模型分析帧图片，返回内容总结"""
        try:
            import base64
            import json as _json
            import re as _re

            # 视觉模型配置（请通过环境变量设置）
            # VISION_API_KEY - API 密钥
            # VISION_BASE_URL - 视觉模型服务地址
            vision_key = os.environ.get("VISION_API_KEY", "your-api-key-here")
            vision_base = os.environ.get("VISION_BASE_URL", "http://your-vision-api:port/v1/chat/completions")

            descs = []
            for path in frame_paths:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                payload = {
                    "model": "glm-4.6v-flash",
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": "这是短视频的一帧画面。请用一两句话客观描述画面里的人物、动作、场景、文字。不要说多余的话。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    ]}],
                    "max_tokens": 300,
                }
                async with self._session.post(vision_base,
                    json=payload, headers={'Authorization': f'Bearer {vision_key}'},
                    proxy=self._proxy,
                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if text:
                        descs.append(text.strip())

            if not descs:
                return f"⚠️ 视频画面解析失败（视觉模型未返回结果）。\n视频标题：{title or '未知'}"

            # 汇总
            joined = "\n".join(f"· {d}" for d in descs)
            return (
                f"🎬 视频解析完成\n"
                f"📌 标题：{title or '未知'}\n\n"
                f"画面内容（按时间顺序）：\n{joined}\n\n"
                f"（以上为视频关键帧的画面识别结果）"
            )
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 视觉分析异常: {}", exc)
            return f"⚠️ 视频画面解析出错：{exc}"

    async def _handle_music(self, message: Message, video_url: str, title: str | None, cover: str | None, music_info: dict | None) -> None:
        """提取音乐：先发10秒语音预览，再发完整 MP3 文件"""
        music_path = None
        if music_info and music_info.get("url"):
            music_url = music_info["url"]
            music_title = music_info.get("title") or title or "音乐"
            music_path = await self._download_music(music_url, music_title)
        else:
            music_title = title or "音乐"
            music_path = await self._extract_audio_from_video(video_url, music_title)

        if not music_path or os.path.getsize(music_path) <= 1024:
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text", content="音乐提取失败。",
                    )
                )
            return

        # 1. 发10秒语音预览（方便试听是不是想要的歌）
        await self._send_voice_preview(message, music_path)
        await asyncio.sleep(0.3)  # 避免消息顺序错乱
        # 2. 发完整 MP3 文件
        await self._send_music_file(message, music_path, music_title or "音乐")

    async def _download_music(self, music_url: str, title: str) -> str | None:
        """下载 MP3 音乐文件"""
        if not self._session:
            return None
        try:
            safe_name = f"music_{abs(hash(music_url)) % 10000000}.mp3"
            local_path = Path("/tmp/wxsph_music") / safe_name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if local_path.exists():
                return str(local_path)
            async with self._session.get(music_url, proxy=self._proxy, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    return None
                with open(local_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            size = os.path.getsize(str(local_path))
            logger.info("WxsphVideoPlugin 音乐下载完成: {} {:.1f}MB", local_path, size / 1024 / 1024)
            return str(local_path)
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 下载音乐异常: {}", exc)
            return None

    async def _extract_audio_from_video(self, video_url: str, title: str) -> str | None:
        """下载视频后 ffmpeg 提取音频为 MP3"""
        if not self._session:
            return None
        try:
            # 下载视频
            safe_name = f"src_{abs(hash(video_url)) % 10000000}.mp4"
            video_path = Path("/tmp/wxsph_music") / safe_name
            video_path.parent.mkdir(parents=True, exist_ok=True)
            if not video_path.exists():
                async with self._session.get(video_url, proxy=self._proxy, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        return None
                    with open(video_path, "wb") as f:
                        while True:
                            chunk = await resp.content.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
            # ffmpeg 提取音频
            mp3_path = video_path.with_suffix(".mp3")
            cmd = ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-acodec", "libmp3lame", "-ab", "128k", str(mp3_path)]
            subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if mp3_path.exists():
                size = os.path.getsize(str(mp3_path))
                logger.info("WxsphVideoPlugin 音频提取完成: {} {:.1f}MB", mp3_path, size / 1024 / 1024)
                return str(mp3_path)
            return None
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 提取音频异常: {}", exc)
            return None

    async def _extract_audio_from_local_video(self, video_path: str) -> str | None:
        """Extract MP3 from a trusted attachment path downloaded by an adapter."""
        try:
            source = Path(video_path)
            if not source.is_file() or source.stat().st_size <= 0:
                return None
            output_dir = Path("/tmp/wxsph_music")
            output_dir.mkdir(parents=True, exist_ok=True)
            mp3_path = output_dir / f"quoted_{abs(hash(str(source.resolve()))) % 10000000}.mp3"
            cmd = [
                "ffmpeg", "-y", "-i", str(source), "-vn",
                "-acodec", "libmp3lame", "-ab", "128k", str(mp3_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode != 0 or not mp3_path.exists() or mp3_path.stat().st_size <= 1024:
                return None
            logger.info("WxsphVideoPlugin 引用视频转 MP3 完成: {}", mp3_path)
            return str(mp3_path)
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 引用视频转 MP3 异常: {}", exc)
            return None

    async def _send_music_file(self, message: Message, file_path: str, title: str) -> None:
        """发送 MP3 音乐文件到对话"""
        try:
            if message.adapter in {"qq", "telegram"}:
                if self._send_reply_fn:
                    await self._send_reply_fn(
                        Reply(
                            platform=message.platform,
                            adapter=message.adapter,
                            conversation_id=message.conversation_id,
                            type="file",
                            content=title,
                            metadata={"path": file_path, "file_name": Path(file_path).name},
                            quote_message_id=message.id,
                        )
                    )
                logger.info("WxsphVideoPlugin 已发送 {} 音乐文件: {}", message.adapter, title[:30])
                return
            from xbot.adapters.wechat869.client import Wechat869Client
            if not self._wechat_cfg:
                return
            client = Wechat869Client(
                host=self._wechat_cfg.host, port=self._wechat_cfg.port,
                admin_key=self._wechat_cfg.admin_key, token_key=self._wechat_cfg.token_key,
                ws_url=self._wechat_cfg.ws_url, timeout_seconds=120,
            )
            await client.send_file_message(message.conversation_id, file_path)
            logger.info("WxsphVideoPlugin 已发送音乐文件: {} - {}", title[:30], file_path)
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 发送音乐文件异常: {}", exc)
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text", content="音乐发送失败，请稍后重试。",
                    )
                )

    async def _send_voice_preview(self, message: Message, music_path: str) -> None:
        """截取前10秒转 AMR 语音发送预览"""
        import subprocess
        from pathlib import Path
        try:
            if message.adapter in {"qq", "telegram"}:
                preview_path = Path("/tmp/wxsph_music") / f"preview_{abs(hash(music_path)) % 10000000}.mp3"
                preview_path.parent.mkdir(parents=True, exist_ok=True)
                cmd = [
                    "ffmpeg", "-y", "-i", music_path, "-t", "10", "-vn",
                    "-acodec", "libmp3lame", "-ab", "64k", str(preview_path),
                ]
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if preview_path.exists() and preview_path.stat().st_size >= 100 and self._send_reply_fn:
                    await self._send_reply_fn(
                        Reply(
                            platform=message.platform,
                            adapter=message.adapter,
                            conversation_id=message.conversation_id,
                            type="voice",
                            content="10秒试听",
                            metadata={"path": str(preview_path), "file_name": preview_path.name},
                            quote_message_id=message.id,
                        )
                    )
                    logger.info("WxsphVideoPlugin 已发送 {} 语音预览 (10s): {}", message.adapter, music_path)
                return
            from xbot.adapters.wechat869.client import Wechat869Client
            if not self._wechat_cfg:
                return
            amr_path = Path("/tmp/wxsph_music") / f"preview_{abs(hash(music_path)) % 10000000}.amr"
            amr_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["ffmpeg", "-y", "-i", music_path, "-t", "10", "-ar", "8000", "-ac", "1", "-ab", "12.2k", "-f", "amr", str(amr_path)]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if not amr_path.exists():
                return
            voice_bytes = amr_path.read_bytes()
            if len(voice_bytes) < 100:
                return
            client = Wechat869Client(
                host=self._wechat_cfg.host, port=self._wechat_cfg.port,
                admin_key=self._wechat_cfg.admin_key, token_key=self._wechat_cfg.token_key,
                ws_url=self._wechat_cfg.ws_url, timeout_seconds=30,
            )
            await client.send_voice_message(message.conversation_id, voice_bytes, format="amr", seconds=10)
            logger.info("WxsphVideoPlugin 已发送语音预览 (10s): {}", music_path)
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 发送语音预览异常: {}", exc)

    async def _send_link_card(self, message: Message, url: str, title: str | None, cover: str | None) -> None:
        """发送视频直链卡片（点击直接播放）"""
        try:
            if message.adapter in {"qq", "telegram"}:
                if self._send_reply_fn:
                    await self._send_reply_fn(
                        Reply(
                            platform=message.platform,
                            adapter=message.adapter,
                            conversation_id=message.conversation_id,
                            type="video",
                            content=title or "视频解析",
                            metadata={"url": url, "file_name": "video.mp4"},
                            quote_message_id=message.id,
                        )
                    )
                logger.info("WxsphVideoPlugin 已发送 {} 视频: {} - {}", message.adapter, (title or "")[:30], url[:60])
                return
            from xbot.adapters.wechat869.client import Wechat869Client
            if not self._wechat_cfg:
                if self._send_reply_fn:
                    await self._send_reply_fn(
                        Reply(
                            platform=message.platform, adapter=message.adapter,
                            conversation_id=message.conversation_id,
                            type="text", content=f"视频：{title}\n{url}",
                        )
                    )
                return
            client = Wechat869Client(
                host=self._wechat_cfg.host, port=self._wechat_cfg.port,
                admin_key=self._wechat_cfg.admin_key, token_key=self._wechat_cfg.token_key,
                ws_url=self._wechat_cfg.ws_url, timeout_seconds=30,
            )
            short_title = (title or "")[:60]
            xml = (
                "<appmsg>"
                f"<title>{escape('视频解析｜' + short_title)}</title>"
                f"<des>{escape('已解析 · 高清直链')}</des>"
                "<action>view</action><type>5</type>"
                f"<url>{escape(url)}</url><lowurl>{escape(url)}</lowurl>"
                f"<dataurl>{escape(url)}</dataurl><lowdataurl>{escape(url)}</lowdataurl>"
                "<appattach><totallen>0</totallen><attachid></attachid><emoticonmd5></emoticonmd5><fileext></fileext></appattach>"
                f"<thumburl>{escape(cover or '')}</thumburl>"
                "</appmsg>"
            )
            result = await client.send_app_message(message.conversation_id, xml, content_type=5)
            is_success = False
            if isinstance(result, list):
                is_success = any(r.get("isSendSuccess") for r in result if isinstance(r, dict))
            elif isinstance(result, dict):
                is_success = result.get("isSendSuccess", False)
            if is_success:
                logger.info("WxsphVideoPlugin 已发送视频卡片: {} - {}", short_title[:30], url[:60])
            else:
                logger.warning("WxsphVideoPlugin 卡片发送未确认成功: {}", result)
                if self._send_reply_fn:
                    await self._send_reply_fn(
                        Reply(
                            platform=message.platform, adapter=message.adapter,
                            conversation_id=message.conversation_id,
                            type="text", content=f"视频：{title}\n{url}",
                        )
                    )
        except Exception as exc:
            logger.exception("WxsphVideoPlugin 发送卡片异常: {}", exc)
            if self._send_reply_fn:
                await self._send_reply_fn(
                    Reply(
                        platform=message.platform, adapter=message.adapter,
                        conversation_id=message.conversation_id,
                        type="text", content=f"视频：{title}\n{url}",
                    )
                )

    async def _parse(self, url: str) -> tuple[str | None, str | None, str | None, dict | None]:
        """调用 BugPk 聚合解析 API，返回 (title, cover_url, video_url, music_info)"""
        if not self._session:
            return None, None, None, None
        try:
            params = {"url": url}
            for attempt in range(3):
                try:
                    async with self._session.get(API_URL, params=params, proxy=self._proxy, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 429:
                            await asyncio.sleep(1)
                            continue
                        if resp.status != 200:
                            return None, None, None, None
                        data = await resp.json()
                        if data.get("code") != 200:
                            return None, None, None, None
                        vd = data.get("data", {})
                        if not isinstance(vd, dict):
                            return None, None, None, None
                        title = vd.get("title") or vd.get("desc") or ""
                        cover = vd.get("cover") or ""
                        video_url = vd.get("url") or ""
                        if not video_url:
                            backups = vd.get("video_backup") or []
                            if isinstance(backups, list) and backups and isinstance(backups[0], dict):
                                video_url = backups[0].get("url") or ""
                        music_info = vd.get("music") or None
                        if isinstance(music_info, dict) and music_info.get("url"):
                            pass
                        else:
                            music_info = None
                        return title, cover, video_url, music_info
                except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as exc:
                    logger.warning("WxsphVideoPlugin API 连接异常({})，重试 ({}/3)", type(exc).__name__, attempt + 1)
                    await asyncio.sleep(2)
            return None, None, None, None
        except Exception as exc:
            logger.exception("WxsphVideoPlugin API 请求异常: {}", exc)
            return None, None, None, None
