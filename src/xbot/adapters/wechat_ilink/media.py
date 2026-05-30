from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from xbot.core.config import WechatIlinkAdapterConfig
from xbot.core.logging import logger


class WechatIlinkMediaResolver:
    def __init__(self, config: WechatIlinkAdapterConfig, client=None) -> None:
        self.config = config
        self.client = client

    async def attachment_from_item(
        self,
        item: dict[str, Any],
        *,
        conversation_id: str,
        msg_id: str,
        quoted: bool,
    ) -> dict[str, Any] | None:
        kind, filename, media, size = self._item_media(item)
        if not kind:
            return None
        status = "metadata_only"
        error = ""
        data = b""
        should_download = (
            quoted
            and self.config.media_enabled
            and ((kind == "image" and self.config.auto_download_images) or (kind != "image" and self.config.auto_download_files))
        )
        if should_download and media:
            try:
                data = await self.download_media(media, label=f"ilink {kind} {msg_id}")
            except Exception as exc:
                error = str(exc)
                logger.warning("WechatIlink media download failed: msg_id={} kind={} error={}", msg_id, kind, exc)
        max_bytes = self.config.max_image_bytes if kind == "image" else self.config.max_file_bytes
        if data:
            if len(data) > int(max_bytes):
                status = "too_large"
                data = b""
            else:
                status = "downloaded"
                size = len(data)
        elif should_download and media:
            status = "download_empty"
        attachment = {
            "kind": kind,
            "filename": self._safe_filename(filename or f"wechat_ilink_{kind}", "jpg" if kind == "image" else ""),
            "size": int(size or 0),
            "mime": mimetypes.guess_type(filename or "")[0] or ("image/jpeg" if kind == "image" else "application/octet-stream"),
            "download_status": status,
            "quoted": quoted,
            "source": "wechat_ilink",
            "metadata": {"media": media} if media else {},
        }
        if error:
            attachment["error"] = error
        if data:
            path, sha256 = self._save_bytes(
                data,
                conversation_id=conversation_id,
                msg_id=msg_id,
                filename=str(attachment["filename"]),
            )
            attachment.update(
                {
                    "local_path": str(path),
                    "sha256": sha256,
                    "size": len(data),
                    "download_status": "downloaded",
                }
            )
        return attachment

    async def download_media(self, media: dict[str, Any], *, label: str = "ilink media") -> bytes:
        full_url = str(media.get("full_url") or "")
        encrypted_param = str(media.get("encrypt_query_param") or "")
        url = full_url or self._download_url(encrypted_param)
        if not url:
            return b""
        data = await self.client.download_cdn(url) if self.client and hasattr(self.client, "download_cdn") else b""
        aes_key = str(media.get("aes_key") or "")
        if not data or not aes_key:
            return data
        key = self._parse_aes_key(aes_key, label=label)
        return self._decrypt_aes_ecb(data, key)

    def _download_url(self, encrypted_param: str) -> str:
        if not encrypted_param:
            return ""
        return f"{self.config.cdn_base_url.rstrip('/')}/download?encrypted_query_param={quote(encrypted_param, safe='')}"

    def _item_media(self, item: dict[str, Any]) -> tuple[str, str, dict[str, Any], int]:
        item_type = item.get("type")
        if item_type == 2:
            image = item.get("image_item") or {}
            media = image.get("media") if isinstance(image.get("media"), dict) else {}
            if image.get("aeskey") and not media.get("aes_key"):
                media = {**media, "aes_key": base64.b64encode(bytes.fromhex(str(image["aeskey"]))).decode("ascii")}
            return "image", str(image.get("file_name") or image.get("filename") or "image.jpg"), media, int(image.get("mid_size") or image.get("hd_size") or 0)
        if item_type == 4:
            file_item = item.get("file_item") or {}
            media = file_item.get("media") if isinstance(file_item.get("media"), dict) else {}
            return "file", str(file_item.get("file_name") or "wechat_file"), media, int(file_item.get("len") or 0)
        if item_type == 5:
            video = item.get("video_item") or {}
            media = video.get("media") if isinstance(video.get("media"), dict) else {}
            return "video", str(video.get("file_name") or "video.mp4"), media, int(video.get("video_size") or 0)
        return "", "", {}, 0

    def _parse_aes_key(self, aes_key_base64: str, *, label: str) -> bytes:
        decoded = base64.b64decode(aes_key_base64)
        if len(decoded) == 16:
            return decoded
        if len(decoded) == 32 and re.fullmatch(rb"[0-9a-fA-F]{32}", decoded):
            return bytes.fromhex(decoded.decode("ascii"))
        raise ValueError(f"{label}: invalid aes_key length {len(decoded)}")

    def _decrypt_aes_ecb(self, data: bytes, key: bytes) -> bytes:
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        plain = decryptor.update(data) + decryptor.finalize()
        pad = plain[-1] if plain else 0
        if 1 <= pad <= 16 and plain.endswith(bytes([pad]) * pad):
            return plain[:-pad]
        return plain

    def _save_bytes(self, data: bytes, *, conversation_id: str, msg_id: str, filename: str) -> tuple[Path, str]:
        sha256 = hashlib.sha256(data).hexdigest()
        today = datetime.utcnow()
        target_dir = (
            Path(self.config.media_dir)
            / f"{today:%Y}"
            / f"{today:%m}"
            / f"{today:%d}"
            / self._safe_path_part(conversation_id)
            / self._safe_path_part(msg_id or sha256[:16])
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / self._safe_filename(filename or sha256[:16], "")
        if target.exists() and target.read_bytes() == data:
            return target, sha256
        if target.exists():
            target = target_dir / f"{target.stem}_{sha256[:8]}{target.suffix}"
        target.write_bytes(data)
        return target, sha256

    def _safe_filename(self, filename: str, default_ext: str) -> str:
        name = Path(str(filename or "wechat_file")).name
        name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .") or "wechat_file"
        if default_ext and not Path(name).suffix:
            name = f"{name}.{default_ext.lstrip('.')}"
        return name[:200]

    def _safe_path_part(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.@-]+", "_", str(value or "unknown"))[:160] or "unknown"
