from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


SEND_CLIENT_MSG_ID_KEYS = ("ClientMsgid", "ClientMsgId", "clientMsgId", "client_msg_id")
SEND_CREATE_TIME_KEYS = ("Createtime", "CreateTime", "createTime", "create_time")
SEND_NEW_MSG_ID_KEYS = ("NewMsgId", "newMsgId", "new_msg_id")


class Wechat869Client:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        admin_key: str = "",
        token_key: str = "",
        ws_url: str = "",
        timeout_seconds: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.admin_key = admin_key
        self.token_key = token_key
        self.ws_url = ws_url
        self.timeout_seconds = timeout_seconds
        self.wxid = ""
        self.nickname = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def append_key_to_ws_url(self, ws_url: str, key: str) -> str:
        parsed = urlparse(ws_url)
        query = parse_qs(parsed.query)
        if key and "key" not in query:
            query["key"] = [key]
        new_query = urlencode({k: v[-1] if isinstance(v, list) else v for k, v in query.items()})
        return urlunparse(parsed._replace(query=new_query))

    async def send_text_message(
        self,
        wxid: str,
        content: str,
        at: list[str] | str | None = None,
    ) -> tuple[int, int, int]:
        if isinstance(at, str) and at:
            at_list = [item for item in at.split(",") if item]
        elif isinstance(at, list):
            at_list = at
        else:
            at_list = []

        payload = {
            "MsgItem": [
                {
                    "ToUserName": wxid,
                    "MsgType": 1,
                    "TextContent": content,
                    "AtWxIDList": at_list,
                }
            ]
        }
        data = await self.call_path("/message/SendTextMessage", body=payload)
        return self._extract_send_tuple(data)

    async def call_path(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        method: str = "POST",
        key: str | None = None,
    ) -> Any:
        payload = await self.request(path, body=body, method=method, key=key)
        if isinstance(payload, dict) and "Data" in payload:
            return payload.get("Data")
        return payload

    async def request(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        method: str = "POST",
        key: str | None = None,
    ) -> Any:
        request_method = method.upper()
        request_url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        request_key = key if key is not None else self.token_key or self.admin_key
        params = {"key": request_key} if request_key else None

        import aiohttp

        async with aiohttp.ClientSession() as session:
            if request_method == "GET":
                response = await session.get(
                    request_url,
                    params=params,
                    timeout=self.timeout_seconds,
                )
            else:
                response = await session.request(
                    request_method,
                    request_url,
                    params=params,
                    json=body or {},
                    timeout=self.timeout_seconds,
                )

            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type.lower():
                payload = await response.json(content_type=None)
            else:
                text = await response.text()
                payload = text

        if response.status >= 400:
            raise RuntimeError(self._extract_error(payload) or f"869 HTTP {response.status}")

        if isinstance(payload, dict):
            code = payload.get("Code")
            if code not in (None, 0, 200):
                raise RuntimeError(self._extract_error(payload) or "869 request failed")
            if code is None and payload.get("Success") is False:
                raise RuntimeError(self._extract_error(payload) or "869 request failed")
        return payload

    def _extract_send_tuple(self, data: Any) -> tuple[int, int, int]:
        now = int(time.time())
        candidate = self._extract_send_candidate(data)
        if not isinstance(candidate, dict):
            return 0, now, 0
        return (
            self._pick_int(candidate, SEND_CLIENT_MSG_ID_KEYS, 0),
            self._pick_int(candidate, SEND_CREATE_TIME_KEYS, now),
            self._pick_int(candidate, SEND_NEW_MSG_ID_KEYS, 0),
        )

    def _extract_send_candidate(self, data: Any) -> Any:
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            return data
        if isinstance(data.get("List"), list) and data["List"]:
            data = data["List"][0]
        if isinstance(data, dict) and isinstance(data.get("resp"), dict):
            chat_list = data["resp"].get("chat_send_ret_list")
            if isinstance(chat_list, list) and chat_list:
                return chat_list[0]
        return data

    def _pick_int(self, data: dict[str, Any], keys: tuple[str, ...], default: int) -> int:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default
        return default

    def _extract_error(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return str(payload or "").strip()
        return str(
            payload.get("Text")
            or payload.get("Message")
            or payload.get("message")
            or payload.get("ErrMsg")
            or ""
        ).strip()
