from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

import aiohttp

from xbot.core.config import QQAdapterConfig
from xbot.core.proxy import create_aiohttp_session


class QQBotApiError(RuntimeError):
    """An OpenAPI or Gateway error with a safe, small diagnostic payload."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        err_code: int | str | None = None,
        trace_id: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.err_code = err_code
        self.trace_id = trace_id


_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}
_MEDIA_TYPES = {"image": 1, "video": 2, "voice": 3, "file": 4}
_MEDIA_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "video": {".mp4"},
    "voice": {".silk", ".mp3", ".wav", ".ogg"},
}


def _assert_public_url(value: str) -> str:
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise QQBotApiError("媒体 URL 必须是 http(s) 地址")
    host = parsed.hostname.lower().rstrip(".")
    if host in _PRIVATE_HOSTNAMES or host.endswith(".local"):
        raise QQBotApiError("媒体 URL 不允许访问 localhost 或内网主机")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified or address.is_multicast):
        raise QQBotApiError("媒体 URL 不允许访问私网地址")
    if address is None:
        # A DNS name can resolve to a private address even when the URL does
        # not contain a literal IP.  Resolve all returned addresses and block
        # private/loopback/link-local results.  DNS failures are left to the
        # HTTP request (useful for deterministic fake/test hosts).
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError:
            infos = []
        for info in infos:
            try:
                resolved = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if resolved.is_private or resolved.is_loopback or resolved.is_link_local or resolved.is_reserved or resolved.is_unspecified or resolved.is_multicast:
                raise QQBotApiError("媒体 URL 解析到私网地址")
    return parsed.geturl()


def _clean_filename(value: str, fallback: str = "media.bin") -> str:
    name = Path(str(value or "")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name[:180] or fallback)


class QQBotClient:
    """Async client for the official QQ Bot v2 OpenAPI.

    The client deliberately keeps transport details in one place: callers can
    use ``request`` for small API calls, while media helpers implement the
    prepare/part-finish/files flow required by the QQ API.  No token, URL
    query, message body or file_info is logged here.
    """

    def __init__(self, config: QQAdapterConfig, *, session: aiohttp.ClientSession | None = None) -> None:
        self.config = config
        self._session = session
        self._owns_session = session is None
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def access_token(self, *, force: bool = False) -> str:
        if not force and self._token_is_valid():
            return self._access_token
        async with self._token_lock:
            if not force and self._token_is_valid():
                return self._access_token
            if not self.config.app_id or not self.config.client_secret:
                raise QQBotApiError("QQ AppID 或 AppSecret 未配置")
            session = await self._get_session()
            try:
                async with session.post(
                    self.config.token_url,
                    json={"appId": self.config.app_id, "clientSecret": self.config.client_secret},
                ) as response:
                    payload = await self._response_json(response)
                    if response.status >= 400:
                        raise self._payload_error(payload, status=response.status)
            except QQBotApiError:
                raise
            except (TimeoutError, aiohttp.ClientError) as exc:
                raise QQBotApiError(f"获取 QQ Access Token 失败: {exc}") from exc
            token = str(payload.get("access_token") or "")
            if not token:
                raise self._payload_error(payload, message="QQ Access Token 响应缺少 access_token")
            try:
                expires_in = max(60, int(payload.get("expires_in") or 7200))
            except (TypeError, ValueError):
                expires_in = 7200
            self._access_token = token
            self._access_token_expires_at = time.monotonic() + max(30, expires_in - 60)
            return token

    async def gateway_url(self) -> str:
        if self.config.gateway_url:
            return self.config.gateway_url
        payload = await self.request("GET", "/gateway")
        url = str(payload.get("url") or "")
        if not url:
            raise QQBotApiError("QQ Gateway 响应缺少 WebSocket 地址")
        return url

    async def websocket(self, url: str) -> aiohttp.ClientWebSocketResponse:
        session = await self._get_session()
        return await session.ws_connect(
            url,
            heartbeat=None,
            autoping=True,
            receive_timeout=None,
            max_msg_size=8 * 1024 * 1024,
        )

    def _message_path(self, target_type: str, target_id: str) -> str:
        if target_type == "group":
            return f"/v2/groups/{target_id}/messages"
        if target_type in {"c2c", "user"}:
            return f"/v2/users/{target_id}/messages"
        if target_type == "channel":
            return f"/channels/{target_id}/messages"
        if target_type in {"dms", "dm"}:
            return f"/dms/{target_id}/messages"
        raise QQBotApiError(f"不支持的 QQ 回复目标类型: {target_type}")

    @staticmethod
    def _require_target_id(target_id: str | None) -> str:
        value = str(target_id or "").strip()
        if not value:
            raise QQBotApiError("QQ 发送目标不能为空")
        return value

    @staticmethod
    def _message_reference(body: dict[str, Any], *, msg_id: str | None = None, event_id: str | None = None, msg_seq: int | None = None, is_wakeup: bool | None = None, message_reference: dict | None = None) -> None:
        if msg_id and event_id:
            raise QQBotApiError("QQ 回复不能同时携带 msg_id 与 event_id")
        if is_wakeup and (msg_id or event_id):
            raise QQBotApiError("QQ is_wakeup 主动消息不能携带 msg_id/event_id")
        if msg_id:
            body["msg_id"] = str(msg_id)
        if event_id:
            body["event_id"] = str(event_id)
        if msg_seq is not None:
            body["msg_seq"] = int(msg_seq)
        if is_wakeup is not None:
            body["is_wakeup"] = bool(is_wakeup)
        if message_reference is not None:
            body["message_reference"] = message_reference

    async def send_text(self, *, target_type: str, target_id: str, content: str, **reference: Any) -> dict[str, Any]:
        if content is None or not str(content).strip():
            raise QQBotApiError("QQ 文本消息内容不能为空")
        content = str(content)
        target_id = self._require_target_id(target_id)
        body: dict[str, Any] = {"msg_type": 0, "content": content}
        self._message_reference(body, **reference)
        return await self.request("POST", self._message_path(target_type, target_id), json=body)

    async def send_markdown(self, *, target_type: str, target_id: str, content: str | dict[str, Any], keyboard: dict[str, Any] | None = None, **reference: Any) -> dict[str, Any]:
        target_id = self._require_target_id(target_id)
        self._validate_markdown_content(content)
        markdown = content if isinstance(content, dict) else {"content": str(content)}
        _validate_bounded_object(markdown, "markdown", max_bytes=32 * 1024)
        body: dict[str, Any] = {"msg_type": 2, "markdown": markdown}
        if keyboard is not None:
            _validate_keyboard(keyboard)
            body["keyboard"] = keyboard
        self._message_reference(body, **reference)
        return await self.request("POST", self._message_path(target_type, target_id), json=body)

    async def send_keyboard(self, *, target_type: str, target_id: str, content: str, keyboard: dict[str, Any], **reference: Any) -> dict[str, Any]:
        return await self.send_markdown(target_type=target_type, target_id=target_id, content=content, keyboard=keyboard, **reference)

    async def send_media(self, *, target_type: str, target_id: str, file_info: str, **reference: Any) -> dict[str, Any]:
        target_id = self._require_target_id(target_id)
        if not isinstance(file_info, str) or not file_info.strip():
            raise QQBotApiError("QQ 媒体 file_info 必须是非空字符串")
        file_info = file_info.strip()
        body: dict[str, Any] = {"msg_type": 7, "media": {"file_info": file_info}}
        self._message_reference(body, **reference)
        return await self.request("POST", self._message_path(target_type, target_id), json=body)

    async def stream_message(self, *, target_id: str, content: str, input_mode: str = "append", input_state: int = 1, index: int = 0, content_type: str = "text", stream_msg_id: str | None = None, state: int | None = None, **reference: Any) -> dict[str, Any]:
        target_id = self._require_target_id(target_id)
        if state is not None:
            input_state = int(state)
        if content is None or not str(content).strip():
            raise QQBotApiError("QQ 流式消息内容不能为空")
        if int(index) < 0:
            raise QQBotApiError("QQ 流式消息 index 不能为负数")
        if input_mode not in {"append", "replace"}:
            raise QQBotApiError("stream input_mode 必须是 append 或 replace")
        if input_state not in {1, 10}:
            raise QQBotApiError("stream input_state 必须是 1（继续）或 10（结束）")
        if content_type not in {"text", "markdown"}:
            raise QQBotApiError("stream content_type 必须是 text 或 markdown")
        body: dict[str, Any] = {
            "content_raw": str(content), "input_mode": input_mode, "input_state": int(input_state),
            "index": int(index), "content_type": content_type,
        }
        if stream_msg_id:
            body["stream_msg_id"] = str(stream_msg_id)
        self._message_reference(body, **reference)
        return await self.request("POST", f"/v2/users/{target_id}/stream_messages", json=body)

    async def input_notify(self, *, target_id: str, input_second: int = 5, **reference: Any) -> dict[str, Any]:
        target_id = self._require_target_id(target_id)
        seconds = int(input_second)
        if seconds < 1 or seconds > 60:
            raise QQBotApiError("input_second 必须在 1 到 60 秒之间")
        body: dict[str, Any] = {"msg_type": 6, "input_notify": {"input_type": 1, "input_second": seconds}}
        self._message_reference(body, **reference)
        return await self.request("POST", f"/v2/users/{target_id}/messages", json=body)

    async def send_input_notify(self, **kwargs: Any) -> dict[str, Any]:
        return await self.input_notify(**kwargs)

    async def send_stream(self, **kwargs: Any) -> dict[str, Any]:
        return await self.stream_message(**kwargs)

    async def send_channel(self, *, target_type: str, target_id: str, content: str = "", markdown: dict | str | None = None, embed: dict | None = None, ark: dict | None = None, image: str | None = None, **reference: Any) -> dict[str, Any]:
        if target_type not in {"channel", "dms", "dm"}:
            raise QQBotApiError("频道消息目标必须是 channel 或 dms")
        target_id = self._require_target_id(target_id)
        body: dict[str, Any] = {}
        if isinstance(markdown, str):
            self._validate_markdown_content(markdown)
            markdown = {"content": markdown}
        if markdown is not None:
            self._validate_markdown_content(markdown)
            # Markdown endpoints use the markdown object as content; sending
            # a duplicate plain ``content`` field changes the API semantics.
            content = ""
        if content:
            body["content"] = str(content)
        if markdown is not None:
            _validate_bounded_object(markdown, "markdown", max_bytes=32 * 1024)
            body["markdown"] = markdown
        if embed is not None:
            _validate_bounded_object(embed, "embed", max_bytes=64 * 1024)
            body["embed"] = embed
        if ark is not None:
            _validate_bounded_object(ark, "ark", max_bytes=64 * 1024)
            body["ark"] = ark
        multipart_image: Path | None = None
        if image:
            image_text = str(image)
            if image_text.startswith(("http://", "https://")):
                body["image"] = _assert_public_url(image_text)
            else:
                multipart_image = Path(image_text).expanduser().resolve()  # noqa: ASYNC240
                if not multipart_image.is_file():
                    raise QQBotApiError("频道图片本地路径不存在")
        self._message_reference(body, **reference)
        path = f"/channels/{target_id}/messages" if target_type == "channel" else f"/dms/{target_id}/messages"
        if multipart_image is not None:
            form = aiohttp.FormData()
            for key, value in body.items():
                if value is not None:
                    form.add_field(key, str(value) if not isinstance(value, (dict, list)) else __import__("json").dumps(value, ensure_ascii=False))
            with multipart_image.open("rb") as stream:
                form.add_field("file_image", stream, filename=multipart_image.name)
                return await self.request("POST", path, data=form)
        if not body:
            raise QQBotApiError("频道消息不能为空")
        return await self.request("POST", path, json=body)

    async def delete_message(self, *, target_type: str, target_id: str, message_id: str) -> dict[str, Any]:
        target_id = str(target_id).strip()
        message_id = str(message_id).strip()
        if not target_id or not message_id:
            raise QQBotApiError("QQ 撤回缺少 target_id/message_id")
        return await self.request("DELETE", f"{self._message_path(target_type, target_id)}/{message_id}")

    @staticmethod
    def _reaction_type(value: str | int) -> str:
        # QQ's EmojiType path segment is numeric: 1 is a system emoji and 2
        # is an emoji.  Keep the human-friendly ``emoji`` alias for callers,
        # but never send the alias verbatim to the OpenAPI endpoint.
        aliases = {
            "1": "1", "system": "1", "system_emoji": "1",
            "2": "2", "emoji": "2",
        }
        normalized = str(value).strip().lower()
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise QQBotApiError("reaction_type 必须是 1（系统表情）或 2（emoji）") from exc

    async def react(self, *, channel_id: str, message_id: str, reaction_type: str | int, reaction_id: str, method: str = "PUT") -> dict[str, Any]:
        channel_id = str(channel_id).strip()
        message_id = str(message_id).strip()
        reaction_id = str(reaction_id).strip()
        if not channel_id or not message_id or not reaction_id:
            raise QQBotApiError("QQ reaction 缺少 channel_id/message_id/reaction_id")
        method = method.upper()
        if method not in {"PUT", "DELETE"}:
            raise QQBotApiError("reaction method 只支持 PUT 或 DELETE")
        reaction_type = self._reaction_type(reaction_type)
        path = f"/channels/{channel_id}/messages/{message_id}/reactions/{reaction_type}/{reaction_id}"
        return await self.request(method, path)

    async def upload_media(self, *, target_type: str, target_id: str, source: str | os.PathLike[str] | bytes | bytearray | BinaryIO, media_type: str, file_name: str = "", chunk_size: int | None = None) -> dict[str, Any]:
        """Upload URL/local media and return the short-lived file_info payload."""
        if target_type not in {"c2c", "group", "user"}:
            raise QQBotApiError("QQ 单聊与群聊媒体上传目标必须是 c2c 或 group")
        target_id = self._require_target_id(target_id)
        media_type = str(media_type).lower().strip()
        if media_type not in _MEDIA_TYPES:
            raise QQBotApiError(f"不支持的 QQ 媒体类型: {media_type}")
        if isinstance(source, str) and source.startswith(("http://", "https://")):
            return await self._upload_media_url(
                target_type=target_type, target_id=target_id, url=source,
                media_type=media_type, file_name=file_name,
            )
        data, name = await self._read_media_source(source, file_name=file_name, media_type=media_type)
        size = len(data)
        self._validate_media_format(name, media_type)
        self._validate_media_size(media_type, size)
        degraded_from = ""
        soft_limit = {
            "image": self.config.media_image_max_bytes,
            "voice": self.config.media_voice_max_bytes,
            "video": self.config.media_video_max_bytes,
            "file": self.config.media_file_max_bytes,
        }[media_type]
        if media_type != "file" and size > int(soft_limit):
            degraded_from = media_type
            media_type = "file"
        digest_md5 = hashlib.md5(data).hexdigest()
        digest_sha1 = hashlib.sha1(data).hexdigest()
        md5_10m = hashlib.md5(data[: 10002432]).hexdigest()
        prefix = "users" if target_type in {"c2c", "user"} else "groups"
        base = f"/v2/{prefix}/{target_id}"
        prepare = await self.request("POST", f"{base}/upload_prepare", json={
                "file_type": _MEDIA_TYPES[media_type], "file_size": str(size), "file_name": name,
            "md5": digest_md5, "sha1": digest_sha1, "md5_10m": md5_10m,
        })
        upload_id = str(prepare.get("upload_id") or prepare.get("uploadId") or "")
        if not upload_id:
            raise QQBotApiError("QQ upload_prepare 响应缺少 upload_id")
        parts = prepare.get("parts") if isinstance(prepare.get("parts"), list) else []
        if not parts:
            # A few test/fake servers return a single URL directly.
            direct = prepare.get("presigned_url") or prepare.get("url")
            parts = [{"part_index": 0, "presigned_url": direct, "block_size": size}] if direct else []
        default_chunk = int(chunk_size or self.config.media_chunk_size)
        offset = 0
        for ordinal, raw_part in enumerate(parts):
            part = raw_part if isinstance(raw_part, dict) else {}
            url = str(part.get("presigned_url") or part.get("url") or "")
            if not url:
                raise QQBotApiError("QQ upload_prepare 响应缺少分片 presigned_url")
            index = int(part.get("part_index", part.get("index", ordinal)))
            block_size = int(part.get("block_size") or part.get("size") or default_chunk)
            block = data[offset : offset + block_size]
            if not block and size:
                break
            await self._put_presigned(url, block)
            await self.request("POST", f"{base}/upload_part_finish", json={
                "upload_id": upload_id, "part_index": index, "block_size": str(len(block)),
                "md5": hashlib.md5(block).hexdigest(),
            })
            offset += len(block)
        if offset < size:
            raise QQBotApiError("QQ 分片上传未覆盖完整文件")
        result = await self.request("POST", f"{base}/files", json={
            "file_type": _MEDIA_TYPES[media_type], "srv_send_msg": False,
            "file_name": name, "upload_id": upload_id,
        })
        result.setdefault("file_info", result.get("fileInfo") or result.get("media"))
        if not result.get("file_info"):
            raise QQBotApiError("QQ files 响应缺少 file_info")
        if degraded_from:
            result["degraded_from"] = degraded_from
        return result

    async def _upload_media_url(self, *, target_type: str, target_id: str, url: str, media_type: str, file_name: str) -> dict[str, Any]:
        safe_url = _assert_public_url(url)
        prefix = "users" if target_type in {"c2c", "user"} else "groups"
        name = self._ensure_media_filename(
            _clean_filename(file_name or Path(urlparse(safe_url).path).name, f"media{self._default_extension(media_type)}"),
            media_type,
        )
        self._validate_media_format(name, media_type)
        result = await self.request("POST", f"/v2/{prefix}/{target_id}/files", json={
            "file_type": _MEDIA_TYPES[media_type], "url": safe_url,
            "srv_send_msg": False, "file_name": name,
        })
        result.setdefault("file_info", result.get("fileInfo") or result.get("media"))
        if not result.get("file_info"):
            raise QQBotApiError("QQ URL 上传响应缺少 file_info")
        return result

    async def upload_url(self, *, target_type: str, target_id: str, url: str, media_type: str, file_name: str = "") -> dict[str, Any]:
        return await self.upload_media(target_type=target_type, target_id=target_id, source=url, media_type=media_type, file_name=file_name)

    async def upload_file(self, *, target_type: str, target_id: str, path: str | os.PathLike[str], media_type: str, file_name: str = "") -> dict[str, Any]:
        return await self.upload_media(target_type=target_type, target_id=target_id, source=path, media_type=media_type, file_name=file_name)

    async def _read_media_source(self, source: str | os.PathLike[str] | bytes | bytearray | BinaryIO, *, file_name: str, media_type: str) -> tuple[bytes, str]:
        if isinstance(source, (bytes, bytearray)):
            return bytes(source), _clean_filename(file_name, f"media{self._default_extension(media_type)}")
        if hasattr(source, "read"):
            data = source.read()
            if hasattr(data, "__await__"):
                data = await data
            return bytes(data), _clean_filename(file_name, f"media{self._default_extension(media_type)}")
        value = str(source)
        if value.startswith(("http://", "https://")):
            url = _assert_public_url(value)
            data, remote_name = await self._download_bytes(url)
            return data, self._ensure_media_filename(
                _clean_filename(file_name or remote_name, f"media{self._default_extension(media_type)}"), media_type
            )
        path = Path(value).expanduser().resolve()  # noqa: ASYNC240
        if not path.is_file():
            raise QQBotApiError("QQ 媒体本地路径不存在或不是文件")
        if path.stat().st_size > self.config.media_max_bytes:
            raise QQBotApiError(f"QQ 媒体超过 {self.config.media_max_bytes} 字节硬限制")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise QQBotApiError(f"读取 QQ 媒体失败: {exc}") from exc
        return data, self._ensure_media_filename(_clean_filename(file_name or path.name, f"media{self._default_extension(media_type)}"), media_type)

    async def _download_bytes(self, url: str) -> tuple[bytes, str]:
        session = await self._get_session()
        limit = int(self.config.media_max_bytes)
        try:
            async with session.get(url, allow_redirects=False) as response:
                if response.status >= 400:
                    raise QQBotApiError(f"下载 QQ 媒体失败: HTTP {response.status}")
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    raise QQBotApiError("QQ 媒体超过大小硬限制")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(256 * 1024):
                    total += len(chunk)
                    if total > limit:
                        raise QQBotApiError("QQ 媒体超过大小硬限制")
                    chunks.append(chunk)
                name = Path(urlparse(url).path).name
                return b"".join(chunks), name
        except QQBotApiError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            raise QQBotApiError(f"下载 QQ 媒体失败: {exc}") from exc

    async def download_to_file(self, url: str, target: str | os.PathLike[str], *, max_bytes: int | None = None) -> Path:
        """Bounded URL download used for inbound QQ attachments."""
        safe_url = _assert_public_url(url)
        session = await self._get_session()
        limit = int(max_bytes or self.config.media_max_bytes)
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.part")
        total = 0
        try:
            async with session.get(safe_url, allow_redirects=False) as response:
                if response.status >= 400:
                    raise QQBotApiError(f"下载 QQ 媒体失败: HTTP {response.status}")
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    raise QQBotApiError("QQ 媒体超过大小硬限制")
                with tmp.open("wb") as stream:
                    async for chunk in response.content.iter_chunked(256 * 1024):
                        total += len(chunk)
                        if total > limit:
                            raise QQBotApiError("QQ 媒体超过大小硬限制")
                        stream.write(chunk)
            tmp.replace(path)
            return path
        except QQBotApiError:
            tmp.unlink(missing_ok=True)
            raise
        except (TimeoutError, aiohttp.ClientError, OSError, ValueError) as exc:
            tmp.unlink(missing_ok=True)
            raise QQBotApiError(f"下载 QQ 媒体失败: {exc}") from exc

    async def _put_presigned(self, url: str, data: bytes) -> None:
        # Presigned URLs must not receive the bot Authorization header.
        session = await self._get_session()
        try:
            async with session.put(url, data=data, headers={"Content-Length": str(len(data))}) as response:
                if response.status >= 400:
                    raise QQBotApiError(f"QQ 分片上传失败: HTTP {response.status}")
        except QQBotApiError:
            raise
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise QQBotApiError(f"QQ 分片上传失败: {exc}") from exc

    def _validate_media_size(self, media_type: str, size: int) -> None:
        if size > int(self.config.media_max_bytes):
            raise QQBotApiError(f"QQ {media_type} 超过 200MB 硬限制")
        soft = {
            "image": self.config.media_image_max_bytes,
            "voice": self.config.media_voice_max_bytes,
            "video": self.config.media_video_max_bytes,
            "file": self.config.media_file_max_bytes,
        }[media_type]
        # Soft limits are intentionally not rejected: callers may choose to
        # send a large image/video as a generic file.  The metadata exposes the
        # configured boundary to adapter/tool callers.
        _ = soft

    def _validate_media_format(self, name: str, media_type: str) -> None:
        suffix = Path(name).suffix.lower()
        if media_type == "image" and suffix not in {".jpg", ".jpeg", ".png"}:
            raise QQBotApiError("QQ 图片上传接口仅明确支持 png/jpg；gif/webp/bmp 需真机验证，未静默伪造成功")
        if media_type == "voice" and suffix != ".silk":
            raise QQBotApiError("QQ 语音上传接口仅明确支持 silk；mp3/wav/ogg 需真机验证，未静默伪造成功")
        if media_type == "video" and suffix != ".mp4":
            raise QQBotApiError("QQ 视频上传接口仅明确支持 mp4")

    @staticmethod
    def _default_extension(media_type: str) -> str:
        return {"image": ".jpg", "video": ".mp4", "voice": ".silk", "file": ".bin"}[media_type]

    def _ensure_media_filename(self, name: str, media_type: str) -> str:
        if Path(name).suffix:
            return name
        return f"{name}{self._default_extension(media_type)}"

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.config.api_base_url.rstrip('/')}/{path.lstrip('/')}"
        session = await self._get_session()
        base_headers = dict(kwargs.pop("headers", {}) or {})
        has_json = "json" in kwargs and kwargs.get("json") is not None
        has_body = any(key in kwargs for key in ("data", "form", "files"))
        if has_json and has_body:
            raise QQBotApiError("QQ 请求不能同时使用 json 与 multipart/data")
        for attempt in range(2):
            token = await self.access_token()
            headers = dict(base_headers)
            headers["Authorization"] = f"QQBot {token}"
            if has_json and not has_body:
                headers.setdefault("Content-Type", "application/json; charset=utf-8")
            try:
                async with session.request(method, url, headers=headers, **kwargs) as response:
                    try:
                        payload = await self._response_json(response)
                    except QQBotApiError:
                        if response.status == 401 and attempt == 0:
                            self.invalidate_access_token(token)
                            continue
                        raise
                    if response.status == 401:
                        self.invalidate_access_token(token)
                        if attempt == 0:
                            continue
                    if response.status >= 400:
                        raise self._payload_error(payload, status=response.status)
                    err_code = payload.get("err_code")
                    if err_code not in {None, 0, "0"}:
                        raise self._payload_error(payload, status=response.status)
                    return payload
            except QQBotApiError:
                raise
            except (TimeoutError, aiohttp.ClientError) as exc:
                raise QQBotApiError(f"QQ OpenAPI 请求失败: {method} {path}: {exc}") from exc
        raise QQBotApiError(f"QQ OpenAPI 鉴权重试失败: {method} {path}", status=401)

    def invalidate_access_token(self, token: str | None = None) -> None:
        if token is None or token == self._access_token:
            self._access_token = ""
            self._access_token_expires_at = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=max(5.0, float(self.config.connect_timeout_seconds)))
            self._session = create_aiohttp_session(timeout=timeout)
            self._owns_session = True
        return self._session

    async def _response_json(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        # DELETE, interaction ACK and reaction endpoints legitimately return
        # 200 with an empty body or 204.  Treat those as successful empty JSON.
        if response.status == 204:
            return {}
        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            text = (await response.text()).strip()
            if not text and response.status in {200, 201, 202, 204}:
                return {}
            raise QQBotApiError(
                f"QQ OpenAPI 返回非 JSON 响应: {text[:300] or response.reason}", status=response.status
            ) from None
        if payload in (None, "") and response.status in {200, 201, 202, 204}:
            return {}
        if not isinstance(payload, dict):
            raise QQBotApiError("QQ OpenAPI 返回了无效响应结构", status=response.status)
        return payload

    def _token_is_valid(self) -> bool:
        return bool(self._access_token) and time.monotonic() < self._access_token_expires_at

    def _payload_error(self, payload: dict[str, Any], *, message: str = "", status: int | None = None) -> QQBotApiError:
        err_code = payload.get("err_code", payload.get("code"))
        trace_id = str(payload.get("trace_id") or "")
        detail = message or str(payload.get("message") or payload.get("error") or "QQ OpenAPI 调用失败")
        if err_code not in {None, ""}:
            detail = f"{detail} (err_code={err_code})"
        if trace_id:
            detail = f"{detail} (trace_id={trace_id})"
        return QQBotApiError(detail, status=status, err_code=err_code, trace_id=trace_id)

    @staticmethod
    def _validate_markdown_content(content: str | dict[str, Any]) -> None:
        value = content.get("content") if isinstance(content, dict) else content
        if value is None or not str(value).strip():
            raise QQBotApiError("QQ Markdown 内容不能为空")


def _validate_bounded_object(value: object, label: str, *, max_bytes: int) -> None:
    import json

    if not isinstance(value, dict):
        raise QQBotApiError(f"{label} 必须是对象")
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
        raise QQBotApiError(f"{label} 超过大小限制")


def _validate_keyboard(value: dict[str, Any]) -> None:
    _validate_bounded_object(value, "keyboard", max_bytes=32 * 1024)
    rows = value.get("content", {}).get("rows", []) if isinstance(value.get("content"), dict) else value.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 5:
        raise QQBotApiError("keyboard 最多支持 5 行")
    for row in rows:
        buttons = row.get("buttons", []) if isinstance(row, dict) else []
        if not isinstance(buttons, list) or len(buttons) > 5:
            raise QQBotApiError("keyboard 每行按钮数超出限制")
        for button in buttons:
            if not isinstance(button, dict):
                raise QQBotApiError("keyboard button 必须是对象")
            label = str(button.get("render_data", {}).get("label") or button.get("label") or "") if isinstance(button.get("render_data"), dict) else str(button.get("label") or "")
            if len(label) > 10:
                raise QQBotApiError("keyboard 按钮文字最多 10 个字符")


# Concise alias used by integrations that call the adapter's transport
# ``QQClient``; keep the historical QQBotClient name for compatibility.
QQClient = QQBotClient
