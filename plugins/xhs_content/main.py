from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from dotenv import dotenv_values
from loguru import logger

from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext

XHS_LINK = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)*(?:xiaohongshu\.com|xhslink\.com|xhslink\.cn)/[^\s\u4e00-\u9fff，。；！？、]+",
    re.IGNORECASE,
)
ALLOWED_LINK_HOSTS = {"xiaohongshu.com", "xhslink.com", "xhslink.cn"}
FINAL_LINK_HOSTS = {"xiaohongshu.com"}
MEDIA_HOSTS = {"xiaohongshu.com", "xhscdn.com"}
REDIRECT_CODES = {301, 302, 303, 307, 308}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36"
)


class XhsParseError(RuntimeError):
    pass


class XhsConfigError(XhsParseError):
    pass


class XhsContentPlugin(PluginBase):
    name = "xhs_content"
    version = "0.1.0"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._send_reply = None
        self._data_dir = Path("data/plugins/xhs_content")
        self._base_url = ""
        self._api_token = ""
        self._timeout_seconds = 30.0
        self._max_images = 9
        self._max_image_bytes = 20 * 1024 * 1024
        self._max_total_image_bytes = 80 * 1024 * 1024
        self._max_video_bytes = 200 * 1024 * 1024
        self._qq_allow_active_messages = False

    async def on_load(self, ctx: PluginContext) -> None:
        self._send_reply = ctx.send_reply
        self._data_dir = ctx.data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._base_url = self._setting("XHS_DOWNLOADER_BASE_URL", "http://host.docker.internal:5556").rstrip("/")
        self._api_token = self._setting("XHS_DOWNLOADER_API_TOKEN", "")
        self._timeout_seconds = self._float_setting("XHS_DOWNLOADER_TIMEOUT_SECONDS", 30.0, minimum=3.0, maximum=120.0)
        self._max_images = int(self._float_setting("XHS_PLUGIN_MAX_IMAGES", 9, minimum=1, maximum=20))
        self._max_image_bytes = int(self._float_setting("XHS_PLUGIN_MAX_IMAGE_BYTES", 20 * 1024 * 1024, minimum=1024, maximum=50 * 1024 * 1024))
        self._max_total_image_bytes = int(self._float_setting("XHS_PLUGIN_MAX_TOTAL_IMAGE_BYTES", 80 * 1024 * 1024, minimum=1024, maximum=300 * 1024 * 1024))
        self._max_video_bytes = int(self._float_setting("XHS_PLUGIN_MAX_VIDEO_BYTES", 200 * 1024 * 1024, minimum=1024, maximum=500 * 1024 * 1024))
        adapters = getattr(getattr(ctx, "settings", None), "adapters", None)
        qq = getattr(adapters, "qq", None)
        self._qq_allow_active_messages = bool(getattr(qq, "allow_active_messages", False))
        self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        logger.info(
            "XhsContentPlugin 已加载: configured={} max_images={}",
            bool(self._base_url and self._api_token),
            self._max_images,
        )

    async def on_unload(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def on_message(self, message: Message, ctx: PluginContext) -> bool:
        match = XHS_LINK.search(message.content or "")
        if not match:
            return False
        started = time.monotonic()
        work_id = "unknown"
        try:
            source_url = self._validate_url(match.group(0).rstrip(".,;!?，。；！？、"), ALLOWED_LINK_HOSTS)
            resolved_url = await self._resolve_share_url(source_url)
            data = await self._parse_detail(resolved_url)
            work_id = self._work_id(data)
            await self._render(message, data, work_id)
            logger.info(
                "XhsContentPlugin 处理成功: work_id={} type={} elapsed_ms={}",
                work_id,
                self._text(data.get("作品类型")) or "unknown",
                int((time.monotonic() - started) * 1000),
            )
        except XhsConfigError:
            logger.warning("XhsContentPlugin 配置不可用: work_id={}", work_id)
            await self._send_text(message, "小红书解析服务还没有配置好，请联系管理员。")
        except XhsParseError as exc:
            logger.warning(
                "XhsContentPlugin 解析失败: work_id={} reason={} elapsed_ms={}",
                work_id,
                self._safe_error(exc),
                int((time.monotonic() - started) * 1000),
            )
            await self._send_text(message, str(exc) or "小红书内容解析失败，请稍后再试。")
        except Exception as exc:
            logger.warning(
                "XhsContentPlugin 服务异常: work_id={} error_type={} elapsed_ms={}",
                work_id,
                type(exc).__name__,
                int((time.monotonic() - started) * 1000),
            )
            await self._send_text(message, "小红书解析服务暂时不可用，请稍后再试。")
        return True

    async def _parse_detail(self, url: str) -> dict[str, Any]:
        if not self._base_url or not self._api_token:
            raise XhsConfigError("小红书解析服务未配置")
        session = self._require_session()
        endpoint = f"{self._base_url}/xhs/detail"
        headers = {"Authorization": f"Bearer {self._api_token}", "Content-Type": "application/json"}
        for attempt in range(2):
            try:
                async with session.post(
                    endpoint,
                    headers=headers,
                    json={"url": url, "download": False, "skip": False},
                    timeout=aiohttp.ClientTimeout(total=self._timeout_seconds),
                    allow_redirects=False,
                ) as response:
                    status = response.status
                    try:
                        payload = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        raise XhsParseError("小红书解析服务返回异常") from None
                    if status == 401:
                        raise XhsConfigError("小红书解析服务鉴权失败")
                    if status == 422:
                        raise XhsParseError("小红书链接格式不正确")
                    if status == 429 or status in {500, 502, 503, 504}:
                        if attempt == 0:
                            await asyncio.sleep(0.6)
                            continue
                        raise XhsParseError("小红书解析服务暂时繁忙，请稍后再试")
                    if status != 200:
                        raise XhsParseError("小红书解析服务暂时不可用，请稍后再试")
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(data, dict) or not data or not self._valid_work_id(data.get("作品ID")):
                        raise XhsParseError("这个小红书链接暂时无法解析，可能已失效或受平台限制。")
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(0.6)
                    continue
                raise XhsParseError("小红书解析服务暂时不可用，请稍后再试") from None
        raise XhsParseError("小红书解析服务暂时不可用，请稍后再试")

    async def _resolve_share_url(self, value: str) -> str:
        current = self._validate_url(value, ALLOWED_LINK_HOSTS)
        if not self._host_allowed(urlparse(current).hostname, {"xhslink.cn"}):
            return current
        session = self._require_session()
        for _ in range(3):
            await self._assert_public_dns(current)
            try:
                async with session.get(
                    current,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=min(10.0, self._timeout_seconds)),
                ) as response:
                    if response.status not in REDIRECT_CODES:
                        break
                    location = response.headers.get("Location")
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise XhsParseError("小红书短链接展开失败，请稍后再试") from None
            if not location:
                break
            current = self._validate_url(urljoin(current, location), ALLOWED_LINK_HOSTS)
            if self._host_allowed(urlparse(current).hostname, FINAL_LINK_HOSTS):
                await self._assert_public_dns(current)
                return current
        raise XhsParseError("短链接没有跳转到有效的小红书作品")

    async def _render(self, message: Message, data: dict[str, Any], work_id: str) -> None:
        formatted_text = self._format_text(message.platform, data)
        is_telegram = message.adapter == "telegram"
        if not is_telegram:
            await self._send_text(message, formatted_text)
        media_urls = self._media_urls(data)
        work_type = self._text(data.get("作品类型")).lower()
        is_video = "视频" in work_type
        caption, continuation = self._telegram_media_text(data) if is_telegram else ("", "")
        if is_video:
            if not media_urls:
                if is_telegram:
                    await self._send_text(message, formatted_text)
                await self._send_text(message, "视频地址暂时不可用。")
                return
            path = await self._download_media(media_urls[0], work_id, 0, kind="video")
            if path:
                await self._send_media(message, "video", path, quote=True, caption=caption)
                if continuation:
                    await self._send_text(message, continuation)
            elif is_telegram:
                await self._send_text(message, formatted_text)
            return

        total = 0
        sent = 0
        qq_passive_left = 4
        telegram_paths: list[Path] = []
        for index, url in enumerate(media_urls[: self._max_images]):
            path = await self._download_media(url, work_id, index, kind="image")
            if not path:
                continue
            size = path.stat().st_size
            if total + size > self._max_total_image_bytes:
                path.unlink(missing_ok=True)
                break
            total += size
            if message.adapter == "qq":
                path = await asyncio.to_thread(self._qq_compatible_image, path)
            if is_telegram:
                telegram_paths.append(path)
                continue
            quote = True
            if message.adapter == "qq":
                quote = qq_passive_left > 0
                qq_passive_left -= 1
                if not quote and not self._qq_allow_active_messages:
                    break
            await self._send_media(
                message,
                "image",
                path,
                quote=quote if not is_telegram else sent == 0,
                caption=caption if is_telegram and sent == 0 else "",
            )
            sent += 1
        if is_telegram and telegram_paths:
            await self._send_media_group(message, telegram_paths, caption=caption)
            sent = len(telegram_paths)
        if is_telegram and sent == 0:
            await self._send_text(message, formatted_text)
        elif is_telegram and continuation:
            await self._send_text(message, continuation)
        if media_urls and sent == 0:
            await self._send_text(message, "图片暂时下载失败，正文已经发出。")

    def _format_text(self, platform: str, data: dict[str, Any]) -> str:
        title = self._text(data.get("作品标题")) or "未命名笔记"
        author = self._text(data.get("作者昵称")) or "未知作者"
        description = self._text(data.get("作品描述")) or "（没有正文）"
        tags = self._string_list(data.get("作品标签"))
        max_description = 1300 if platform == "qq" else 3200
        if len(description) > max_description:
            description = f"{description[:max_description]}\n……正文已截断"
        if platform == "telegram":
            title = self._telegram_markdown(title)
            author = self._telegram_markdown(author)
            description = self._telegram_markdown(description)
            tags = [self._telegram_markdown(tag) for tag in tags]
        statistics = " · ".join(
            value for value in (
                self._stat("赞", data.get("点赞数量")),
                self._stat("藏", data.get("收藏数量")),
                self._stat("评", data.get("评论数量")),
                self._stat("享", data.get("分享数量")),
            ) if value
        )
        lines = [f"*📕 {title}*" if platform == "telegram" else f"📕 {title}", f"👤 {author}"]
        if tags:
            lines.append("🏷️ " + "  ".join(f"#{tag.lstrip('#')}" for tag in tags[:12]))
        if published := self._text(data.get("发布时间")):
            lines.append(f"🕒 {published}")
        if statistics:
            lines.append(f"📊 {statistics}")
        lines.extend(("", description))
        return "\n".join(lines)

    def _telegram_media_text(self, data: dict[str, Any]) -> tuple[str, str]:
        title = self._text(data.get("作品标题")) or "未命名笔记"
        author = self._text(data.get("作者昵称")) or "未知作者"
        description = self._text(data.get("作品描述")) or "（没有正文）"
        tags = self._string_list(data.get("作品标签"))
        statistics = " · ".join(
            value for value in (
                self._stat("赞", data.get("点赞数量")),
                self._stat("藏", data.get("收藏数量")),
                self._stat("评", data.get("评论数量")),
                self._stat("享", data.get("分享数量")),
            ) if value
        )
        lines = [
            f"*📕 {self._telegram_markdown(title[:60])}*",
            f"👤 {self._telegram_markdown(author[:30])}",
        ]
        if tags:
            lines.append("🏷️ " + "  ".join(
                f"#{self._telegram_markdown(tag.lstrip('#')[:12])}" for tag in tags[:4]
            ))
        if statistics:
            lines.append(f"📊 {self._telegram_markdown(statistics)}")
        if published := self._text(data.get("发布时间")):
            lines.append(f"🕒 {self._telegram_markdown(published[:40])}")
        header = "\n".join(lines)
        continuation_hint = "\n……完整正文见下一条"
        available = max(0, 1000 - len(header) - 2)
        escaped_parts: list[str] = []
        escaped_length = 0
        consumed = 0
        for character in description:
            escaped = self._telegram_markdown(character)
            reserve = len(continuation_hint) if consumed + 1 < len(description) else 0
            if escaped_length + len(escaped) + reserve > available:
                break
            escaped_parts.append(escaped)
            escaped_length += len(escaped)
            consumed += 1
        caption = f"{header}\n\n{''.join(escaped_parts)}"
        if consumed < len(description):
            caption += continuation_hint
        if consumed >= len(description):
            return caption, ""
        remainder = description[consumed:3200]
        if len(description) > 3200:
            remainder += "\n……正文已截断"
        return caption, f"*正文（续）*\n{self._telegram_markdown(remainder)}"

    async def _send_media_group(self, message: Message, paths: list[Path], *, caption: str) -> None:
        first = paths[0]
        await self._safe_send(Reply(
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            type="image",
            content=str(first),
            metadata={
                "path": str(first),
                "paths": [str(path) for path in paths[:10]],
                "caption": caption,
                "parse_mode": "Markdown",
            },
            quote_message_id=message.id,
        ))

    @staticmethod
    def _telegram_markdown(value: str) -> str:
        return re.sub(r"([\\_*`\[\]])", r"\\\1", str(value or ""))

    async def _download_media(self, value: str, work_id: str, index: int, *, kind: str) -> Path | None:
        current = self._validate_url(value, MEDIA_HOSTS)
        session = self._require_session()
        limit = self._max_video_bytes if kind == "video" else self._max_image_bytes
        for _ in range(4):
            await self._assert_public_dns(current)
            try:
                async with session.get(
                    current,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=self._timeout_seconds),
                ) as response:
                    if response.status in REDIRECT_CODES:
                        location = response.headers.get("Location")
                        if not location:
                            return None
                        current = self._validate_url(urljoin(current, location), MEDIA_HOSTS)
                        continue
                    if response.status != 200:
                        return None
                    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                    expected = "video/" if kind == "video" else "image/"
                    if not content_type.startswith(expected):
                        return None
                    length = response.headers.get("Content-Length")
                    if length and int(length) > limit:
                        return None
                    suffix = self._media_suffix(content_type, kind)
                    directory = self._data_dir / self._safe_work_id(work_id)
                    directory.mkdir(parents=True, exist_ok=True)
                    target = directory / f"{kind}-{index + 1}{suffix}"
                    temporary = target.with_suffix(target.suffix + ".part")
                    total = 0
                    try:
                        with temporary.open("wb") as stream:
                            async for chunk in response.content.iter_chunked(256 * 1024):
                                total += len(chunk)
                                if total > limit:
                                    raise XhsParseError(f"小红书{('视频' if kind == 'video' else '图片')}超过大小限制")
                                stream.write(chunk)
                        temporary.replace(target)
                        return target
                    except Exception:
                        temporary.unlink(missing_ok=True)
                        raise
            except XhsParseError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
                return None
        return None

    async def _send_text(self, message: Message, content: str) -> None:
        await self._safe_send(Reply(
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            type="markdown" if message.adapter == "telegram" else "text",
            content=content,
            quote_message_id=message.id if message.adapter in {"qq", "telegram"} else None,
        ))

    async def _send_media(self, message: Message, kind: str, path: Path, *, quote: bool, caption: str = "") -> None:
        await self._safe_send(Reply(
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            type=kind,
            content=str(path),
            metadata={
                "path": str(path),
                "file_name": path.name,
                "caption": caption,
                "parse_mode": "Markdown" if caption and message.adapter == "telegram" else None,
            },
            quote_message_id=message.id if quote and message.adapter in {"qq", "telegram"} else None,
        ))

    async def _safe_send(self, reply: Reply) -> None:
        if self._send_reply is None:
            return
        try:
            await self._send_reply(reply)
        except Exception as exc:
            logger.warning("XhsContentPlugin 发送失败: adapter={} type={} error_type={}", reply.adapter, reply.type, type(exc).__name__)

    def _media_urls(self, data: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("下载地址", "图片列表", "图片地址", "视频地址"):
            self._collect_urls(data.get(key), values)
        unique: list[str] = []
        for value in values:
            if value not in unique:
                unique.append(value)
        return unique

    def _collect_urls(self, value: Any, output: list[str]) -> None:
        if isinstance(value, str):
            if value.startswith(("http://", "https://")):
                output.append(value)
            return
        if isinstance(value, list):
            for item in value:
                self._collect_urls(item, output)
            return
        if isinstance(value, dict):
            for item in value.values():
                self._collect_urls(item, output)

    async def _assert_public_dns(self, value: str) -> None:
        host = urlparse(value).hostname or ""
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
        except OSError:
            raise XhsParseError("小红书资源域名解析失败") from None
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified or address.is_multicast:
                raise XhsParseError("小红书链接跳转到了不安全的地址")

    @classmethod
    def _validate_url(cls, value: str, allowed_hosts: set[str]) -> str:
        value = str(value or "").strip()
        if not value or len(value) > 2048:
            raise XhsParseError("小红书链接无效")
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError:
            raise XhsParseError("小红书链接无效") from None
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or port not in {None, 80, 443}
            or not cls._host_allowed(parsed.hostname, allowed_hosts)
        ):
            raise XhsParseError("小红书链接无效")
        return value

    @staticmethod
    def _host_allowed(host: str | None, allowed: set[str]) -> bool:
        normalized = (host or "").lower().rstrip(".")
        return any(normalized == item or normalized.endswith(f".{item}") for item in allowed)

    @staticmethod
    def _valid_work_id(value: Any) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,128}", str(value or "").strip()))

    @classmethod
    def _work_id(cls, data: dict[str, Any]) -> str:
        value = str(data.get("作品ID") or "").strip()
        if not cls._valid_work_id(value):
            raise XhsParseError("小红书作品 ID 无效")
        return value

    @staticmethod
    def _safe_work_id(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", value)[:128] or "unknown"

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return ""
        return str(value).strip()

    @classmethod
    def _string_list(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [text for item in value if (text := cls._text(item))]
        text = cls._text(value)
        return [item.strip() for item in re.split(r"[,，\s]+", text) if item.strip()] if text else []

    @classmethod
    def _stat(cls, label: str, value: Any) -> str:
        text = cls._text(value)
        return f"{label}{text}" if text else ""

    @staticmethod
    def _media_suffix(content_type: str, kind: str) -> str:
        if kind == "video":
            return ".mp4"
        return {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type, ".jpg")

    @staticmethod
    def _qq_compatible_image(path: Path) -> Path:
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            return path
        try:
            from PIL import Image

            target = path.with_suffix(".jpg")
            temporary = target.with_suffix(".jpg.part")
            with Image.open(path) as image:
                image.convert("RGB").save(temporary, format="JPEG", quality=92)
            temporary.replace(target)
            return target
        except Exception as exc:
            raise XhsParseError("小红书图片格式暂时无法发送到 QQ") from exc

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = str(exc).replace("\r", " ").replace("\n", " ")[:160]
        return text or type(exc).__name__

    @staticmethod
    def _setting(name: str, default: str) -> str:
        value = os.getenv(name)
        if value is not None:
            return value.strip()
        try:
            dotenv = dotenv_values(Path.cwd() / ".env")
            configured = dotenv.get(name)
            return str(configured).strip() if configured is not None else default
        except Exception:
            return default

    @classmethod
    def _float_setting(cls, name: str, default: float, *, minimum: float, maximum: float) -> float:
        try:
            value = float(cls._setting(name, str(default)))
        except ValueError:
            value = default
        return max(minimum, min(value, maximum))

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise XhsParseError("小红书解析服务暂时不可用，请稍后再试")
        return self._session
