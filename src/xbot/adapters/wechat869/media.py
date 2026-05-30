from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from xbot.core.config import Wechat869AdapterConfig
from xbot.core.logging import logger


class Wechat869MediaResolver:
    def __init__(self, config: Wechat869AdapterConfig, client=None) -> None:
        self.config = config
        self.client = client

    async def enrich(self, raw: dict[str, Any], message: dict[str, Any], *, msg_type: int, conversation_id: str, msg_id: str) -> dict:
        attachments: list[dict[str, Any]] = []
        if not self.config.media_enabled:
            return {"attachments": attachments, "quote": self.extract_quote(message)}

        if msg_type == 3:
            image = await self._image_attachment(message, conversation_id=conversation_id, msg_id=msg_id, quoted=False)
            if image:
                attachments.append(image)
        elif msg_type == 49:
            file_attachment = await self._file_attachment(message, conversation_id=conversation_id, msg_id=msg_id, quoted=False)
            if file_attachment:
                attachments.append(file_attachment)

        quote = self.extract_quote(message)
        if quote:
            quote_attachments = []
            quote_type = int(quote.get("msg_type") or 0)
            quote_id = str(quote.get("message_id") or msg_id or "").strip()
            if quote_type == 3:
                image = await self._image_attachment(quote.get("raw") or quote, conversation_id=conversation_id, msg_id=quote_id, quoted=True)
                if image:
                    quote_attachments.append(image)
            elif quote_type == 49:
                file_attachment = await self._file_attachment(quote.get("raw") or quote, conversation_id=conversation_id, msg_id=quote_id, quoted=True)
                if file_attachment:
                    quote_attachments.append(file_attachment)
            quote["attachments"] = quote_attachments
        return {"attachments": attachments, "quote": quote}

    def extract_quote(self, message: dict[str, Any]) -> dict[str, Any] | None:
        quote = message.get("Quote") or message.get("quote") or message.get("refermsg") or message.get("ReferMsg")
        if isinstance(quote, str):
            quote = self._loads_jsonish(quote) or self._quote_from_xml(quote)
        if not isinstance(quote, dict):
            xml = self._pick_text(message, ("Content", "content", "Xml", "xml"))
            quote = self._quote_from_xml(xml)
        if not isinstance(quote, dict) or not quote:
            return None
        msg_type = self._pick_int(quote, ("MsgType", "msg_type", "type"), 0)
        content = self._pick_text(quote, ("Content", "content", "title", "Title"))
        sender = self._pick_text(quote, ("FromWxid", "from_wxid", "FromUserName", "from_user_name", "sender"))
        return {
            "message_id": self._pick_text(quote, ("NewMsgId", "MsgId", "new_msg_id", "msg_id", "message_id")),
            "sender_wxid": sender,
            "sender_name": self._pick_text(quote, ("Nickname", "nickname", "SenderNickName", "sender_name")),
            "msg_type": msg_type,
            "content": content,
            "raw": quote,
        }

    async def _image_attachment(self, data: dict[str, Any], *, conversation_id: str, msg_id: str, quoted: bool) -> dict[str, Any] | None:
        image_meta = self._image_meta(data)
        image_bytes = self._decode_bytes_from_keys(data, ("Image", "image", "File", "file", "FileData", "fileData"))
        status = "metadata_only"
        error = ""
        if not image_bytes and self.config.auto_download_images and image_meta.get("aeskey") and image_meta.get("cdn_url"):
            try:
                image_bytes = await self.client.download_image(image_meta["aeskey"], image_meta["cdn_url"]) if self.client else b""
            except Exception as exc:
                error = str(exc)
                logger.warning("Wechat869 image download failed: msg_id={} error={}", msg_id, exc)
        if image_bytes:
            if len(image_bytes) > int(self.config.max_image_bytes):
                status = "too_large"
                image_bytes = b""
            else:
                status = "downloaded"
        filename = self._safe_filename(str(data.get("Filename") or data.get("filename") or "wechat_image"), "jpg")
        attachment = self._base_attachment("image", data, filename, image_meta, quoted=quoted, status=status, error=error)
        if image_bytes:
            path, sha256 = self._save_bytes(image_bytes, conversation_id=conversation_id, msg_id=msg_id, filename=filename)
            attachment.update(
                {
                    "local_path": str(path),
                    "sha256": sha256,
                    "size": len(image_bytes),
                    "mime": self._mime_for(filename, image_bytes, fallback="image/jpeg"),
                    "download_status": "downloaded",
                }
            )
        return attachment

    async def _file_attachment(self, data: dict[str, Any], *, conversation_id: str, msg_id: str, quoted: bool) -> dict[str, Any] | None:
        file_meta = self._file_meta(data)
        if not file_meta:
            return None
        file_bytes = self._decode_bytes_from_keys(data, ("File", "file", "FileData", "fileData", "data_base64"))
        status = "metadata_only"
        error = ""
        if not file_bytes and self.config.auto_download_files and file_meta.get("aeskey") and file_meta.get("file_url"):
            try:
                logger.info(
                    "Wechat869 file download via CDN: msg_id={} filename={} size={}",
                    msg_id,
                    file_meta.get("filename") or "",
                    file_meta.get("size") or 0,
                )
                file_bytes = await self.client.download_file(file_meta["aeskey"], file_meta["file_url"]) if self.client else b""
            except Exception as exc:
                error = str(exc)
                logger.warning("Wechat869 file download failed: msg_id={} error={}", msg_id, exc)
        if not file_bytes and self.config.auto_download_files and file_meta.get("attachid"):
            try:
                logger.info(
                    "Wechat869 file download via attachid: msg_id={} filename={} size={}",
                    msg_id,
                    file_meta.get("filename") or "",
                    file_meta.get("size") or 0,
                )
                file_bytes = await self.client.download_attach(file_meta["attachid"]) if self.client and hasattr(self.client, "download_attach") else b""
            except Exception as exc:
                error = str(exc)
                logger.warning("Wechat869 attach download failed: msg_id={} error={}", msg_id, exc)
        if file_bytes:
            if len(file_bytes) > int(self.config.max_file_bytes):
                status = "too_large"
                file_bytes = b""
            else:
                status = "downloaded"
        elif self.config.auto_download_files and (file_meta.get("aeskey") or file_meta.get("attachid")):
            status = "download_empty"
        filename = self._safe_filename(file_meta.get("filename") or "wechat_file", file_meta.get("extension") or "")
        attachment = self._base_attachment("file", data, filename, file_meta, quoted=quoted, status=status, error=error)
        if file_bytes:
            path, sha256 = self._save_bytes(file_bytes, conversation_id=conversation_id, msg_id=msg_id, filename=filename)
            attachment.update(
                {
                    "local_path": str(path),
                    "sha256": sha256,
                    "size": len(file_bytes),
                    "mime": mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    "download_status": "downloaded",
                }
            )
        return attachment

    def _base_attachment(self, kind: str, data: dict[str, Any], filename: str, meta: dict[str, Any], *, quoted: bool, status: str, error: str) -> dict[str, Any]:
        size = int(meta.get("size") or data.get("FileSize") or data.get("file_size") or 0)
        result = {
            "kind": kind,
            "filename": filename,
            "size": size,
            "mime": mimetypes.guess_type(filename)[0] or ("image/jpeg" if kind == "image" else "application/octet-stream"),
            "download_status": status,
            "quoted": quoted,
            "source": "wechat869",
            "metadata": {key: value for key, value in meta.items() if value not in (None, "")},
        }
        if error:
            result["error"] = error
        return result

    def _image_meta(self, data: dict[str, Any]) -> dict[str, Any]:
        xml_meta = self._image_meta_from_xml(self._pick_text(data, ("Content", "content", "Xml", "xml")))
        direct = {
            "aeskey": self._pick_text(data, ("aeskey", "AesKey", "cdnthumbaeskey")),
            "cdnmidimgurl": self._pick_text(data, ("cdnmidimgurl", "CdnMidImgUrl")),
            "cdnbigimgurl": self._pick_text(data, ("cdnbigimgurl", "CdnBigImgUrl")),
            "md5": self._pick_text(data, ("md5", "Md5", "ImageMD5")),
            "size": self._pick_int(data, ("length", "FileSize", "size"), 0),
        }
        merged = {**xml_meta, **{k: v for k, v in direct.items() if v not in ("", 0)}}
        merged["cdn_url"] = merged.get("cdnbigimgurl") or merged.get("cdnmidimgurl") or ""
        return merged

    def _file_meta(self, data: dict[str, Any]) -> dict[str, Any]:
        appattach = data.get("appattach") if isinstance(data.get("appattach"), dict) else {}
        xml_meta = self._file_meta_from_xml(self._pick_text(data, ("Content", "content", "Xml", "xml")))
        merged = {**xml_meta, **appattach}
        has_file_marker = bool(
            merged
            or data.get("File")
            or data.get("file")
            or data.get("FileData")
            or data.get("fileData")
            or data.get("Filename")
            or data.get("filename")
            or data.get("FileName")
            or data.get("FileExtend")
            or data.get("attachid")
            or data.get("FileURL")
        )
        if not has_file_marker:
            return {}
        content_name = self._pick_text(data, ("Content", "content", "title", "Title"))
        if self._xml_fragment(content_name).startswith("<"):
            content_name = ""
        filename = (
            self._pick_text(data, ("Filename", "filename", "FileName"))
            or str(merged.get("title") or "")
            or content_name
        )
        extension = str(merged.get("fileext") or data.get("FileExtend") or "").strip().lstrip(".")
        size = int(merged.get("totallen") or data.get("FileSize") or data.get("file_size") or 0)
        attach_id = str(merged.get("attachid") or data.get("attachid") or "").strip()
        aeskey = str(merged.get("aeskey") or merged.get("cdnattachaeskey") or data.get("aeskey") or "").strip()
        file_url = str(merged.get("cdnattachurl") or merged.get("file_url") or data.get("FileURL") or "").strip()
        return {
            "filename": filename or "wechat_file",
            "extension": extension,
            "size": size,
            "attachid": attach_id,
            "aeskey": aeskey,
            "file_url": file_url,
        }

    def _image_meta_from_xml(self, text: str) -> dict[str, Any]:
        text = self._xml_fragment(text)
        if "<" not in text or "img" not in text:
            return {}
        try:
            root = ET.fromstring(text)
        except Exception:
            return {}
        img = root.find(".//img")
        if img is None:
            return {}
        return {
            "aeskey": img.get("aeskey") or img.get("cdnthumbaeskey") or "",
            "cdnmidimgurl": img.get("cdnmidimgurl") or "",
            "cdnbigimgurl": img.get("cdnbigimgurl") or "",
            "md5": img.get("md5") or "",
            "size": int(img.get("length") or 0),
        }

    def _file_meta_from_xml(self, text: str) -> dict[str, Any]:
        text = self._xml_fragment(text)
        if "<" not in text or "appattach" not in text:
            return {}
        try:
            root = ET.fromstring(text)
        except Exception:
            return {}
        attach = root.find(".//appattach")
        if attach is None:
            return {}
        data = {}
        for child in list(attach):
            data[child.tag] = (child.text or "").strip()
        title = root.find(".//title")
        if title is not None and title.text:
            data.setdefault("title", title.text.strip())
        return data

    def _quote_from_xml(self, text: str) -> dict[str, Any] | None:
        text = self._xml_fragment(text)
        if "<" not in text or "refermsg" not in text:
            return None
        try:
            root = ET.fromstring(text)
        except Exception:
            return None
        refer = root.find(".//refermsg")
        if refer is None:
            return None
        data = {}
        for child in list(refer):
            data[child.tag] = (child.text or "").strip()
        return data

    def _xml_fragment(self, text: str) -> str:
        text = str(text or "").strip()
        index = text.find("<")
        if index > 0:
            return text[index:].strip()
        return text

    def _save_bytes(self, data: bytes, *, conversation_id: str, msg_id: str, filename: str) -> tuple[Path, str]:
        sha256 = hashlib.sha256(data).hexdigest()
        today = datetime.utcnow()
        safe_conversation = self._safe_path_part(conversation_id or "unknown")
        safe_msg = self._safe_path_part(msg_id or sha256[:16])
        target_dir = Path(self.config.media_dir) / f"{today:%Y}" / f"{today:%m}" / f"{today:%d}" / safe_conversation / safe_msg
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / self._safe_filename(filename or sha256[:16], "")
        if target.exists() and target.read_bytes() == data:
            return target, sha256
        if target.exists():
            target = target_dir / f"{target.stem}_{sha256[:8]}{target.suffix}"
        target.write_bytes(data)
        return target, sha256

    def _decode_bytes_from_keys(self, data: dict[str, Any], keys: tuple[str, ...]) -> bytes:
        for key in keys:
            if key in data:
                decoded = self._decode_bytes(data.get(key))
                if decoded:
                    return decoded
        return b""

    def _decode_bytes(self, value: Any) -> bytes:
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, dict):
            for key in ("buffer", "Buffer", "FileData", "fileData", "base64", "Base64", "data", "Data", "Image"):
                decoded = self._decode_bytes(value.get(key))
                if decoded:
                    return decoded
            return b""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return b""
            if text.startswith("data:") and "," in text:
                text = text.split(",", 1)[1]
            text = "".join(text.split())
            try:
                return base64.b64decode(text, validate=True)
            except Exception:
                return b""
        return b""

    def _loads_jsonish(self, text: str) -> Any:
        import json

        try:
            return json.loads(text)
        except Exception:
            return None

    def _pick_text(self, raw: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            if key not in raw:
                continue
            value = raw.get(key)
            if isinstance(value, dict):
                for nested_key in ("str", "Str", "string", "String", "value", "Value", "text", "Text"):
                    nested = value.get(nested_key)
                    if nested not in (None, ""):
                        return str(nested)
            if value not in (None, ""):
                return str(value)
        return ""

    def _pick_int(self, raw: dict[str, Any], keys: tuple[str, ...], default: int = 0) -> int:
        text = self._pick_text(raw, keys)
        try:
            return int(text)
        except (TypeError, ValueError):
            return default

    def _safe_filename(self, filename: str, default_ext: str) -> str:
        name = Path(str(filename or "wechat_file")).name
        name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .") or "wechat_file"
        if default_ext and not Path(name).suffix:
            name = f"{name}.{default_ext.lstrip('.')}"
        return name[:200]

    def _safe_path_part(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.@-]+", "_", str(value or "unknown"))[:160] or "unknown"

    def _mime_for(self, filename: str, data: bytes, *, fallback: str) -> str:
        guessed = mimetypes.guess_type(filename)[0]
        if guessed:
            return guessed
        if data.startswith(b"\x89PNG"):
            return "image/png"
        if data.startswith(b"GIF"):
            return "image/gif"
        if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
            return "image/webp"
        return fallback
