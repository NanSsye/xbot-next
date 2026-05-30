from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import struct
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


ILINK_APP_ID = "bot"
CHANNEL_VERSION = "xbot-next/0.1.0"


class WechatIlinkError(Exception):
    def __init__(self, message: str, *, code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}

    @property
    def is_session_expired(self) -> bool:
        return self.code == -14


def _random_wechat_uin() -> str:
    value = struct.unpack(">I", os.urandom(4))[0]
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _base_info() -> dict[str, str]:
    return {"channel_version": CHANNEL_VERSION}


def _common_headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": "1",
    }


def _public_headers() -> dict[str, str]:
    return {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": "1",
    }


def _check_payload(payload: dict[str, Any], label: str) -> dict[str, Any]:
    ret = payload.get("ret")
    errcode = payload.get("errcode")
    if (isinstance(ret, int) and ret != 0) or (isinstance(errcode, int) and errcode != 0):
        code = errcode if isinstance(errcode, int) and errcode != 0 else ret
        raise WechatIlinkError(
            f"{payload.get('errmsg') or f'{label} failed'} payload={_preview_payload(payload)}",
            code=code,
            payload=payload,
        )
    return payload


def _preview_payload(payload: dict[str, Any], limit: int = 500) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"...({len(text)} chars)"


class WechatIlinkClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: int = 45,
        cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.cdn_base_url = cdn_base_url.rstrip("/")

    async def get_qr_code(self) -> dict[str, Any]:
        url = f"{self.base_url}/ilink/bot/get_bot_qrcode?bot_type=3"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, headers=_public_headers())
                payload = json.loads(response.text) if response.text else {}
                if response.status_code >= 400:
                    raise WechatIlinkError(
                        str(payload.get("errmsg") or f"get_bot_qrcode HTTP {response.status_code}"),
                        code=payload.get("errcode"),
                        payload=payload,
                    )
                return _check_payload(payload, "get_bot_qrcode")
        except httpx.TimeoutException as exc:
            raise WechatIlinkError("get_bot_qrcode 请求超时", code=-408) from exc
        except httpx.RequestError as exc:
            raise WechatIlinkError(f"get_bot_qrcode 网络异常：{exc}") from exc

    async def poll_qr_status(self, qrcode: str, *, base_url: str | None = None) -> dict[str, Any]:
        root = (base_url or self.base_url).rstrip("/")
        url = f"{root}/ilink/bot/get_qrcode_status?qrcode={quote(qrcode, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=_public_headers())
                payload = json.loads(response.text) if response.text else {}
                if response.status_code >= 400:
                    raise WechatIlinkError(
                        str(payload.get("errmsg") or f"get_qrcode_status HTTP {response.status_code}"),
                        code=payload.get("errcode"),
                        payload=payload,
                    )
                return _check_payload(payload, "get_qrcode_status")
        except httpx.TimeoutException as exc:
            raise WechatIlinkError("get_qrcode_status 请求超时", code=-408) from exc
        except httpx.RequestError as exc:
            raise WechatIlinkError(f"get_qrcode_status 网络异常：{exc}") from exc

    async def get_updates(self, cursor: str = "") -> dict[str, Any]:
        return await self._post(
            "/ilink/bot/getupdates",
            {"get_updates_buf": cursor, "base_info": _base_info()},
            timeout=self.timeout_seconds,
        )

    async def send_text(self, *, to_user_id: str, context_token: str, text: str) -> None:
        message = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": str(uuid4()),
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }
        await self._post(
            "/ilink/bot/sendmessage",
            {"msg": message, "base_info": _base_info()},
            timeout=15,
        )

    async def send_image(self, *, to_user_id: str, context_token: str, path: str, text: str = "") -> dict:
        uploaded = await self._upload_media(path=path, to_user_id=to_user_id, media_type=1)
        item = {
            "type": 2,
            "image_item": {
                "media": {
                    "encrypt_query_param": uploaded["download_param"],
                    "aes_key": base64.b64encode(uploaded["aeskey_hex"].encode("ascii")).decode("ascii"),
                    "encrypt_type": 1,
                },
                "mid_size": uploaded["cipher_size"],
            },
        }
        return await self._send_media_items(to_user_id=to_user_id, context_token=context_token, text=text, media_item=item)

    async def send_file(
        self,
        *,
        to_user_id: str,
        context_token: str,
        path: str,
        name: str | None = None,
        text: str = "",
    ) -> dict:
        uploaded = await self._upload_media(path=path, to_user_id=to_user_id, media_type=3)
        filename = name or Path(path).name
        item = {
            "type": 4,
            "file_item": {
                "media": {
                    "encrypt_query_param": uploaded["download_param"],
                    "aes_key": base64.b64encode(uploaded["aeskey_hex"].encode("ascii")).decode("ascii"),
                    "encrypt_type": 1,
                },
                "file_name": filename,
                "len": str(uploaded["raw_size"]),
            },
        }
        return await self._send_media_items(to_user_id=to_user_id, context_token=context_token, text=text, media_item=item)

    async def download_cdn(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    async def _upload_media(self, *, path: str, to_user_id: str, media_type: int) -> dict:
        data = Path(path).read_bytes()
        raw_size = len(data)
        aeskey = os.urandom(16)
        aeskey_hex = aeskey.hex()
        cipher = self._encrypt_aes_ecb(data, aeskey)
        filekey = os.urandom(16).hex()
        upload = await self._post(
            "/ilink/bot/getuploadurl",
            {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": raw_size,
                "rawfilemd5": hashlib.md5(data).hexdigest(),
                "filesize": len(cipher),
                "no_need_thumb": True,
                "aeskey": aeskey_hex,
                "base_info": _base_info(),
            },
            timeout=15,
        )
        upload_url = str(upload.get("upload_full_url") or "")
        upload_param = str(upload.get("upload_param") or "")
        if not upload_url and upload_param:
            upload_url = f"{self.cdn_base_url}/upload?encrypted_query_param={quote(upload_param, safe='')}&filekey={quote(filekey, safe='')}"
        if not upload_url:
            raise WechatIlinkError("getuploadurl returned no upload URL", payload=upload)
        download_param = await self._upload_cdn(upload_url, cipher)
        return {
            "filekey": filekey,
            "download_param": download_param,
            "aeskey_hex": aeskey_hex,
            "raw_size": raw_size,
            "cipher_size": len(cipher),
        }

    async def _upload_cdn(self, url: str, data: bytes) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                url,
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
            if response.status_code != 200:
                raise WechatIlinkError(f"CDN upload failed: HTTP {response.status_code} {response.text}")
            download_param = response.headers.get("x-encrypted-param")
            if not download_param:
                raise WechatIlinkError("CDN upload response missing x-encrypted-param")
            return download_param

    async def _send_media_items(self, *, to_user_id: str, context_token: str, text: str, media_item: dict) -> dict:
        last_client_id = ""
        items = []
        if text:
            items.append({"type": 1, "text_item": {"text": text}})
        items.append(media_item)
        for item in items:
            last_client_id = str(uuid4())
            await self._post(
                "/ilink/bot/sendmessage",
                {
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": to_user_id,
                        "client_id": last_client_id,
                        "message_type": 2,
                        "message_state": 2,
                        "context_token": context_token,
                        "item_list": [item],
                    },
                    "base_info": _base_info(),
                },
                timeout=15,
            )
        return {"message_id": last_client_id}

    def _encrypt_aes_ecb(self, data: bytes, key: bytes) -> bytes:
        pad = 16 - (len(data) % 16)
        plain = data + bytes([pad]) * pad
        encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        return encryptor.update(plain) + encryptor.finalize()

    async def _post(self, endpoint: str, body: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=_common_headers(self.token), json=body)
                payload = json.loads(response.text) if response.text else {}
                if response.status_code >= 400:
                    raise WechatIlinkError(
                        str(payload.get("errmsg") or f"{endpoint} HTTP {response.status_code}"),
                        code=payload.get("errcode"),
                        payload=payload,
                    )
                return _check_payload(payload, endpoint)
        except httpx.TimeoutException as exc:
            raise WechatIlinkError(f"{endpoint} 请求超时", code=-408) from exc
        except httpx.RequestError as exc:
            raise WechatIlinkError(f"{endpoint} 网络异常：{exc}") from exc
