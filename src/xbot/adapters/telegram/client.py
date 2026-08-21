from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
from typing import Any

import aiohttp

from xbot.core.config import TelegramAdapterConfig
from xbot.core.proxy import create_aiohttp_session


class TelegramApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after


class TelegramBotClient:
    """Small Telegram Bot API client that never exposes token-bearing URLs."""

    def __init__(self, config: TelegramAdapterConfig, session: aiohttp.ClientSession | None = None) -> None:
        self.config = config
        self._session = session
        self._owns_session = session is None

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def get_me(self) -> dict[str, Any]:
        return await self.request("getMe")

    async def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "edited_message", "channel_post", "edited_channel_post", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self.request("getUpdates", json=payload, request_timeout=timeout + 10)
        return result if isinstance(result, list) else []

    async def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> bool:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        return bool(await self.request("answerCallbackQuery", json=payload))

    async def send_chat_action(self, *, chat_id: str, action: str = "typing") -> bool:
        return bool(await self.request(
            "sendChatAction",
            json={"chat_id": chat_id, "action": action},
        ))

    async def set_my_commands(
        self,
        *,
        commands: list[dict[str, str]],
        scope: dict[str, Any],
    ) -> bool:
        return bool(await self.request(
            "setMyCommands",
            json={"commands": commands, "scope": scope},
        ))

    async def set_chat_menu_button(self, *, chat_id: str) -> bool:
        return bool(await self.request(
            "setChatMenuButton",
            json={"chat_id": chat_id, "menu_button": {"type": "commands"}},
        ))

    async def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self._with_reply(payload, reply_to_message_id)
        result = await self.request("sendMessage", json=payload)
        return result if isinstance(result, dict) else {}

    async def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = await self.request("editMessageText", json=payload)
        return result if isinstance(result, dict) else {}

    async def send_media(
        self,
        *,
        kind: str,
        chat_id: str,
        source: str,
        caption: str = "",
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        file_name: str = "",
    ) -> dict[str, Any]:
        methods = {
            "image": ("sendPhoto", "photo"),
            "file": ("sendDocument", "document"),
            "audio": ("sendAudio", "audio"),
            "voice": ("sendVoice", "voice"),
            "video": ("sendVideo", "video"),
        }
        try:
            method, field = methods[kind]
        except KeyError as exc:
            raise TelegramApiError(f"Telegram 不支持媒体类型: {kind}") from exc
        payload: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption if parse_mode else caption[:1024]
        if parse_mode:
            payload["parse_mode"] = parse_mode
        self._with_reply(payload, reply_to_message_id)
        if source.startswith(("http://", "https://")) or not Path(source).expanduser().is_file():
            payload[field] = source
            result = await self.request(method, json=payload)
        else:
            path = Path(source).expanduser().resolve()
            form = aiohttp.FormData()
            for key, value in payload.items():
                form.add_field(key, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value))
            with path.open("rb") as stream:
                form.add_field(field, stream, filename=file_name or path.name, content_type="application/octet-stream")
                result = await self.request(method, data=form)
        return result if isinstance(result, dict) else {}

    async def send_media_group(
        self,
        *,
        chat_id: str,
        sources: list[str],
        caption: str = "",
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if not 2 <= len(sources) <= 10:
            raise TelegramApiError("Telegram 相册必须包含 2～10 个媒体文件")
        payload: dict[str, Any] = {"chat_id": chat_id}
        self._with_reply(payload, reply_to_message_id)
        media: list[dict[str, Any]] = []
        local_paths: list[Path | None] = []
        for index, source in enumerate(sources):
            path = Path(source).expanduser()
            is_local = path.is_file()
            item: dict[str, Any] = {
                "type": "photo",
                "media": f"attach://media{index}" if is_local else source,
            }
            if index == 0 and caption:
                item["caption"] = caption if parse_mode else caption[:1024]
                if parse_mode:
                    item["parse_mode"] = parse_mode
            media.append(item)
            local_paths.append(path.resolve() if is_local else None)
        if not any(local_paths):
            payload["media"] = media
            result = await self.request("sendMediaGroup", json=payload)
        else:
            form = aiohttp.FormData()
            for key, value in payload.items():
                form.add_field(key, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value))
            form.add_field("media", json.dumps(media, ensure_ascii=False))
            with contextlib.ExitStack() as stack:
                for index, path in enumerate(local_paths):
                    if path is None:
                        continue
                    stream = stack.enter_context(path.open("rb"))
                    form.add_field(f"media{index}", stream, filename=path.name, content_type="application/octet-stream")
                result = await self.request("sendMediaGroup", data=form)
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    async def download_file(self, file_id: str, target: str | os.PathLike[str], *, max_bytes: int) -> Path:
        info = await self.request("getFile", json={"file_id": file_id})
        file_path = str(info.get("file_path") or "") if isinstance(info, dict) else ""
        if not file_path:
            raise TelegramApiError("Telegram getFile 响应缺少 file_path")
        session = await self._get_session()
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_name(f".{target_path.name}.part")
        total = 0
        try:
            async with session.get(self._file_url(file_path), allow_redirects=False) as response:
                if response.status >= 400:
                    raise TelegramApiError(f"Telegram 文件下载失败: HTTP {response.status}")
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    raise TelegramApiError("Telegram 文件超过配置的大小限制")
                with temporary.open("wb") as stream:
                    async for chunk in response.content.iter_chunked(256 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise TelegramApiError("Telegram 文件超过配置的大小限制")
                        stream.write(chunk)
            temporary.replace(target_path)
            return target_path
        except TelegramApiError:
            temporary.unlink(missing_ok=True)
            raise
        except (aiohttp.ClientError, OSError, TimeoutError, ValueError):
            temporary.unlink(missing_ok=True)
            raise TelegramApiError("Telegram 文件下载失败") from None

    async def request(self, method: str, *, request_timeout: float | None = None, **kwargs: Any) -> Any:
        if not self.config.bot_token.strip():
            raise TelegramApiError("Telegram Bot Token 未配置")
        session = await self._get_session()
        timeout = aiohttp.ClientTimeout(total=request_timeout or max(5.0, float(self.config.connect_timeout_seconds)))
        try:
            for attempt in range(2):
                async with session.post(self._api_url(method), timeout=timeout, **kwargs) as response:
                    try:
                        payload = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        raise TelegramApiError(f"Telegram {method} 返回了无效响应", error_code=response.status) from None
                    if isinstance(payload, dict) and payload.get("ok"):
                        return payload.get("result")
                    description = str(payload.get("description") or "Bot API 调用失败") if isinstance(payload, dict) else "Bot API 调用失败"
                    error_code = (
                        payload.get("error_code") or response.status
                        if isinstance(payload, dict)
                        else response.status
                    )
                    parameters = payload.get("parameters") if isinstance(payload, dict) else None
                    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
                    retry_seconds = float(retry_after) if isinstance(retry_after, (int, float)) else None
                    if (
                        int(error_code or 0) == 429
                        and retry_seconds is not None
                        and attempt == 0
                        and "json" in kwargs
                    ):
                        await asyncio.sleep(min(30.0, max(0.1, retry_seconds)))
                        continue
                    raise TelegramApiError(
                        f"Telegram {method} 失败: {description}",
                        error_code=int(error_code) if error_code else None,
                        retry_after=retry_seconds,
                    )
            raise TelegramApiError(f"Telegram {method} 请求失败")
        except TelegramApiError:
            raise
        except (aiohttp.ClientError, TimeoutError):
            raise TelegramApiError(f"Telegram {method} 请求失败") from None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = create_aiohttp_session()
            self._owns_session = True
        return self._session

    def _api_url(self, method: str) -> str:
        return f"{self.config.api_base_url.rstrip('/')}/bot{self.config.bot_token}/{method}"

    def _file_url(self, file_path: str) -> str:
        return f"{self.config.api_base_url.rstrip('/')}/file/bot{self.config.bot_token}/{file_path.lstrip('/')}"

    @staticmethod
    def _with_reply(payload: dict[str, Any], message_id: int | None) -> None:
        if message_id is not None:
            payload["reply_parameters"] = {"message_id": message_id, "allow_sending_without_reply": True}
