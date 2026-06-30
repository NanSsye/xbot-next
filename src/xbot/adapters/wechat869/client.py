from __future__ import annotations

import base64
import asyncio
import uuid
import time
from typing import Any
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


SEND_CLIENT_MSG_ID_KEYS = ("ClientMsgid", "ClientMsgId", "clientMsgId", "client_msg_id")
SEND_CREATE_TIME_KEYS = ("Createtime", "CreateTime", "createTime", "create_time")
SEND_NEW_MSG_ID_KEYS = ("NewMsgId", "newMsgId", "new_msg_id")
AUTH_KEY_KEYS = ("AuthKey", "auth_key", "Key", "key")
TOKEN_KEY_KEYS = ("TokenKey", "token_key", "tokenKey")
POLL_KEY_KEYS = ("PollKey", "poll_key", "Uuid", "uuid")
UUID_KEYS = ("Uuid", "uuid", "UUID")
DISPLAY_UUID_KEYS = ("DisplayUuid", "display_uuid", "DisplayUUID")
LOGIN_TX_ID_KEYS = ("LoginTxId", "login_tx_id")
QR_URL_KEYS = ("QrCodeUrl", "qrcode_url", "QRCodeUrl", "Url", "url")
WXID_KEYS = ("Wxid", "wxid", "UserName", "userName", "user_name", "UserNameStr", "FromUserName")
NICKNAME_KEYS = ("NickName", "nickName", "nickname")
ALIAS_KEYS = ("Alias", "alias", "Wechat", "wechat")
STATUS_KEYS = ("Status", "status", "LoginStatus", "login_status", "state", "State")
DATA62_KEYS = ("Data62", "data62")
TICKET_KEYS = ("Ticket", "ticket")


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
        self.alias = ""
        self.auth_key = ""
        self.auth_keys: list[str] = []
        self.poll_key = ""
        self.display_uuid = ""
        self.login_tx_id = ""
        self.data62 = ""
        self.ticket = ""
        self.device_id = ""
        self.device_type = "ipad"

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


    async def send_image_message(self, wxid: str, image_path: str) -> Any:
        data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        payload = {"MsgItem": [{"ToUserName": wxid, "MsgType": 2, "ImageContent": data}]}
        try:
            return await self.call_path("/message/SendImageMessage", body=payload)
        except Exception:
            return await self.call_path("/message/SendImageNewMessage", body=payload)

    async def send_file_message(self, wxid: str, file_path: str) -> Any:
        path = Path(file_path)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        upload = await self.call_path("/other/UploadAppAttach", body={"fileData": data})
        info = upload if isinstance(upload, dict) else {}
        media_id = str(info.get("mediaId") or info.get("MediaId") or info.get("media_id") or "")
        total_len = int(info.get("totalLen") or info.get("TotalLen") or path.stat().st_size)
        file_name = path.name
        ext = path.suffix.lstrip(".")
        xml = (
            "<appmsg appid='' sdkver='0'>"
            f"<title>{file_name}</title><des></des><type>6</type>"
            f"<appattach><totallen>{total_len}</totallen><attachid>{media_id}</attachid><fileext>{ext}</fileext></appattach>"
            "</appmsg>"
        )
        payload = {"AppList": [{"ToUserName": wxid, "ContentType": 6, "ContentXML": xml}]}
        return await self.call_path("/message/SendAppMessage", body=payload)


    async def send_app_message(self, wxid: str, content_xml: str, content_type: int = 6) -> Any:
        payload = {"AppList": [{"ToUserName": wxid, "ContentType": int(content_type), "ContentXML": content_xml}]}
        return await self.call_path("/message/SendAppMessage", body=payload)

    async def send_video_message(self, wxid: str, video_path: str) -> Any:
        return await self.send_file_message(wxid, video_path)

    async def send_voice_message(self, wxid: str, voice_bytes: bytes, *, format: str = "wav", seconds: int = 0) -> Any:
        payload = {
            "ToUserName": wxid,
            "VoiceData": base64.b64encode(voice_bytes).decode("ascii"),
            "VoiceFormat": 0 if str(format).lower() == "amr" else 3,
            "VoiceSecond": int(seconds or 0),
        }
        return await self.call_path("/message/SendVoice", body=payload)

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

    async def ensure_auth_key(self) -> str:
        if self.auth_key:
            return self.auth_key
        self.auth_keys = [str(item).strip() for item in self.auth_keys if str(item).strip()]
        if self.auth_keys:
            self.auth_key = self.auth_keys[0]
            return self.auth_key
        if self.token_key:
            self.auth_key = self.token_key
            return self.auth_key
        if not self.admin_key:
            raise RuntimeError("缺少 admin_key，无法生成 869 AuthKey")

        try:
            payload = await self.request("/admin/GetActiveLicenseKeys", method="GET", key=self.admin_key)
            for value in self._extract_auth_keys(payload):
                if value not in self.auth_keys:
                    self.auth_keys.append(value)
        except Exception:
            pass

        if not self.auth_keys:
            payload = await self.request("/admin/GenAuthKey2", method="GET", key=self.admin_key)
            for value in self._extract_auth_keys(payload):
                if value not in self.auth_keys:
                    self.auth_keys.append(value)

        if not self.auth_keys:
            raise RuntimeError("生成 869 AuthKey 失败")
        self.auth_key = self.auth_keys[0]
        return self.auth_key

    async def get_login_qrcode(
        self,
        *,
        device_type: str = "ipad",
        device_id: str = "",
        proxy: str = "",
    ) -> dict[str, Any]:
        auth_key = await self.ensure_auth_key()
        login_device = "mac" if str(device_type or "").strip().lower() == "mac" else "ipad"
        payload: dict[str, Any] = {"IpadOrmac": login_device, "Check": False}
        if proxy:
            payload["Proxy"] = proxy
        response = await self.request_with_fallback(
            "/login/GetLoginQrCodeNewDirect",
            body=payload,
            method="POST",
            key=auth_key,
        )
        data = response.get("Data") if isinstance(response, dict) else {}
        if not isinstance(data, dict):
            data = response if isinstance(response, dict) else {}
        data62 = self._pick(data, DATA62_KEYS) or self._pick(response, DATA62_KEYS)
        if data62:
            self.data62 = str(data62)
        ticket = self._pick(data, TICKET_KEYS) or self._pick(response, TICKET_KEYS)
        if ticket:
            self.ticket = str(ticket)
        token_key = self._pick(data, TOKEN_KEY_KEYS) or self._pick(response, TOKEN_KEY_KEYS)
        if token_key:
            self.token_key = str(token_key)
        poll_key = self._pick(data, POLL_KEY_KEYS) or self._pick(response, POLL_KEY_KEYS)
        self.poll_key = str(poll_key or self.poll_key or self.auth_key)
        auth_key_from_data = self._pick(data, AUTH_KEY_KEYS) or self._pick(response, AUTH_KEY_KEYS)
        if auth_key_from_data:
            self.auth_key = str(auth_key_from_data)
        display_uuid = self._pick(data, DISPLAY_UUID_KEYS)
        login_tx_id = self._pick(data, LOGIN_TX_ID_KEYS)
        qr_url = str(self._pick(data, QR_URL_KEYS) or "")
        login_uuid = str(self._pick(data, UUID_KEYS) or self._extract_uuid_from_qr_url(qr_url) or "")
        if not qr_url and login_uuid:
            qr_url = f"http://weixin.qq.com/x/{login_uuid}"
        self.display_uuid = str(display_uuid or login_uuid or self.display_uuid)
        self.login_tx_id = str(login_tx_id or self.login_tx_id)
        self.device_type = login_device
        self.device_id = device_id or self.device_id or self.create_device_id()
        self._sync_key_from_url(qr_url)
        return {
            "status": "waiting_login",
            "qrcode": login_uuid or self.display_uuid,
            "uuid": login_uuid,
            "qr_url": qr_url,
            "expires_in": 240,
            "login_mode": login_device,
            "device_id": self.device_id,
            "token_key": self.token_key,
            "poll_key": self.poll_key,
            "auth_key": self.auth_key,
            "display_uuid": self.display_uuid,
            "login_tx_id": self.login_tx_id,
            "data62": self.data62,
            "ticket": self.ticket,
        }

    async def poll_login_status(self, key: str = "") -> dict[str, Any]:
        active_key = key or self.token_key or self.poll_key or self.auth_key
        if not active_key:
            return {"logged_in": False, "status": "missing_key", "message": "缺少登录 Key"}
        try:
            response = await self.request("/login/CheckLoginStatus", method="GET", key=active_key)
        except Exception as exc:
            return {"logged_in": False, "status": "error", "message": str(exc)}
        data = response.get("Data") if isinstance(response, dict) else {}
        if not isinstance(data, dict):
            data = response if isinstance(response, dict) else {}
        ticket = self._pick(data, TICKET_KEYS) or self._pick(response, TICKET_KEYS)
        if ticket:
            self.ticket = str(ticket)
        data62 = self._pick(data, DATA62_KEYS) or self._pick(response, DATA62_KEYS)
        if data62:
            self.data62 = str(data62)
        token_key = self._pick(data, TOKEN_KEY_KEYS) or self._pick(response, TOKEN_KEY_KEYS)
        if token_key:
            self.token_key = str(token_key)
        wxid = self._pick(data, WXID_KEYS) or self._pick(response, WXID_KEYS)
        if wxid:
            self.wxid = str(wxid)
        status_code = self._safe_int(self._pick(data, STATUS_KEYS) or self._pick(response, STATUS_KEYS), 0)
        logged_in = bool(wxid) or status_code in {1, 2, 200, 201}
        if logged_in:
            await self.refresh_profile()
        return {
            "logged_in": logged_in,
            "status": "online" if logged_in else "waiting_login",
            "bot_wxid": self.wxid,
            "bot_nickname": self.nickname,
            "bot_alias": self.alias,
            "token_key": self.token_key,
            "poll_key": self.poll_key,
            "auth_key": self.auth_key,
            "display_uuid": self.display_uuid,
            "login_tx_id": self.login_tx_id,
            "data62": self.data62,
            "ticket": self.ticket,
            "raw": data or response,
        }

    async def get_login_status(self) -> dict[str, Any]:
        active_key = self.token_key or self.poll_key or self.auth_key
        if not active_key:
            return {"logged_in": False, "status": "missing_key"}
        try:
            response = await self.request("/login/GetLoginStatus", method="GET", key=active_key)
        except Exception as exc:
            return {"logged_in": False, "status": "error", "message": str(exc)}
        data = response.get("Data") if isinstance(response, dict) else {}
        if not isinstance(data, dict):
            data = response if isinstance(response, dict) else {}
        wxid = self._pick(data, WXID_KEYS) or self._pick(response, WXID_KEYS)
        if wxid:
            self.wxid = str(wxid)
        status_code = self._safe_int(self._pick(data, STATUS_KEYS) or self._pick(response, STATUS_KEYS), 0)
        status_bool = self._pick(data, ("IsLogin", "is_login", "LoggedIn", "logged_in"))
        logged_in = bool(wxid) or self._truthy_login_value(status_bool) or status_code in {1, 2, 200, 201}
        profile = await self.refresh_profile()
        if self.wxid:
            logged_in = True
        return {
            "logged_in": logged_in,
            "status": "online" if logged_in else "offline",
            "bot_wxid": self.wxid,
            "bot_nickname": self.nickname,
            "bot_alias": self.alias,
            "profile_loaded": bool(profile),
            "raw": data or response,
        }

    async def refresh_profile(self) -> dict[str, Any]:
        try:
            data = await self.call_path("/user/GetProfile", method="GET")
        except Exception:
            return {}
        profile = data if isinstance(data, dict) else {}
        user_info = profile.get("userInfo") if isinstance(profile.get("userInfo"), dict) else profile
        wxid = self._pick_nested(user_info, WXID_KEYS)
        nickname = self._pick_nested(user_info, NICKNAME_KEYS)
        alias = self._pick_nested(user_info, ALIAS_KEYS)
        if wxid:
            self.wxid = str(wxid)
        if nickname:
            self.nickname = str(nickname)
        if alias:
            self.alias = str(alias)
        return profile

    async def try_wakeup_login(self) -> bool:
        active_key = self.token_key or self.poll_key or self.auth_key or self.admin_key
        if not active_key:
            return False
        login_device = "mac" if self.device_type == "mac" else "ipad"
        try:
            payload = await self.request(
                "/login/WakeUpLogin",
                body={"IpadOrmac": login_device, "Check": False},
                method="POST",
                key=active_key,
            )
            data = payload.get("Data") if isinstance(payload, dict) else {}
            if not isinstance(data, dict):
                data = payload if isinstance(payload, dict) else {}
            token_key = self._pick(data, TOKEN_KEY_KEYS) or self._pick(payload, TOKEN_KEY_KEYS)
            poll_key = self._pick(data, POLL_KEY_KEYS) or self._pick(payload, POLL_KEY_KEYS)
            if token_key:
                self.token_key = str(token_key)
            if poll_key:
                self.poll_key = str(poll_key)
        except Exception:
            return False
        for _ in range(3):
            status = await self.get_login_status()
            if status.get("logged_in"):
                return True
            await asyncio.sleep(0.2)
        return False

    async def request_with_fallback(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        method: str = "POST",
        key: str | None = None,
    ) -> Any:
        candidates = {
            "/login/GetLoginQrCodeNewDirect": [
                "/login/GetLoginQrCodeNewDirect",
                "/login/GetLoginQrCodeNew",
                "/login/GetLoginQrCodeNewX",
            ],
        }.get(path, [path])
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return await self.request(candidate, body=body, method=method, key=key)
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError(f"869 request failed: {path}")

    async def send_cdn_download(self, aes_key: str, file_url: str, file_type: int) -> str:
        if not aes_key or not file_url:
            return ""
        data = await self.call_path(
            "/message/SendCdnDownload",
            body={"AesKey": aes_key, "FileURL": file_url, "FileType": int(file_type)},
        )
        return self._extract_base64_from_payload(data)

    async def download_image(self, aes_key: str, cdn_url: str) -> bytes:
        for file_type in (2, 3):
            try:
                payload = await self.send_cdn_download(aes_key, cdn_url, file_type)
                if payload:
                    return base64.b64decode(payload)
            except Exception:
                continue
        return b""

    async def download_file(self, aes_key: str, file_url: str) -> bytes:
        payload = await self.send_cdn_download(aes_key, file_url, 5)
        return base64.b64decode(payload) if payload else b""

    async def download_attach(self, attach_id: str) -> bytes:
        attach_id = str(attach_id or "").strip()
        if not attach_id:
            return b""
        aes_key = ""
        file_url = ""
        if attach_id.startswith("@cdn_"):
            raw = attach_id[len("@cdn_") :]
            parts = [part for part in raw.split("_") if part]
            if len(parts) >= 3:
                aes_key = parts[-2]
                file_url = "_".join(parts[:-2])
        if aes_key and file_url:
            data = await self.download_file(aes_key, file_url)
            if data:
                return data
        try:
            payload = await self.call_path(
                "/api/Tools/DownloadFile",
                body={"Wxid": self.wxid, "AttachId": attach_id},
            )
        except Exception:
            return b""
        encoded = self._extract_base64_from_payload(payload)
        return base64.b64decode(encoded) if encoded else b""


    async def get_chatroom_member_list(self, group_wxid: str) -> list[dict[str, Any]]:
        """实时获取群成员列表，兼容 869 多种返回结构。"""
        attempts = (
            ("/group/GetChatroomMemberDetail", {"ChatRoomName": group_wxid}),
            ("/group/GetChatroomMemberDetail", {"ChatRoomWxid": group_wxid}),
            ("/group/GetChatroomMemberDetail", {"ChatRoomWxId": group_wxid}),
            ("/group/GetChatroomMemberList", {"ChatRoomName": group_wxid}),
            ("/group/GetChatroomMemberList", {"ChatRoomWxid": group_wxid}),
            ("/group/GetChatRoomInfo", {"ChatRoomWxIdList": [group_wxid]}),
            ("/group/GetChatRoomInfo", {"ChatRoomName": group_wxid}),
        )
        for path, body in attempts:
            try:
                data = await self.call_path(path, body=body)
            except Exception:
                continue
            members = self._extract_chatroom_members(data)
            if members:
                return [self._normalize_chatroom_member_item(item) for item in members]
        return []

    async def get_chatroom_members(self, group_wxid: str) -> list[dict[str, Any]]:
        return await self.get_chatroom_member_list(group_wxid)

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

    @staticmethod
    def create_device_id(seed: str = "") -> str:
        if seed:
            return uuid.uuid5(uuid.NAMESPACE_DNS, seed).hex
        return uuid.uuid4().hex

    @staticmethod
    def _pick(data: Any, keys: tuple[str, ...], default: Any = "") -> Any:
        if not isinstance(data, dict):
            return default
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
        return default

    @classmethod
    def _pick_nested(cls, data: Any, keys: tuple[str, ...], default: Any = "") -> Any:
        value = cls._pick(data, keys, default)
        if isinstance(value, dict):
            nested = cls._pick(value, ("str", "Str", "string", "String", "value", "Value", "text", "Text"), default)
            return nested
        return value


    @classmethod
    def _normalize_chatroom_member_item(cls, item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        wxid = str(cls._pick_nested(item, ("UserName", "UserNameStr", "userName", "user_name", "Wxid", "WxId", "wxid", "MemberWxid", "member_wxid", "MemberId", "memberId"), "") or "").strip()
        nickname = str(cls._pick_nested(item, ("NickName", "NickNameStr", "nickName", "nickname", "nick_name", "DisplayName", "display_name", "Remark", "RemarkName"), "") or "").strip()
        big_avatar = str(cls._pick_nested(item, ("BigHeadImgUrl", "bigHeadImgUrl", "big_head_img_url"), "") or "").strip()
        small_avatar = str(cls._pick_nested(item, ("SmallHeadImgUrl", "smallHeadImgUrl", "small_head_img_url"), "") or "").strip()
        if wxid:
            normalized.setdefault("UserName", wxid)
            normalized.setdefault("Wxid", wxid)
            normalized.setdefault("wxid", wxid)
        if nickname:
            normalized.setdefault("NickName", nickname)
            normalized.setdefault("nickname", nickname)
        if big_avatar:
            normalized.setdefault("BigHeadImgUrl", big_avatar)
        if small_avatar:
            normalized.setdefault("SmallHeadImgUrl", small_avatar)
        if not normalized.get("avatar"):
            normalized["avatar"] = big_avatar or small_avatar
        return normalized

    @classmethod
    def _extract_chatroom_members(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            direct = [x for x in payload if isinstance(x, dict) and cls._chatroom_member_id(x)]
            if direct:
                return direct
            for item in payload:
                members = cls._extract_chatroom_members(item)
                if members:
                    return members
            return []
        if not isinstance(payload, dict):
            return []
        for key in ("Data", "data", "member_data", "NewChatroomData", "newChatroomData"):
            members = cls._extract_chatroom_members(payload.get(key))
            if members:
                return members
        for key in ("chatroom_member_list", "ChatRoomMember", "MemberList", "memberList", "member_list", "ChatRoomMemberList"):
            value = payload.get(key)
            if isinstance(value, list):
                direct = [x for x in value if isinstance(x, dict) and cls._chatroom_member_id(x)]
                if direct:
                    return direct
        for key in ("ChatRoomInfo", "chatroomInfo", "ContactList", "contactList"):
            members = cls._extract_chatroom_members(payload.get(key))
            if members:
                return members
        return []

    @classmethod
    def _chatroom_member_id(cls, item: dict[str, Any]) -> str:
        wxid = str(cls._pick_nested(item, ("UserName", "UserNameStr", "userName", "user_name", "Wxid", "WxId", "wxid", "MemberWxid", "member_wxid", "MemberId", "memberId"), "") or "").strip()
        if not wxid or wxid.endswith("@chatroom"):
            return ""
        return wxid

    @classmethod
    def _extract_auth_keys(cls, payload: Any) -> list[str]:
        values: list[str] = []
        if isinstance(payload, dict):
            for key in (*AUTH_KEY_KEYS, "AuthKeys", "auth_keys", "Keys", "keys", "Data"):
                value = payload.get(key)
                if isinstance(value, (list, tuple)):
                    values.extend(str(item).strip() for item in value if str(item).strip())
                elif isinstance(value, dict):
                    values.extend(cls._extract_auth_keys(value))
                elif value not in (None, ""):
                    values.append(str(value).strip())
        elif isinstance(payload, list):
            for item in payload:
                values.extend(cls._extract_auth_keys(item))
        elif payload not in (None, ""):
            values.append(str(payload).strip())
        seen = set()
        result = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @staticmethod
    def _extract_uuid_from_qr_url(qr_url: str) -> str:
        if not qr_url:
            return ""
        parsed = urlparse(qr_url)
        parts = [part for part in parsed.path.split("/") if part]
        return parts[-1] if parts else ""

    def _sync_key_from_url(self, qr_url: str) -> None:
        parsed = urlparse(qr_url or "")
        query = parse_qs(parsed.query)
        key = (query.get("key") or [""])[-1]
        if key and not self.token_key:
            self.token_key = key

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _truthy_login_value(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value) in {1, 2, 200, 201}
        text = str(value or "").strip().lower()
        return text in {"true", "yes", "online", "logged_in", "1", "2", "200", "201", "在线"}

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

    def _extract_base64_from_payload(self, payload: Any) -> str:
        if isinstance(payload, str):
            text = payload.strip()
            if text.startswith("data:") and "," in text:
                return text.split(",", 1)[1].strip()
            return text
        if isinstance(payload, list):
            for item in payload:
                value = self._extract_base64_from_payload(item)
                if value:
                    return value
            return ""
        if isinstance(payload, dict):
            for key in ("FileData", "fileData", "base64", "Base64", "data", "Data", "buffer", "Buffer"):
                if key in payload:
                    value = self._extract_base64_from_payload(payload.get(key))
                    if value:
                        return value
            for value in payload.values():
                nested = self._extract_base64_from_payload(value)
                if nested:
                    return nested
        return ""

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
