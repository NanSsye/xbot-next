from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext
from xbot.messaging.models import Message, Reply
try:
    from loguru import logger
except Exception:
    from xbot.core.logging import logger

from loguru import logger
import aiohttp
from aiohttp import web
import asyncio
import os
import tomllib
import base64
import time
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import traceback
import mimetypes
import shutil
from datetime import datetime, timedelta
try:
    from curl_cffi import requests as curl_requests
except Exception:
    import requests as curl_requests




# 媒体缓存过期时间 (秒)
MEDIA_CACHE_TIMEOUT = 1200

# 全局文件存储目录
FILES_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "files"))
GROUP_MEMBERS_DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database", "contacts.db")
)


def on_image_message(*args, **kwargs):
    return lambda fn: fn
def on_file_message(*args, **kwargs):
    return lambda fn: fn
def on_video_message(*args, **kwargs):
    return lambda fn: fn
def on_voice_message(*args, **kwargs):
    return lambda fn: fn
def on_at_message(*args, **kwargs):
    return lambda fn: fn
def on_quote_message(*args, **kwargs):
    return lambda fn: fn
def on_xml_message(*args, **kwargs):
    return lambda fn: fn
def on_text_message(*args, **kwargs):
    return lambda fn: fn

def get_contact_from_db(*args, **kwargs):
    return None
def get_group_member_from_db(group_wxid, member_wxid):
    try:
        conn = group_members_db_module._connect()
        try:
            cur = conn.execute(
                "SELECT member_wxid, nickname, remark, display_name FROM group_members WHERE group_wxid=? AND member_wxid=?",
                (group_wxid, member_wxid),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"wxid": row[0], "nickname": row[1], "remark": row[2], "display_name": row[3]}
        finally:
            conn.close()
    except Exception:
        return None
def get_all_contacts(*args, **kwargs):
    return []
def get_contacts_from_db(*args, **kwargs):
    return []

class group_members_db_module:
    DB_PATH = GROUP_MEMBERS_DB_PATH

    @staticmethod
    def _connect():
        import sqlite3
        os.makedirs(os.path.dirname(group_members_db_module.DB_PATH), exist_ok=True)
        conn = sqlite3.connect(group_members_db_module.DB_PATH)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_members ("
            "group_wxid TEXT NOT NULL, "
            "member_wxid TEXT NOT NULL, "
            "nickname TEXT DEFAULT '', "
            "remark TEXT DEFAULT '', "
            "display_name TEXT DEFAULT '', "
            "raw_json TEXT DEFAULT '', "
            "updated_at INTEGER NOT NULL, "
            "PRIMARY KEY(group_wxid, member_wxid))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS contacts ("
            "wxid TEXT PRIMARY KEY, nickname TEXT DEFAULT '', remark TEXT DEFAULT '', "
            "alias TEXT DEFAULT '', type TEXT DEFAULT '', updated_at INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_limits ("
            "group_wxid TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_time REAL NOT NULL, updated_at INTEGER NOT NULL)"
        )
        return conn

    @staticmethod
    def _pick(item, *keys):
        for key in keys:
            value = item.get(key) if isinstance(item, dict) else None
            if value not in (None, ""):
                if isinstance(value, dict) and "str" in value:
                    return str(value.get("str") or "")
                return str(value)
        return ""

    @staticmethod
    def save_group_members_to_db(group_wxid, members):
        import json
        now = int(time.time())
        conn = group_members_db_module._connect()
        try:
            rows = []
            for item in members or []:
                if not isinstance(item, dict):
                    continue
                wxid = group_members_db_module._pick(
                    item,
                    "wxid", "Wxid", "WxId", "UserName", "Username", "userName", "user_name",
                    "member_wxid", "MemberWxid", "MemberId", "MemberID", "memberId", "member_id",
                    "UserId", "UserID", "userId", "user_id", "FromUserName",
                )
                if not wxid:
                    continue
                nickname = group_members_db_module._pick(
                    item, "nickname", "NickName", "Nickname", "nickName", "display_name", "DisplayName",
                    "ChatRoomNickName", "MemberName", "memberName", "SenderNickname", "SenderNickName", "name",
                )
                remark = group_members_db_module._pick(item, "remark", "Remark", "RemarkName")
                display = remark or nickname or wxid
                rows.append((group_wxid, wxid, nickname, remark, display, json.dumps(item, ensure_ascii=False), now))
            if not rows:
                return False
            conn.executemany(
                "INSERT OR REPLACE INTO group_members "
                "(group_wxid, member_wxid, nickname, remark, display_name, raw_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
            return True
        finally:
            conn.close()



class _XBot869BotShim:
    def __init__(self, ctx: PluginContext, plugin: "OpenClawBridgePlugin") -> None:
        self.ctx = ctx
        self.plugin = plugin
        settings = getattr(ctx, "settings", None)
        wechat = getattr(getattr(settings, "adapters", None), "wechat869", None) if settings else None
        self.wxid = str(getattr(wechat, "bot_wxid", "") or "")
        self.nickname = str(getattr(wechat, "bot_nickname", "") or "")
        self._client = None
        self._handled_msg_ids: set[str] = set()

    def _get_client(self):
        if self._client is not None:
            return self._client
        adapters = getattr(getattr(self.ctx, "plugins", None), "_settings", None)
        runtime_adapters = getattr(self.ctx, "adapters", None)
        # Prefer live adapter from runtime context if reachable through manager internals.
        manager = getattr(self.ctx, "plugins", None)
        settings = getattr(manager, "_settings", None) if manager else getattr(self.ctx, "settings", None)
        cfg = getattr(getattr(settings, "adapters", None), "wechat869", None) if settings else None
        if cfg is None:
            raise RuntimeError("wechat869 config unavailable")
        from xbot.adapters.wechat869.client import Wechat869Client
        self._client = Wechat869Client(
            host=cfg.host,
            port=cfg.port,
            admin_key=getattr(cfg, "admin_key", ""),
            token_key=getattr(cfg, "token_key", ""),
            ws_url=getattr(cfg, "ws_url", ""),
            timeout_seconds=getattr(cfg, "connect_timeout_seconds", 30),
        )
        return self._client

    async def send_text_message(self, wxid, text):
        return await self._get_client().send_text_message(wxid, text)

    async def send_at_message(self, wxid, text, at_wxids):
        return await self._get_client().send_text_message(wxid, text, at_wxids)

    async def send_image_message(self, wxid, path):
        return await self._get_client().send_image_message(wxid, path)

    async def send_file_message(self, wxid, path):
        return await self._get_client().send_file_message(wxid, path)

    async def send_video_message(self, wxid, path, *args, **kwargs):
        return await self.send_file_message(wxid, path)

    async def send_voice_message(self, wxid, voice_bytes, format="wav"):
        import tempfile
        suffix = "." + str(format or "wav").lstrip(".")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(voice_bytes)
            tmp = f.name
        try:
            return await self.send_file_message(wxid, tmp)
        finally:
            try: os.unlink(tmp)
            except Exception: pass

    async def send_app_message(self, wxid, xml, content_type=6):
        return await self._get_client().send_app_message(wxid, xml, content_type) if hasattr(self._get_client(), "send_app_message") else await self.send_text_message(wxid, xml)

    async def download_image(self, aes_key, cdn_url):
        return await self._get_client().download_image(aes_key, cdn_url)

    async def download_attach(self, attach_id):
        return await self._get_client().download_attach(attach_id)

    async def call_path(self, path, *, body=None, method="POST", key=None):
        return await self._get_client().call_path(path, body=body, method=method, key=key)

    async def request(self, path, *, body=None, method="POST", key=None):
        return await self._get_client().request(path, body=body, method=method, key=key)

    async def get_chatroom_member_list(self, group_wxid):
        return []
    async def get_chatroom_members(self, group_wxid):
        return []
    def get_local_nickname(self, wxid, group_wxid=None):
        return ""
    async def get_contract_detail(self, *args, **kwargs):
        return None
    async def get_nickname(self, *args, **kwargs):
        return ""

class OpenClawBridgePlugin(PluginBase):
    description = "OpenClaw 桥接插件"
    author = "Antigravity"
    version = "1.0.0"
    priority = 30
    
    def __init__(self):
        super().__init__()
        self.bot = None
        self.robot_names = []
        self.file_cache = {} # {md5: {path, timestamp, type, name}}
        self.user_latest_files = {} # {wxid: {md5, timestamp, type}}
        self._recent_media_sent = {} # {"url|to": timestamp} 媒体发送去重
        self._reply_contexts = {}
        self._reply_context_ttl_seconds = 1800
        self._openclaw_request_timings = {}
        self._openclaw_request_ttl_seconds = 3600
        self._openclaw_slow_callback_seconds = 10.0
        # 联系人缓存: {wxid/chatroom_id: {id, name, type}}
        self.contacts_cache = {}
        self.contacts_cache_time = 0
        self.contacts_cache_ttl = 300  # 5分钟
        self._group_member_name_cache = {}
        self._group_member_name_cache_ttl = 21600
        self._group_member_empty_cache_ttl = 120
        self._group_member_sync_tasks = {}
        self._group_member_persist_lock = asyncio.Lock()
        self.config = self.load_config()
        self._group_member_name_cache_ttl = int(
            self.config.get("openclaw", {}).get("group_member_cache_ttl_seconds", self._group_member_name_cache_ttl)
        )
        self._group_member_empty_cache_ttl = int(
            self.config.get("openclaw", {}).get("group_member_empty_cache_ttl_seconds", self._group_member_empty_cache_ttl)
        )
        self.ws_url = self.config["openclaw"].get("ws_url", "ws://192.168.50.38:9093/ws")
        self.ws_reconnect_enabled = self.config["openclaw"].get("ws_reconnect_enabled", True)
        self.ws_ping_interval_seconds = int(self.config["openclaw"].get("ws_ping_interval_seconds", 30))
        self.ws_connect_timeout_seconds = int(self.config["openclaw"].get("ws_connect_timeout_seconds", 15))
        # account_id: 优先用配置值，否则从 robot_stat.json 读取已登录的 wxid
        self.account_id = self.config["openclaw"].get("account_id", "")
        if not self.account_id:
            try:
                robot_stat_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resource", "robot_stat.json")
                if os.path.exists(robot_stat_path):
                    with open(robot_stat_path, "r", encoding="utf-8") as f:
                        robot_stat = json.load(f)
                    self.account_id = robot_stat.get("wxid", "") or ""
                    if self.account_id:
                        logger.info(f"OpenClawBridge 从 robot_stat.json 读取 accountId: {self.account_id}")
            except Exception as e:
                logger.warning(f"读取 robot_stat.json 获取 wxid 失败: {e}")
        self._ws_session = None
        self._ws = None
        self._ws_task = None
        self._ws_heartbeat_task = None
        self._ws_send_lock = asyncio.Lock()
        self._ws_last_pong_ts = 0.0
        
        # 频率限制配置
        self.limits_config = self.config.get("limits", {
            "enable_group_limit": False,
            "default_group_limit": 50,
            "limit_reached_message": "本群今日提问次数已达上限，请明天再来吧~",
            "custom_groups": {}
        })
        
        # OpenClaw Workspace 路径
        self.workspace_path = self.config["openclaw"].get("workspace_path")
        if not self.workspace_path:
             self.workspace_path = os.path.expanduser("~/.openclaw/workspace")
        # 兼容相对路径
        if not os.path.isabs(self.workspace_path):
             self.workspace_path = os.path.abspath(os.path.join(os.getcwd(), self.workspace_path))
        logger.info(f"OpenClaw Workspace 路径: {self.workspace_path}")
        
        # 主人配置
        self.owner_wxid = self.config.get("owner", {}).get("wxid", "")
        self.owner_aliases = [a.lower() for a in self.config.get("owner", {}).get("aliases", [])]
        
    def load_config(self):
         config_path = os.path.join(os.path.dirname(__file__), "config.toml")
         try:
             with open(config_path, "r", encoding="utf-8-sig") as f:
                 return tomllib.loads(f.read())
         except Exception as e:
             logger.error(f"加载 OpenClawBridge 配置失败: {e}")
             return {
                 "openclaw": {
                     "ws_url": "ws://127.0.0.1:9093/ws",
                     "ws_reconnect_enabled": True,
                     "ws_ping_interval_seconds": 30,
                     "ws_connect_timeout_seconds": 15
                 },
                 "filters": {
                     "mention_only": True, 
                     "allow_groups": True, 
                     "trigger_words": [],
                     "filter_mode": "None",
                     "whitelist": [],
                     "blacklist": [],
                     "disable_private_chat_at_trigger": False
                 },
                 "prompt": {
                     "enabled": False,
                     "mode": "body_for_agent",
                     "text": ""
                 }
             }

    def _get_group_limit_reset_time(self, now=None):
        """返回下一次本地自然日零点的时间戳。"""
        now_ts = time.time() if now is None else now
        now_dt = datetime.fromtimestamp(now_ts)
        next_midnight = now_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return next_midnight.timestamp()

    def _should_reset_group_limit_record(self, record, now=None):
        """判断群限流记录是否已经跨过当前自然日窗口。"""
        now_ts = time.time() if now is None else now
        try:
            record_reset_time = float(record.get("reset_time", 0))
        except (TypeError, ValueError, AttributeError):
            return True

        daily_reset_time = self._get_group_limit_reset_time(now_ts)
        return now_ts >= record_reset_time or int(record_reset_time) != int(daily_reset_time)


    async def on_load(self, ctx: PluginContext) -> None:
        self._xbot_ctx = ctx
        self.bot = _XBot869BotShim(ctx, self)
        await self.on_enable(self.bot)
        await self.async_init()

    async def on_unload(self) -> None:
        await self.on_disable()

    async def on_message(self, message: Message, ctx: PluginContext):
        self._xbot_ctx = ctx
        if not self.bot:
            self.bot = _XBot869BotShim(ctx, self)
        legacy = self._xbot_message_to_legacy(message)
        msg_type = int(legacy.get("MsgType") or 1)
        if legacy.get("Quote"):
            await self.handle_quote_message(self.bot, legacy)
        elif msg_type == 3 or message.type == "image":
            await self.handle_image(self.bot, legacy)
            return False
        elif msg_type in (34,):
            await self.handle_voice(self.bot, legacy)
            return False
        elif msg_type in (43,):
            await self.handle_video(self.bot, legacy)
            return False
        elif message.type == "file" or msg_type == 49:
            await self.handle_file(self.bot, legacy)
            return False
        else:
            await self.handle_text(self.bot, legacy)
        return bool(legacy.get("_is_handled"))

    def _xbot_message_to_legacy(self, message: Message) -> dict:
        raw = message.raw if isinstance(message.raw, dict) else {}
        scope = raw.get("scope") or ("group" if message.conversation_id.endswith("@chatroom") else "private")
        is_group = scope == "group"
        sender = str(raw.get("sender_wxid") or message.sender_id or "")
        from_wxid = str(raw.get("group_wxid") or message.conversation_id if is_group else sender or message.conversation_id)
        msg = dict(raw)
        msg.setdefault("MsgId", raw.get("message_id") or raw.get("msg_id") or message.id)
        msg.setdefault("NewMsgId", msg.get("MsgId"))
        msg.setdefault("Content", message.content or raw.get("content") or "")
        msg.setdefault("FromWxid", from_wxid)
        msg.setdefault("SenderWxid", sender)
        msg.setdefault("IsGroup", is_group)
        msg.setdefault("MsgType", raw.get("MsgType") or raw.get("msg_type") or (3 if message.type == "image" else 49 if message.type == "file" else 1))
        msg.setdefault("Nickname", message.sender_name or raw.get("sender_name") or "")
        if raw.get("mentions_bot"):
            bot_id = getattr(self.bot, "wxid", "") or raw.get("bot_wxid") or ""
            msg.setdefault("At", [bot_id] if bot_id else [])
        quote = raw.get("quote")
        if isinstance(quote, dict):
            qraw = quote.get("raw") if isinstance(quote.get("raw"), dict) else quote
            q = dict(qraw)
            q.setdefault("Content", quote.get("content") or qraw.get("Content") or "")
            q.setdefault("FromWxid", quote.get("sender_wxid") or qraw.get("FromWxid") or "")
            q.setdefault("Nickname", quote.get("sender_name") or qraw.get("Nickname") or "")
            q.setdefault("MsgType", quote.get("msg_type") or qraw.get("MsgType") or 1)
            atts = quote.get("attachments") or []
            if atts and isinstance(atts[0], dict):
                local = atts[0].get("local_path")
                kind = atts[0].get("kind")
                if local:
                    if kind == "image": q.setdefault("image_path", local)
                    elif kind == "video": q.setdefault("video_path", local)
                    elif kind == "voice": q.setdefault("voice_path", local)
                    else: q.setdefault("file_path", local)
            msg["Quote"] = q
        atts = raw.get("attachments") or []
        if atts and isinstance(atts[0], dict):
            att = atts[0]
            if att.get("local_path"):
                msg.setdefault("FilePath", att.get("local_path"))
                msg.setdefault("FileName", att.get("filename") or os.path.basename(str(att.get("local_path"))))
                msg.setdefault("FileMd5", att.get("sha256") or "")
        return msg

    def _decode_download_payload(self, payload):
        """将 869 下载接口返回值统一解码为 bytes。"""
        if not payload:
            return b""
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, dict):
            return self._decode_download_payload(self._extract_download_base64(payload))
        if isinstance(payload, str):
            try:
                return base64.b64decode(payload)
            except Exception as e:
                logger.warning(f"解码下载数据失败: {e}")
                return b""
        return b""

    def _build_cdn_attach_id(self, file_url: str, aes_key: str, file_type: int = 5) -> str:
        """为 Client869.download_attach 构造 CDN 直连标识。"""
        file_url = (file_url or "").strip()
        aes_key = (aes_key or "").strip()
        if not file_url or not aes_key:
            return ""
        return f"@cdn_{file_url}_{aes_key}_{int(file_type)}"

    def _parse_cdn_attach_id(self, attach_id: str) -> tuple[str, str, int | None]:
        """从 @cdn_fileurl_aeskey_filetype 中拆出 CDN 参数。"""
        if not isinstance(attach_id, str) or not attach_id.startswith("@cdn_"):
            return "", "", None
        raw = attach_id[len("@cdn_"):]
        parts = [p for p in raw.split("_") if p]
        if len(parts) < 3:
            return "", "", None
        file_url = "_".join(parts[:-2])
        aes_key = parts[-2]
        try:
            file_type = int(parts[-1])
        except (TypeError, ValueError):
            file_type = None
        return file_url, aes_key, file_type

    def _extract_download_base64(self, payload) -> str:
        """兼容提取 869 下载接口里的 base64 文件内容。"""
        if isinstance(payload, str):
            return payload
        if not isinstance(payload, dict):
            return ""

        for key in ("FileData", "fileData", "Base64", "base64", "buffer", "Buffer"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value

        for key in ("Data", "data"):
            nested = payload.get(key)
            if nested is payload:
                continue
            found = self._extract_download_base64(nested)
            if found:
                return found

        return ""

    async def _send_cdn_download_payload(self, file_url: str, aes_key: str, file_type: int) -> str:
        """在插件内直调 CDN 下载，避免依赖框架 download_attach 的固定 FileType。"""
        file_url = (file_url or "").strip()
        aes_key = (aes_key or "").strip()
        if not file_url or not aes_key or not self.bot:
            return ""

        try:
            if hasattr(self.bot, "_send_cdn_download"):
                return await self.bot._send_cdn_download(aes_key, file_url, int(file_type))

            if hasattr(self.bot, "call_path"):
                response = await self.bot.call_path(
                    "/message/SendCdnDownload",
                    body={"AesKey": aes_key, "FileURL": file_url, "FileType": int(file_type)},
                )
                return self._extract_download_base64(response)
        except Exception as e:
            logger.warning(f"引用文件：CDN 直连下载失败 (type={file_type}): {e}")
            logger.debug(traceback.format_exc())

        return ""

    async def _download_attach_with_wxid(self, attach_id: str, wxid: str) -> str:
        """按指定会话下载附件；群文件通常需要用 chatroom_id 作为 Wxid。"""
        attach_id = (attach_id or "").strip()
        wxid = (wxid or "").strip()
        if not attach_id or not wxid or not self.bot or not hasattr(self.bot, "request"):
            return ""

        try:
            response = await self.bot.request(
                "/api/Tools/DownloadFile",
                method="POST",
                body={"Wxid": wxid, "AttachId": attach_id},
                timeout=300,
            )
            downloaded = self._extract_download_base64(response)
            if downloaded:
                logger.success(f"引用文件：按会话 {wxid} 下载成功")
                return downloaded
        except Exception as e:
            logger.debug(f"引用文件：按会话 {wxid} 下载失败: {e}")

        return ""

    async def _download_quote_file_payload(
        self,
        attach_id: str,
        file_url: str,
        aes_key: str,
        wxid_candidates: list[str] | None = None,
    ) -> str:
        """下载引用文件；常规接口失败时按 CDN 元数据在插件内重试。"""
        attach_id = (attach_id or "").strip()
        file_url = (file_url or "").strip()
        aes_key = (aes_key or "").strip()

        if self.bot and hasattr(self.bot, "download_attach") and attach_id:
            try:
                downloaded = await self.bot.download_attach(attach_id)
                if downloaded:
                    return downloaded
                logger.warning("引用文件：download_attach 返回空，尝试 CDN 直连回退")
            except Exception as e:
                logger.warning(f"引用文件：download_attach 调用失败，尝试 CDN 直连回退: {e}")
                logger.debug(traceback.format_exc())

        seen_wxids = set()
        for wxid in wxid_candidates or []:
            wxid = (wxid or "").strip()
            if not wxid or wxid in seen_wxids:
                continue
            seen_wxids.add(wxid)
            downloaded = await self._download_attach_with_wxid(attach_id, wxid)
            if downloaded:
                return downloaded

        parsed_url, parsed_key, parsed_type = self._parse_cdn_attach_id(attach_id)
        cdn_url = file_url or parsed_url
        cdn_key = aes_key or parsed_key
        candidate_types = []
        for candidate in (parsed_type, 1, 5):
            if candidate is not None and candidate not in candidate_types:
                candidate_types.append(candidate)

        for file_type in candidate_types:
            downloaded = await self._send_cdn_download_payload(cdn_url, cdn_key, file_type)
            if downloaded:
                logger.success(f"引用文件：CDN 直连下载成功 (type={file_type})")
                return downloaded

        return ""

    def _publish_media_file(self, media_path: str, preferred_name: str | None = None) -> str | None:
        """
        确保媒体文件落到 FILES_DIR 下，便于 OpenClaw 通过 /files/... 访问。
        返回发布后的绝对路径；失败时返回原路径或 None。
        """
        if not media_path:
            return None
        abs_media_path = os.path.abspath(media_path)
        if not os.path.exists(abs_media_path):
            return None

        os.makedirs(FILES_DIR, exist_ok=True)
        files_root = os.path.abspath(FILES_DIR)
        try:
            common = os.path.commonpath([files_root, abs_media_path])
        except ValueError:
            common = ""
        if common == files_root:
            return abs_media_path

        safe_name = os.path.basename(preferred_name or abs_media_path)
        if not safe_name:
            safe_name = os.path.basename(abs_media_path)
        target_path = os.path.join(files_root, safe_name)
        if os.path.abspath(target_path) == abs_media_path:
            return abs_media_path

        if os.path.exists(target_path):
            try:
                if os.path.getsize(target_path) == os.path.getsize(abs_media_path):
                    return target_path
            except Exception:
                pass
            name_only, ext = os.path.splitext(safe_name)
            digest = hashlib.md5(abs_media_path.encode("utf-8", errors="ignore")).hexdigest()[:8]
            target_path = os.path.join(files_root, f"{name_only}_{digest}{ext}")

        shutil.copy2(abs_media_path, target_path)
        logger.info(f"已发布引用媒体到 files 目录: {abs_media_path} -> {target_path}")
        return target_path

    def _attach_media_url(self, media_data: dict, media_path: str, preferred_name: str | None = None) -> str | None:
        """为媒体补齐可被 OpenClaw 拉取的 /files URL。"""
        if not media_data or not media_path:
            return None
        published_path = self._publish_media_file(media_path, preferred_name=preferred_name)
        if not published_path:
            return None

        media_data["local_path"] = published_path
        base_url = self.config.get("openclaw", {}).get("download_base_url", "")
        if not base_url:
            media_data["path"] = published_path
            return published_path

        base_url = base_url.rstrip("/")
        filename = os.path.basename(published_path)
        media_url = f"{base_url}/files/{filename}"
        media_data["url"] = media_url
        media_data["path"] = media_url
        return published_path

    def _image_extension_from_bytes(self, content: bytes) -> str | None:
        """根据文件头判断图片类型，避免把下载失败的短字节串当图片。"""
        if not content or len(content) < 16:
            return None
        if content.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return ".webp"
        if content.startswith(b"BM"):
            return ".bmp"
        if content.startswith((b"II*\x00", b"MM\x00*")):
            return ".tiff"
        return None

    def _is_valid_image_file(self, path: str | None) -> bool:
        """校验本地文件是否是真图片；群聊 OpenIM 坏图通常只有几十字节。"""
        if not path or not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                head = f.read(64)
            return self._image_extension_from_bytes(head) is not None
        except Exception as e:
            logger.warning(f"校验图片文件失败: {path}, {e}")
            return False

    async def _download_quote_image_bytes(self, img_aeskey: str, img_cdn_url: str) -> bytes:
        """下载引用图片，并只返回通过图片头校验的内容。"""
        img_aeskey = (img_aeskey or "").strip()
        img_cdn_url = (img_cdn_url or "").strip()
        if not img_aeskey or not img_cdn_url or not self.bot:
            return b""

        if hasattr(self.bot, "download_image"):
            try:
                downloaded_image = await self.bot.download_image(img_aeskey, img_cdn_url)
                img_bytes = self._decode_download_payload(downloaded_image)
                if self._image_extension_from_bytes(img_bytes):
                    return img_bytes
                if img_bytes:
                    logger.warning(f"引用图片：download_image 返回非图片内容 ({len(img_bytes)} bytes)")
            except Exception as e:
                logger.warning(f"引用图片：download_image 调用失败，尝试 CDN 直连回退: {e}")
                logger.debug(traceback.format_exc())

        for file_type in (2, 3, 5, 1):
            downloaded = await self._send_cdn_download_payload(img_cdn_url, img_aeskey, file_type)
            img_bytes = self._decode_download_payload(downloaded)
            if self._image_extension_from_bytes(img_bytes):
                logger.success(f"引用图片：CDN 直连下载成功 (type={file_type})")
                return img_bytes
            if img_bytes:
                logger.warning(f"引用图片：CDN 直连返回非图片内容 (type={file_type}, {len(img_bytes)} bytes)")

        return b""

    def _extract_quote_image_metadata(self, quote: dict | None, quoted_content: str) -> tuple[str | None, str | None, str | None]:
        """统一提取引用图片的 md5、aeskey 和 CDN 地址。"""
        quote = quote or {}

        img_md5 = (quote.get("md5") or "").strip().lower() or None
        img_aeskey = (
            (quote.get("aeskey") or quote.get("cdnthumbaeskey") or quote.get("tpthumbaeskey") or "").strip() or None
        )
        img_cdn_url = (
            (
                quote.get("cdnmidimgurl")
                or quote.get("cdnbigimgurl")
                or quote.get("tpurl")
                or quote.get("tphdurl")
                or quote.get("cdnthumburl")
                or quote.get("tpthumburl")
                or ""
            ).strip()
            or None
        )

        if quoted_content:
            try:
                import html as _html

                normalized_xml = _html.unescape(quoted_content)
                if img_cdn_url:
                    img_cdn_url = _html.unescape(img_cdn_url)
            except Exception:
                normalized_xml = quoted_content

            xml_md5_match = re.search(r'md5="([a-fA-F0-9]{32})"', normalized_xml)
            if not xml_md5_match:
                xml_md5_match = re.search(r"<md5>([a-fA-F0-9]{32})</md5>", normalized_xml, re.IGNORECASE)
            xml_aeskey_match = re.search(r'aeskey="([a-fA-F0-9]+)"', normalized_xml, re.IGNORECASE)
            xml_tpaeskey_match = re.search(r'tpthumbaeskey="([a-fA-F0-9]+)"', normalized_xml, re.IGNORECASE)
            xml_cdnmid_match = re.search(r'cdnmidimgurl="([^"]+)"', normalized_xml)
            xml_cdnbig_match = re.search(r'cdnbigimgurl="([^"]+)"', normalized_xml)
            xml_cdnthumb_match = re.search(r'cdnthumburl="([^"]+)"', normalized_xml)
            xml_tp_match = re.search(r'tpurl="([^"]+)"', normalized_xml)
            xml_tphd_match = re.search(r'tphdurl="([^"]+)"', normalized_xml)
            xml_tpthumb_match = re.search(r'tpthumburl="([^"]+)"', normalized_xml)

            if not img_md5 and xml_md5_match:
                img_md5 = xml_md5_match.group(1).lower()
            if not img_aeskey and xml_aeskey_match:
                img_aeskey = xml_aeskey_match.group(1)
            if not img_aeskey and xml_tpaeskey_match:
                img_aeskey = xml_tpaeskey_match.group(1)
            if not img_cdn_url:
                img_cdn_url = (
                    (xml_cdnmid_match.group(1) if xml_cdnmid_match else None)
                    or (xml_cdnbig_match.group(1) if xml_cdnbig_match else None)
                    or (xml_tp_match.group(1) if xml_tp_match else None)
                    or (xml_tphd_match.group(1) if xml_tphd_match else None)
                    or (xml_cdnthumb_match.group(1) if xml_cdnthumb_match else None)
                    or (xml_tpthumb_match.group(1) if xml_tpthumb_match else None)
                )

        return img_md5, img_aeskey, img_cdn_url

    def _extract_quote_file_metadata(self, quote: dict | None, quoted_content: str) -> dict:
        """统一提取引用文件的标题、附件下载标识和扩展名。"""
        quote = quote or {}
        quoted_content = quoted_content or ""

        appattach = quote.get("appattach") or {}
        if not isinstance(appattach, dict):
            appattach = {}

        filename = str(
            quote.get("FileName")
            or quote.get("filename")
            or quote.get("Title")
            or quote.get("title")
            or quote.get("Content")
            or ""
        ).strip()
        attach_id = str(
            appattach.get("attachid")
            or quote.get("attachid")
            or quote.get("AttachId")
            or ""
        ).strip()
        file_ext = str(
            appattach.get("fileext")
            or quote.get("fileext")
            or quote.get("FileExt")
            or ""
        ).strip().lstrip(".")
        file_aeskey = str(
            appattach.get("aeskey")
            or quote.get("aeskey")
            or quote.get("AesKey")
            or ""
        ).strip()
        file_url = str(
            appattach.get("cdnattachurl")
            or quote.get("cdnattachurl")
            or quote.get("CdnAttachUrl")
            or ""
        ).strip()
        parsed_md5 = str(quote.get("md5") or quote.get("Md5") or "").strip().lower() or None

        total_len_raw = appattach.get("totallen") or quote.get("totallen") or quote.get("TotalLen") or 0
        try:
            total_len = int(total_len_raw or 0)
        except Exception:
            total_len = 0

        xml_type = 0
        try:
            xml_type = int(quote.get("XmlType") or 0)
        except Exception:
            xml_type = 0

        if quoted_content:
            try:
                import html as _html

                normalized_xml = _html.unescape(quoted_content)
            except Exception:
                normalized_xml = quoted_content

            title_match = re.search(r"<title>([^<]+)</title>", normalized_xml, re.IGNORECASE)
            attach_id_match = re.search(r"<attachid>([^<]+)</attachid>", normalized_xml, re.IGNORECASE)
            totallen_match = re.search(r"<totallen>(\d+)</totallen>", normalized_xml, re.IGNORECASE)
            aeskey_match = re.search(r"<aeskey>([^<]+)</aeskey>", normalized_xml, re.IGNORECASE)
            file_url_match = re.search(r"<cdnattachurl>([^<]+)</cdnattachurl>", normalized_xml, re.IGNORECASE)
            file_ext_match = re.search(r"<fileext>([^<]+)</fileext>", normalized_xml, re.IGNORECASE)
            file_md5_match = re.search(r"<md5>([a-fA-F0-9]{32})</md5>", normalized_xml, re.IGNORECASE)

            if not filename and title_match:
                filename = title_match.group(1).strip()
            if not attach_id and attach_id_match:
                attach_id = attach_id_match.group(1).strip()
            if not total_len and totallen_match:
                try:
                    total_len = int(totallen_match.group(1))
                except Exception:
                    total_len = 0
            if not file_aeskey and aeskey_match:
                file_aeskey = aeskey_match.group(1).strip()
            if not file_url and file_url_match:
                file_url = file_url_match.group(1).strip()
            if not file_ext and file_ext_match:
                file_ext = file_ext_match.group(1).strip().lstrip(".")
            if not parsed_md5 and file_md5_match:
                parsed_md5 = file_md5_match.group(1).lower()

        if filename and file_ext and not filename.lower().endswith(f".{file_ext.lower()}"):
            filename = f"{filename}.{file_ext}"

        is_file_quote = bool(
            xml_type == 6
            or attach_id
            or file_url
            or file_ext
            or total_len > 0
        )

        return {
            "is_file_quote": is_file_quote,
            "filename": filename,
            "attach_id": attach_id,
            "total_len": total_len,
            "file_aeskey": file_aeskey,
            "file_url": file_url,
            "file_ext": file_ext,
            "md5": parsed_md5,
        }

    async def _resolve_quote_image_path(self, quote: dict | None, quoted_content: str) -> tuple[str | None, str | None]:
        """按引用图片元数据在 files 中命中或主动下载落地。"""
        img_md5, img_aeskey, img_cdn_url = self._extract_quote_image_metadata(quote, quoted_content)
        if not any([img_md5, img_aeskey, img_cdn_url]):
            return None, None

        media_path = None
        if os.path.exists(FILES_DIR):
            for filename in os.listdir(FILES_DIR):
                lower_name = filename.lower()
                if img_md5 and img_md5 in lower_name:
                    candidate_path = os.path.join(FILES_DIR, filename)
                    if self._is_valid_image_file(candidate_path):
                        media_path = candidate_path
                        logger.info(f"引用图片：在 FILES_DIR 按 MD5 命中本地文件: {media_path}")
                        break
                    logger.warning(f"引用图片：跳过无效本地图片: {candidate_path}")
                if img_aeskey and img_aeskey.lower() in lower_name:
                    candidate_path = os.path.join(FILES_DIR, filename)
                    if self._is_valid_image_file(candidate_path):
                        media_path = candidate_path
                        logger.info(f"引用图片：在 FILES_DIR 按 AESKey 命中本地文件: {media_path}")
                        break
                    logger.warning(f"引用图片：跳过无效本地图片: {candidate_path}")

        if (
            not media_path
            and img_aeskey
            and img_cdn_url
            and self.bot
        ):
            try:
                logger.info(
                    f"引用图片：本地未命中，尝试下载 (md5={img_md5}, aeskey={img_aeskey}, cdn={str(img_cdn_url)[:30]}...)"
                )
                img_bytes = await self._download_quote_image_bytes(img_aeskey, img_cdn_url)
                if img_bytes:
                    os.makedirs(FILES_DIR, exist_ok=True)
                    ext = self._image_extension_from_bytes(img_bytes) or ".jpg"
                    base_name = img_md5 or (img_aeskey.lower() if img_aeskey else None) or f"img_{int(time.time())}"
                    save_path = os.path.join(FILES_DIR, f"{base_name}{ext}")
                    with open(save_path, "wb") as f:
                        f.write(img_bytes)
                    media_path = save_path
                    logger.success(f"引用图片：下载并落地成功: {media_path} ({len(img_bytes)} bytes)")

                    cache_key = img_md5 or (img_aeskey.lower() if img_aeskey else None)
                    if cache_key:
                        self.file_cache[cache_key] = {
                            "path": media_path,
                            "timestamp": time.time(),
                            "type": "image",
                            "name": os.path.basename(media_path),
                        }
                else:
                    logger.warning(f"引用图片：下载失败或返回非图片内容 (md5={img_md5}, aeskey={img_aeskey})")
            except Exception as e:
                logger.warning(f"引用图片：解析/下载失败: {e}")
                logger.debug(traceback.format_exc())

        return media_path, img_md5

    async def on_enable(self, bot=None):
        self.bot = bot

    async def async_init(self):
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self.connect_ws_loop())
            logger.info("OpenClawBridge WS 连接任务已启动")

    async def on_disable(self):
        self._cancel_task(self._ws_task)
        self._ws_task = None
        await self._cleanup_ws()

    def _cancel_task(self, task):
        if not task:
            return
        try:
            task_loop = task.get_loop()
            current_loop = asyncio.get_running_loop()
            if task_loop is not current_loop and task_loop.is_running():
                task_loop.call_soon_threadsafe(task.cancel)
            else:
                task.cancel()
        except Exception:
            try:
                task.cancel()
            except Exception:
                pass

    def _close_coro_in_owner_loop(self, owner, close_coro_factory):
        """跨事件循环安全关闭 aiohttp 对象（ws/session）。"""
        if not owner:
            return
        try:
            owner_loop = getattr(owner, "_loop", None)
            current_loop = asyncio.get_running_loop()
            if owner_loop and owner_loop is not current_loop and owner_loop.is_running():
                asyncio.run_coroutine_threadsafe(close_coro_factory(), owner_loop)
                return
        except Exception:
            pass
        return close_coro_factory()

    async def _cleanup_ws(self):
        if self._ws_heartbeat_task:
            self._cancel_task(self._ws_heartbeat_task)
            self._ws_heartbeat_task = None
        ws = self._ws
        self._ws = None
        if ws:
            try:
                maybe_coro = self._close_coro_in_owner_loop(ws, ws.close)
                if maybe_coro is not None:
                    await maybe_coro
            except Exception as e:
                logger.warning(f"关闭 OpenClaw WS 连接失败: {e}")

        ws_session = self._ws_session
        self._ws_session = None
        if ws_session:
            try:
                maybe_coro = self._close_coro_in_owner_loop(ws_session, ws_session.close)
                if maybe_coro is not None:
                    await maybe_coro
            except Exception as e:
                logger.warning(f"关闭 OpenClaw WS 会话失败: {e}")

    def _ensure_reply_context_store(self):
        if not hasattr(self, "_reply_contexts") or self._reply_contexts is None:
            self._reply_contexts = {}
        if not hasattr(self, "_reply_context_ttl_seconds") or not self._reply_context_ttl_seconds:
            self._reply_context_ttl_seconds = 1800

    def _new_request_id(self):
        return f"ocb-{int(time.time() * 1000)}-{os.urandom(4).hex()}"

    def _prune_openclaw_request_timings(self):
        if not hasattr(self, "_openclaw_request_timings") or self._openclaw_request_timings is None:
            self._openclaw_request_timings = {}
        now = time.time()
        ttl = float(getattr(self, "_openclaw_request_ttl_seconds", 3600) or 3600)
        expired_request_ids = []
        for request_id, meta in self._openclaw_request_timings.items():
            sent_at = meta.get("sent_at") if isinstance(meta, dict) else None
            if sent_at is None or (now - float(sent_at)) > ttl:
                expired_request_ids.append(request_id)
        for request_id in expired_request_ids:
            self._openclaw_request_timings.pop(request_id, None)

    def _remember_openclaw_request_timing(self, request_id, payload, sent_at=None):
        if not request_id:
            return
        self._prune_openclaw_request_timings()
        payload = payload if isinstance(payload, dict) else {}
        content = payload.get("content", "")
        self._openclaw_request_timings[request_id] = {
            "sent_at": float(sent_at or time.time()),
            "from": payload.get("from"),
            "content_len": len(content) if isinstance(content, str) else 0,
            "has_media": bool(payload.get("media")),
            "callback_count": 0,
        }

    def _log_openclaw_callback_latency(self, payload):
        if not isinstance(payload, dict):
            return
        request_id = payload.get("requestId")
        if not request_id:
            return

        self._prune_openclaw_request_timings()
        meta = self._openclaw_request_timings.get(request_id)
        if not meta:
            return

        now = time.time()
        elapsed = now - float(meta.get("sent_at") or now)
        meta["callback_count"] = int(meta.get("callback_count") or 0) + 1
        meta["last_callback_at"] = now
        level = logger.warning if elapsed >= float(getattr(self, "_openclaw_slow_callback_seconds", 10.0) or 10.0) else logger.info
        level(
            "OpenClaw 回调耗时: "
            f"{elapsed:.2f}s requestId={request_id} callback#{meta['callback_count']} "
            f"from={meta.get('from')} to={payload.get('to')} "
            f"type={payload.get('type', 'text')} content_len={meta.get('content_len')} "
            f"media={meta.get('has_media')}"
        )

    def _store_reply_context(self, request_id, context):
        if not request_id:
            return
        self._ensure_reply_context_store()
        stored_context = dict(context or {})
        stored_context["created_at"] = time.time()
        self._reply_contexts[request_id] = stored_context

    def _prune_reply_contexts(self):
        self._ensure_reply_context_store()
        now = time.time()
        expired_request_ids = []
        for request_id, context in self._reply_contexts.items():
            created_at = context.get("created_at")
            if created_at is None or (now - float(created_at)) > self._reply_context_ttl_seconds:
                expired_request_ids.append(request_id)
        for request_id in expired_request_ids:
            self._reply_contexts.pop(request_id, None)

    def _get_reply_context(self, request_id):
        if not request_id:
            return None
        self._prune_reply_contexts()
        return self._reply_contexts.get(request_id)

    def _normalize_at_wxids(self, raw):
        if not raw:
            return []
        if isinstance(raw, str):
            candidates = [raw]
        elif isinstance(raw, (list, tuple, set)):
            candidates = list(raw)
        else:
            return []

        normalized = []
        seen = set()
        for item in candidates:
            if not isinstance(item, str):
                continue
            wxid = item.strip()
            if not wxid or wxid in seen:
                continue
            seen.add(wxid)
            normalized.append(wxid)
        return normalized

    def _resolve_reply_at_wxids(self, to_wxid, payload):
        if not to_wxid or not str(to_wxid).endswith("@chatroom"):
            return []

        payload = payload if isinstance(payload, dict) else {}
        explicit_at_wxids = self._normalize_at_wxids(payload.get("atWxids") or payload.get("targets"))
        if explicit_at_wxids:
            return explicit_at_wxids

        request_id = payload.get("requestId")
        context = self._get_reply_context(request_id)
        if not context:
            return []
        if not context.get("mention_trigger_user"):
            return []
        return self._normalize_at_wxids(context.get("default_at_wxids"))

    async def _send_text_with_optional_at(self, to_wxid, text, at_wxids=None, payload=None):
        if not self.bot or not text:
            return

        # 提取并删除正文里的隐藏 AT 标记 \x01OCLAW_AT:wxid1,wxid2\x01
        import re as _re
        oclaw_at_wxids = []
        def _extract_oclaw_at(t):
            m = _re.search(r'\x01OCLAW_AT:([^\x01]+)\x01', t)
            if m:
                ids = [x.strip() for x in m.group(1).split(',') if x.strip()]
                clean = _re.sub(r'\x01OCLAW_AT:[^\x01]+\x01', '', t)
                return clean, ids
            return t, []
        text, oclaw_at_wxids = _extract_oclaw_at(text)

        resolved_at_wxids = self._normalize_at_wxids(at_wxids)
        if not resolved_at_wxids:
            resolved_at_wxids = oclaw_at_wxids
        if not resolved_at_wxids:
            resolved_at_wxids = self._resolve_reply_at_wxids(to_wxid, payload)

        logger.info(f"[AT调试] to={to_wxid}, resolved_at_wxids={resolved_at_wxids}, oclaw_at={oclaw_at_wxids}, has_send_at={hasattr(self.bot, 'send_at_message')}")

        if str(to_wxid).endswith("@chatroom") and resolved_at_wxids and hasattr(self.bot, "send_at_message"):
            try:
                logger.info(f"[AT调试] 调用 send_at_message: to={to_wxid}, at={resolved_at_wxids}")
                await self.bot.send_at_message(to_wxid, text, resolved_at_wxids)
                return
            except Exception as e:
                logger.warning(f"send_at_message 失败，降级普通文本: {e}")

        await self.bot.send_text_message(to_wxid, text)

    async def connect_ws_loop(self):
        retry = 1
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=None, connect=self.ws_connect_timeout_seconds)
                self._ws_session = aiohttp.ClientSession(timeout=timeout)
                logger.info(f"OpenClaw WS connecting: {self.ws_url}")
                async with self._ws_session.ws_connect(
                    self.ws_url,
                    heartbeat=None,
                    autoping=False,
                    receive_timeout=None,
                    max_msg_size=100 * 1024 * 1024,  # 100MB, 防止 Base64 媒体超限导致 1009 断连
                ) as ws:
                    self._ws = ws
                    self._ws_last_pong_ts = time.time()
                    retry = 1
                    logger.success(f"OpenClaw WS connected: {self.ws_url}")
                    # 连接后立刻发送 register 事件，向服务端注册 accountId
                    register_id = self.account_id or (self.bot.wxid if self.bot and hasattr(self.bot, 'wxid') else "default")
                    await self.send_ws_message({
                        "direction": "bridge_to_openclaw",
                        "event": "register",
                        "payload": {"accountId": register_id},
                        "ts": int(time.time() * 1000),
                    })
                    logger.info(f"OpenClaw WS registered with accountId: {register_id}")
                    self._ws_heartbeat_task = asyncio.create_task(self.heartbeat_task())
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                frame = json.loads(msg.data)
                            except json.JSONDecodeError:
                                logger.warning("OpenClaw WS received invalid JSON frame")
                                continue
                            await self.handle_ws_message(frame)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                    logger.warning(
                        f"OpenClaw WS stream ended: close_code={getattr(ws, 'close_code', None)} "
                        f"exception={ws.exception() if hasattr(ws, 'exception') else None}"
                    )
            except asyncio.CancelledError:
                logger.info("OpenClaw WS connect loop cancelled.")
                raise
            except Exception as e:
                logger.warning(f"OpenClaw WS disconnected: {e}")
            finally:
                if self._ws_heartbeat_task:
                    self._ws_heartbeat_task.cancel()
                    self._ws_heartbeat_task = None
                self._ws = None
                if self._ws_session:
                    await self._ws_session.close()
                    self._ws_session = None

            if not self.ws_reconnect_enabled:
                logger.warning("OpenClaw WS reconnect is disabled, stop connect loop.")
                return

            wait_seconds = min(retry, 15)
            logger.info(f"OpenClaw WS reconnect in {wait_seconds}s")
            await asyncio.sleep(wait_seconds)
            retry = min(retry * 2, 15)

    async def heartbeat_task(self):
        while self._ws and not self._ws.closed:
            await asyncio.sleep(self.ws_ping_interval_seconds)
            if not self._ws or self._ws.closed:
                return
            if time.time() - self._ws_last_pong_ts > 70:
                logger.warning("OpenClaw WS heartbeat timeout, close socket and reconnect.")
                await self._ws.close()
                return
            await self.send_ws_message({
                "direction": "bridge_to_openclaw",
                "event": "ping",
                "payload": {},
                "ts": int(time.time() * 1000),
            })

    async def send_ws_message(self, frame):
        ws = self._ws
        if not ws or ws.closed:
            return False
        try:
            async with self._ws_send_lock:
                await ws.send_str(json.dumps(frame, ensure_ascii=False))
            return True
        except Exception as e:
            logger.warning(f"OpenClaw WS send failed: {e}")
            return False

    async def handle_ws_message(self, frame):
        event = frame.get("event")
        if event == "pong":
            self._ws_last_pong_ts = time.time()
            return
        if event == "ping":
            self._ws_last_pong_ts = time.time()
            await self.send_ws_message({
                "direction": "bridge_to_openclaw",
                "event": "pong",
                "payload": {},
                "ts": int(time.time() * 1000),
            })
            return

        if event not in {"outbound_text", "outbound_media"}:
            logger.debug(f"OpenClaw WS ignore event: {event}")
            return

        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        await self.handle_callback(_InMemoryRequest(payload))

    async def refresh_contacts_cache(self):
        """从数据库刷新联系人缓存"""
        try:
            logger.info("开始从数据库刷新联系人缓存...")
            new_cache = {}
            
            # xbot-next 环境没有旧版 database 包，默认使用空联系人缓存。
            contacts = get_all_contacts()
            
            for c in contacts:
                wxid = c.get("wxid")
                if not wxid:
                    continue
                
                # 优先使用备注，其次昵称
                nickname = c.get("nickname", "")
                remark = c.get("remark", "")
                name = remark or nickname or wxid
                
                contact_type = c.get("type", "")
                if not contact_type:
                    if wxid.endswith("@chatroom"):
                        contact_type = "group"
                    elif wxid.startswith("gh_"):
                        contact_type = "official"
                    else:
                        contact_type = "friend"

                new_cache[wxid] = {
                    "id": wxid,
                    "name": name,
                    "nickname": nickname,
                    "remark": remark,
                    "alias": c.get("alias", ""),
                    "type": contact_type
                }
            
            self.contacts_cache = new_cache
            self.contacts_cache_time = time.time()
            logger.info(f"联系人缓存刷新完成，共 {len(new_cache)} 个联系人")
        except Exception as e:
            logger.error(f"刷新联系人缓存失败: {e}")
    
    async def get_contacts_cache(self):
        """获取联系人缓存，过期则刷新"""
        if time.time() - self.contacts_cache_time > self.contacts_cache_ttl:
            await self.refresh_contacts_cache()
        return self.contacts_cache

    def _extract_text_value(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value).strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                extracted = self._extract_text_value(item)
                if extracted:
                    return extracted
        if isinstance(value, dict):
            for key in ("string", "String", "str", "Str", "text", "Text", "value", "Value"):
                inner = value.get(key)
                extracted = self._extract_text_value(inner)
                if extracted:
                    return extracted
        return ""

    def _normalize_display_name(self, value, *invalid_values):
        name = self._extract_text_value(value)
        if not name:
            return ""
        invalid = {str(item or "").strip() for item in invalid_values if str(item or "").strip()}
        if name in invalid:
            return ""
        if name.lower() in {"user", "unknown", "none", "null"}:
            return ""
        return name

    def _extract_person_display_name(self, payload, *invalid_values):
        if not isinstance(payload, dict):
            return ""
        for key in (
            "remark",
            "Remark",
            "display_name",
            "DisplayName",
            "ChatRoomNickName",
            "chat_room_nick_name",
            "nickname",
            "NickName",
            "Nickname",
            "nickName",
            "nick_name",
            "MemberName",
            "memberName",
            "member_name",
            "SenderNickname",
            "SenderNickName",
            "senderName",
            "SenderName",
            "name",
        ):
            name = self._normalize_display_name(payload.get(key), *invalid_values)
            if name:
                return name
        return ""

    def _extract_member_wxid(self, member):
        if not isinstance(member, dict):
            return ""
        return self._extract_text_value(
            member.get("UserName")
            or member.get("Username")
            or member.get("userName")
            or member.get("user_name")
            or member.get("wxid")
            or member.get("Wxid")
            or member.get("WxId")
            or member.get("member_wxid")
            or member.get("MemberId")
            or member.get("MemberID")
            or member.get("memberId")
            or member.get("member_id")
            or member.get("UserId")
            or member.get("UserID")
            or member.get("userId")
            or member.get("user_id")
            or member.get("FromUserName")
        )

    def _extract_members_from_payload(self, payload):
        if not isinstance(payload, dict):
            return []
        direct_candidates = [
            payload.get("ChatRoomMember"),
            payload.get("MemberList"),
            payload.get("chatroom_member_list"),
            payload.get("ChatRoomMemberList"),
        ]
        for candidate in direct_candidates:
            if isinstance(candidate, list) and candidate:
                return [item for item in candidate if isinstance(item, dict)]
        for nested_key in ("NewChatroomData", "newChatroomData", "member_data"):
            members = self._extract_members_from_payload(payload.get(nested_key))
            if members:
                return members
        for list_key in ("ChatRoomInfo", "chatroomInfo", "ContactList", "contactList"):
            container = payload.get(list_key)
            if isinstance(container, list):
                for item in container:
                    members = self._extract_members_from_payload(item)
                    if members:
                        return members
        return []

    def _build_group_member_name_map(self, members):
        name_map = {}
        for item in members or []:
            wxid = self._extract_member_wxid(item)
            if not wxid:
                continue
            name = self._extract_person_display_name(item, wxid)
            if name:
                name_map[wxid] = name
        return name_map

    def _find_cached_contact(self, identifier):
        identifier = str(identifier or "").strip()
        if not identifier:
            return None
        direct = self.contacts_cache.get(identifier)
        if direct:
            return direct
        lowered = identifier.lower()
        for contact in self.contacts_cache.values():
            if not isinstance(contact, dict):
                continue
            for key in ("id", "wxid", "alias"):
                if str(contact.get(key) or "").strip().lower() == lowered:
                    return contact
        return None

    def _get_group_member_cache_state(self, group_wxid):
        group_member_cache = getattr(self, "_group_member_name_cache", {})
        if not hasattr(self, "_group_member_name_cache"):
            self._group_member_name_cache = group_member_cache
        group_member_cache_ttl = getattr(self, "_group_member_name_cache_ttl", 21600)
        cached = group_member_cache.get(group_wxid)
        if not cached:
            return False, {}
        cache_ttl = group_member_cache_ttl if cached.get("has_members") else getattr(self, "_group_member_empty_cache_ttl", 120)
        is_fresh = time.time() - cached.get("time", 0) <= cache_ttl
        return is_fresh, cached.get("names", {}) or {}

    async def _fetch_group_members_snapshot(self, group_wxid):
        if not self.bot or not group_wxid:
            return []

        members = []
        try:
            if hasattr(self.bot, "get_chatroom_member_list"):
                result = await self.bot.get_chatroom_member_list(group_wxid)
                if isinstance(result, list):
                    members = [item for item in result if isinstance(item, dict)]
            elif hasattr(self.bot, "get_chatroom_members"):
                result = await self.bot.get_chatroom_members(group_wxid)
                if isinstance(result, list):
                    members = [item for item in result if isinstance(item, dict)]
        except Exception as e:
            logger.debug(f"获取实时群成员列表失败: group={group_wxid}, error={e}")

        if not members and hasattr(self.bot, "call_path"):
            for path, body in (
                ("/group/GetChatroomMemberDetail", {"ChatRoomName": group_wxid}),
                ("/group/GetChatRoomInfo", {"ChatRoomWxIdList": [group_wxid]}),
            ):
                try:
                    data = await self.bot.call_path(path, body=body)
                    members = self._extract_members_from_payload(data)
                    if members:
                        break
                except Exception as e:
                    logger.debug(f"获取群成员列表兜底接口失败: path={path}, group={group_wxid}, error={e}")
        return members

    async def _persist_group_members_snapshot(self, group_wxid, members):
        async with self._group_member_persist_lock:
            member_name_map = self._build_group_member_name_map(members)
            self._group_member_name_cache[group_wxid] = {
                "time": time.time(),
                "names": member_name_map,
                "has_members": bool(members),
            }
            if not members:
                return member_name_map
            try:
                
                saved = await asyncio.to_thread(group_members_db_module.save_group_members_to_db, group_wxid, members)
                if saved:
                    logger.info(
                        f"群成员快照已落库: group={group_wxid}, members={len(members)}, "
                        f"names={len(member_name_map)}, db={GROUP_MEMBERS_DB_PATH}"
                    )
                else:
                    logger.warning(f"群成员快照落库返回失败: group={group_wxid}, members={len(members)}")
            except Exception as e:
                logger.debug(f"群成员快照落库异常: group={group_wxid}, error={e}")
            return member_name_map

    async def _refresh_group_members_snapshot(self, group_wxid):
        fresh, _ = self._get_group_member_cache_state(group_wxid)
        if fresh:
            return
        try:
            members = await self._fetch_group_members_snapshot(group_wxid)
            await self._persist_group_members_snapshot(group_wxid, members)
            if not members:
                logger.debug(f"群成员快照为空，已按 TTL 记录本次尝试: group={group_wxid}")
        finally:
            tasks = getattr(self, "_group_member_sync_tasks", {})
            if tasks.get(group_wxid) is asyncio.current_task():
                tasks.pop(group_wxid, None)

    def _schedule_group_members_snapshot(self, group_wxid):
        if not group_wxid or not str(group_wxid).endswith("@chatroom"):
            return
        fresh, _ = self._get_group_member_cache_state(group_wxid)
        if fresh:
            return
        tasks = getattr(self, "_group_member_sync_tasks", {})
        if not hasattr(self, "_group_member_sync_tasks"):
            self._group_member_sync_tasks = tasks
        task = tasks.get(group_wxid)
        if task and not task.done():
            return
        tasks[group_wxid] = asyncio.create_task(self._refresh_group_members_snapshot(group_wxid))

    async def _get_live_group_member_name(self, group_wxid, sender_wxid):
        if not self.bot or not group_wxid or not sender_wxid:
            return ""

        fresh, cached_names = self._get_group_member_cache_state(group_wxid)
        if fresh:
            name = cached_names.get(sender_wxid, "")
            if name:
                return self._normalize_display_name(name, sender_wxid)

        try:
            if hasattr(self.bot, "get_local_nickname"):
                name = self.bot.get_local_nickname(sender_wxid, group_wxid)
                name = self._normalize_display_name(name, sender_wxid)
                if name:
                    return name
        except Exception:
            pass

        task = getattr(self, "_group_member_sync_tasks", {}).get(group_wxid)
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=3)
                fresh, cached_names = self._get_group_member_cache_state(group_wxid)
                if fresh:
                    name = cached_names.get(sender_wxid, "")
                    if name:
                        return self._normalize_display_name(name, sender_wxid)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

        members = await self._fetch_group_members_snapshot(group_wxid)
        member_name_map = await self._persist_group_members_snapshot(group_wxid, members)

        name = member_name_map.get(sender_wxid, "")
        return self._normalize_display_name(name, sender_wxid)

    async def _resolve_sender_display_name(self, message, from_wxid, sender_wxid, is_group):
        invalid_values = (sender_wxid, from_wxid, self.account_id)

        # 先吃消息体里随消息带来的实时昵称字段。
        for key in (
            "SenderNickname",
            "SenderNickName",
            "SenderName",
            "senderName",
            "ChatRoomNickName",
            "chat_room_nick_name",
            "DisplayName",
            "display_name",
            "Nickname",
            "NickName",
            "nickname",
            "Remark",
            "remark",
        ):
            name = self._normalize_display_name(message.get(key), *invalid_values)
            if name:
                return name

        await self.get_contacts_cache()

        if is_group:
            live_name = await self._get_live_group_member_name(from_wxid, sender_wxid)
            if live_name:
                return live_name

            try:
                member_info = get_group_member_from_db(from_wxid, sender_wxid)
                name = self._extract_person_display_name(member_info, *invalid_values)
                if name:
                    return name
            except Exception as e:
                logger.debug(f"从群成员数据库解析 sender 昵称失败: group={from_wxid}, sender={sender_wxid}, error={e}")

        cached_contact = self._find_cached_contact(sender_wxid)
        name = self._extract_person_display_name(cached_contact, *invalid_values)
        if name:
            return name

        try:
            contact_info = get_contact_from_db(sender_wxid)
            name = self._extract_person_display_name(contact_info, *invalid_values)
            if name:
                return name
        except Exception as e:
            logger.debug(f"从联系人数据库解析 sender 昵称失败: sender={sender_wxid}, error={e}")

        if self.bot and hasattr(self.bot, "get_contract_detail"):
            try:
                details = await self.bot.get_contract_detail(
                    [sender_wxid],
                    chatroom=(from_wxid if is_group else ""),
                )
                if isinstance(details, dict):
                    details = [details]
                if isinstance(details, list):
                    for item in details:
                        wxid = self._extract_member_wxid(item) or sender_wxid
                        if wxid and wxid != sender_wxid:
                            continue
                        name = self._extract_person_display_name(item, *invalid_values)
                        if name:
                            return name
            except TypeError:
                try:
                    details = await self.bot.get_contract_detail(sender_wxid)
                    if isinstance(details, dict):
                        details = [details]
                    if isinstance(details, list):
                        for item in details:
                            name = self._extract_person_display_name(item, *invalid_values)
                            if name:
                                return name
                except Exception as e:
                    logger.debug(f"get_contract_detail(sender) 解析昵称失败: sender={sender_wxid}, error={e}")
            except Exception as e:
                logger.debug(f"get_contract_detail 解析昵称失败: sender={sender_wxid}, error={e}")

        if self.bot and hasattr(self.bot, "get_nickname"):
            try:
                nickname = await self.bot.get_nickname([sender_wxid])
                if isinstance(nickname, list):
                    nickname = nickname[0] if nickname else ""
                name = self._normalize_display_name(nickname, *invalid_values)
                if name:
                    return name
            except TypeError:
                try:
                    nickname = await self.bot.get_nickname(sender_wxid)
                    name = self._normalize_display_name(nickname, *invalid_values)
                    if name:
                        return name
                except Exception as e:
                    logger.debug(f"get_nickname(sender) 解析昵称失败: sender={sender_wxid}, error={e}")
            except Exception as e:
                logger.debug(f"get_nickname 解析昵称失败: sender={sender_wxid}, error={e}")

        logger.debug(f"未解析到 sender 昵称，回退 User: sender={sender_wxid}, from={from_wxid}, is_group={is_group}")
        return "User"
    
    async def handle_contacts_search(self, request):
        """搜索联系人 API"""
        try:
            query = request.query.get("q", "").strip()
            contact_type = request.query.get("type", "")  # user, group, 或空(全部)
            
            if not query:
                return web.json_response({"error": "缺少搜索关键字 q"}, status=400)
            
            # 检查是否匹配主人别名
            query_lower = query.lower().strip()
            if self.owner_wxid and query_lower in self.owner_aliases:
                owner_contact = {
                    "id": self.owner_wxid,
                    "name": "主人",
                    "nickname": "主人",
                    "remark": "",
                    "type": "user"
                }
                logger.info(f"搜索匹配主人别名 '{query}' -> {self.owner_wxid}")
                return web.json_response({"contacts": [owner_contact], "count": 1})
            
            cache = await self.get_contacts_cache()
            results = []
            
            for contact_id, contact in cache.items():
                # 过滤类型
                if contact_type and contact.get("type") != contact_type:
                    continue
                
                # 匹配名称、昵称、备注、ID
                name = (contact.get("name") or "").lower()
                nickname = (contact.get("nickname") or "").lower()
                remark = (contact.get("remark") or "").lower()
                cid = contact_id.lower()
                
                if query_lower in name or query_lower in nickname or query_lower in remark or query_lower in cid:
                    results.append(contact)
            
            return web.json_response({"contacts": results, "count": len(results)})
        except Exception as e:
            logger.error(f"搜索联系人失败: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def handle_contacts_refresh(self, request):
        """强制刷新联系人缓存 API"""
        try:
            await self.refresh_contacts_cache()
            return web.json_response({"success": True, "count": len(self.contacts_cache)})
        except Exception as e:
            logger.error(f"刷新联系人缓存失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

    def clean_markdown(self, text):
        if not text:
            return text
        
        # 过滤 NO_REPLY 标记，但不吞掉有用的正文
        if "NO_REPLY" in text.upper():
            text = re.sub(r'(?i)\s*NO_REPLY\s*', '', text)
            if not text.strip():
                return ""

        # Remove code blocks ```
        text = re.sub(r'```[\w]*', '', text)
        # Remove markdown images ![alt](url) - handle this BEFORE regular links
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        # Remove bold **
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        # Remove markdown links [text](url) -> text
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        # Remove system tags like [[reply_to_current]]
        text = re.sub(r'\[\[.*?\]\]', '', text)
        # Remove headers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        return text.strip()

    def _is_nonempty_send_result(self, result) -> bool:
        """判断 WechatAPI 发送接口返回是否代表成功。

        说明：部分协议会返回 Code=200 但 Data 为空；这里以“非空结果”为最低标准。
        """
        if result is None:
            return False
        if result is False:
            return False
        if isinstance(result, dict):
            return len(result) > 0
        if isinstance(result, (list, tuple, set)):
            return len(result) > 0
        if isinstance(result, str):
            return bool(result.strip())
        return True

    def _is_successful_voice_send_result(self, result) -> bool:
        """判断 send_voice_message 的返回结果是否可视为发送成功。"""
        if result is None or result is False:
            return False
        if isinstance(result, (list, tuple)):
            if len(result) >= 3:
                return bool(result[0]) or bool(result[2])
            return any(result)
        return self._is_nonempty_send_result(result)

    async def _send_long_audio_as_voice_chunks(
        self,
        to_wxid: str,
        audio_data,
        source_label: str = "",
        assume_sent_on_no_exception: bool = False,
    ) -> bool:
        """将长音频切成 <=59s 的 wav 片段，逐段以语音消息发送。"""
        if not self.bot or not hasattr(self.bot, "send_voice_message"):
            return False

        try:
            from io import BytesIO

            max_chunk_ms = 59000
            total_duration_ms = len(audio_data)
            if total_duration_ms <= 0:
                return False

            sent_chunks = 0
            chunk_index = 0
            for start_ms in range(0, total_duration_ms, max_chunk_ms):
                chunk_index += 1
                end_ms = min(start_ms + max_chunk_ms, total_duration_ms)
                chunk = audio_data[start_ms:end_ms]
                if len(chunk) <= 0:
                    continue

                with BytesIO() as buffer:
                    chunk.export(buffer, format="wav")
                    voice_bytes = buffer.getvalue()

                if not voice_bytes:
                    logger.warning(
                        f"长音频分片导出为空，跳过片段 {chunk_index}: {source_label or to_wxid}"
                    )
                    continue

                try:
                    result = await self.bot.send_voice_message(to_wxid, voice_bytes, format="wav")
                    if assume_sent_on_no_exception or self._is_successful_voice_send_result(result):
                        sent_chunks += 1
                        logger.success(
                            f"长音频片段发送成功 ({chunk_index}): {source_label or to_wxid} [{start_ms}-{end_ms}ms]"
                        )
                    else:
                        logger.warning(
                            f"长音频片段发送返回失败状态 ({chunk_index}): {source_label or to_wxid}, result={result}"
                        )
                except Exception as send_err:
                    logger.warning(
                        f"长音频片段发送失败 ({chunk_index}): {source_label or to_wxid}, error={send_err}"
                    )

            return sent_chunks > 0
        except Exception as e:
            logger.warning(f"长音频切片发送失败: {source_label or to_wxid}, error={e}")
            return False

    def _probe_video_duration_seconds(self, video_path: str) -> int:
        """用 ffprobe 获取视频时长（秒）；失败返回 0。"""
        try:
            import shutil
            import subprocess

            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                return 0
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if p.returncode != 0:
                return 0
            raw = (p.stdout or "").strip()
            if not raw:
                return 0
            val = float(raw)
            if val <= 0:
                return 0
            # 取整（秒）
            return int(round(val))
        except Exception:
            return 0

    def _extract_video_thumbnail(self, video_path: str) -> str | None:
        """用 ffmpeg 抽取视频缩略图；失败返回 None。"""
        try:
            import shutil
            import subprocess
            import tempfile

            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return None
            thumb_path = os.path.join(
                tempfile.gettempdir(),
                f"openclawbridge_thumb_{int(time.time())}_{os.getpid()}.jpg",
            )
            cmd = [ffmpeg, "-y", "-i", video_path, "-ss", "00:00:01", "-frames:v", "1", thumb_path]
            subprocess.run(cmd, capture_output=True, timeout=30, check=False)
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                return thumb_path
            return None
        except Exception:
            return None

    async def _send_video_path(self, to_wxid: str, video_path: str) -> bool:
        """发送视频：优先 video 接口（带缩略图/时长），失败回退为文件/链接。"""
        try:
            thumb_path = self._extract_video_thumbnail(video_path)
            duration = self._probe_video_duration_seconds(video_path)

            if hasattr(self.bot, "send_video_message"):
                try:
                    result = await self.bot.send_video_message(
                        to_wxid,
                        video_path,
                        image=thumb_path,
                        video_duration=duration,
                    )
                    if self._is_nonempty_send_result(result):
                        return True
                    logger.warning(
                        f"send_video_message 返回空结果，可能发送失败: {result}"
                    )
                except Exception as e:
                    logger.warning(f"send_video_message 发送异常: {e}")

            if hasattr(self.bot, "send_file_message"):
                try:
                    success = await self.bot.send_file_message(to_wxid, video_path)
                    if success:
                        return True
                except Exception as e:
                    logger.warning(f"send_file_message 发送异常: {e}")

            await self._send_file_as_link(to_wxid, video_path)
            return False
        except Exception as e:
            logger.error(f"_send_video_path 失败: {e}")
            try:
                await self._send_file_as_link(to_wxid, video_path)
            except Exception:
                pass
            return False

    async def _send_file_as_link(self, to_wxid: str, file_path: str, reply_payload=None):
        """回退方案：复制文件到静态目录并发送下载链接"""
        import shutil
        try:
            static_dir = os.path.join(os.getcwd(), "files")
            os.makedirs(static_dir, exist_ok=True)
            
            filename = os.path.basename(file_path)
            target_path = os.path.join(static_dir, filename)
            
            if os.path.abspath(file_path) != os.path.abspath(target_path):
                shutil.copy2(file_path, target_path)
            
            base_url = self.config.get("openclaw", {}).get("download_base_url", "https://wechat.aitell.vip")
            base_url = base_url.rstrip("/")
            file_url = f"{base_url}/files/{filename}"
            
            msg_content = f"📂 收到文件: {filename}\n🔗 下载链接: {file_url}\n"
            await self._send_text_with_optional_at(to_wxid, msg_content, payload=reply_payload)
            logger.success(f"文件链接发送成功: {file_url}")
        except Exception as e:
            logger.error(f"发送文件链接失败: {e}")
            await self._send_text_with_optional_at(to_wxid, f"[文件处理失败: {os.path.basename(file_path)}]", payload=reply_payload)


    async def _download_and_send_media(self, to_wxid, url, alt_text=""):
        """使用 curl_requests 下载媒体并自动识别格式发送给微信"""
        try:
            logger.info(f"开始使用 curl_requests 下载媒体: {url}")
            # 使用 impersonate='chrome' 来避开反爬
            response = curl_requests.get(url, impersonate="chrome", timeout=30)
            if response.status_code != 200:
                logger.error(f"媒体下载失败 (status={response.status_code}): {url}")
                return False
            
            content = response.content
            if not content:
                logger.error(f"媒体内容为空: {url}")
                return False

            # --- 自动识别格式 (特征码嗅探) ---
            import tempfile
            ext = ".bin"
            
            # 1. 优先通过文件头嗅探真实格式
            if content.startswith(b'\xff\xd8\xff'): ext = ".jpg"
            elif content.startswith(b'\x89PNG\r\n\x1a\n'): ext = ".png"
            elif content.startswith(b'GIF87a') or content.startswith(b'GIF89a'): ext = ".gif"
            elif b'ftyp' in content[:32]: ext = ".mp4"
            elif content.startswith(b'%PDF'): ext = ".pdf"
            elif content.startswith(b'ID3') or content.startswith(b'\xff\xfb'): ext = ".mp3"
            elif content.startswith(b'RIFF') and content[8:12] == b'WAVE': ext = ".wav"
            elif content.startswith(b'OggS'): ext = ".ogg"
            elif content.startswith(b'fLaC'): ext = ".flac"
            
            # 2. 如果嗅探失败，退而求其次使用 Content-Type
            if ext == ".bin":
                content_type = response.headers.get("Content-Type", "").lower()
                if "image/jpeg" in content_type: ext = ".jpg"
                elif "image/png" in content_type: ext = ".png"
                elif "image/gif" in content_type: ext = ".gif"
                elif "video/mp4" in content_type: ext = ".mp4"
                elif "application/pdf" in content_type: ext = ".pdf"
                elif "audio/mpeg" in content_type: ext = ".mp3"
                
            # 3. 最后才看 URL 后缀
            if ext == ".bin":
                path_part = url.split("?")[0]
                url_ext = os.path.splitext(path_part)[1].lower()
                if url_ext: ext = url_ext

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            logger.info(f"媒体识别完成: 格式={ext}, 大小={len(content)} bytes")
            
            # 根据识别出的后缀或类型发送
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
                await self.bot.send_image_message(to_wxid, tmp_path)
                logger.success(f"Markdown 图片识别并发送成功: {url}")
            elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.flv']:
                await self._send_video_path(to_wxid, tmp_path)
                logger.success(f"Markdown 视频识别并发送成功: {url}")
            else:
                # 其他文件 (音频或文档)
                if hasattr(self.bot, "send_file_message"):
                    await self.bot.send_file_message(to_wxid, tmp_path)
                else:
                    await self._send_file_as_link(to_wxid, tmp_path)
                logger.success(f"Markdown 媒体已按文件模式发送: {url}")
            
            # 发送完删除临时文件
            try:
                os.remove(tmp_path)
            except:
                pass
            return True
        except Exception as e:
            logger.error(f"下载并解析媒体失败 ({url}): {e}")
            return False

    async def _send_text_or_appmsg(self, to_wxid, content, reply_payload=None):
        """发送消息，支持文本与 Markdown 图片按原始顺序混排发送。"""
        if not content or not self.bot:
            return

        # 提取 XML 卡片内容 (支持 WXAPPMSG: 和 //n<appmsg 两种标记)
        xml_parts = []
        
        # 1. 优先提取 //n<appmsg 标记的所有卡片
        if "//n<appmsg" in content:
            parts = content.split("//n<appmsg")
            content = parts[0].strip()  # 取第一部分作为正文文本
            for part in parts[1:]:
                xml = ("<appmsg" + part).strip()
                xml_parts.append(xml)

        # 2. 如果没有 //n，尝试传统的 WXAPPMSG: 标记 (只支持一个)
        elif "WXAPPMSG:" in content:
            parts = content.split("WXAPPMSG:", 1)
            content = parts[0].strip()
            if len(parts) > 1 and parts[1].strip():
                xml_candidate = parts[1].strip()
                # 尝试分离正常文本 (防止 AI 在 XML 后继续说废话导致 XML 解析崩溃)
                if "</appmsg>" in xml_candidate:
                    sub_parts = xml_candidate.split("</appmsg>", 1)
                    xml_parts.append(sub_parts[0] + "</appmsg>")
                    if len(sub_parts) > 1 and sub_parts[1].strip():
                        content += "\n\n" + sub_parts[1].strip()
                else:
                    xml_parts.append(xml_candidate)

        # 情况 1: 如果整个内容(或剥离后的)就是纯 <appmsg XML (无文字)
        stripped = content.strip()
        if stripped.startswith("<appmsg") or (stripped.startswith("<?xml") and "<appmsg" in stripped):
            if stripped not in xml_parts:
                xml_parts.append(stripped)
            content = ""  # 清空纯文本部分

        # 情况 2: 执行图文混排顺序发送
        # 使用正则切分：捕获组会保留分隔符本身以便识别
        # 匹配 ![alt](url)
        fragments = re.split(r'(!\[.*?\]\(https?://.*?\))', content)
        
        for fragment in fragments:
            if not fragment:
                continue
            
            # 检查是否是图片标签
            img_match = re.match(r'!\[(.*?)\]\((https?://.*?)\)', fragment)
            if img_match:
                # 这是一个图片
                alt_text = img_match.group(1)
                url = img_match.group(2)
                await self._download_and_send_media(to_wxid, url, alt_text)
            else:
                # 这是一个文本段
                cleaned_text = self.clean_markdown(fragment)
                if cleaned_text:
                    logger.info(f"发送文本片段给 {to_wxid}: {cleaned_text[:30]}...")
                    await self._send_text_with_optional_at(to_wxid, cleaned_text, payload=reply_payload)
                else:
                    continue # 如果是空行之类的就不等 1.5s 了
            
            # 每发一段，等待一下让微信喘气，并保持顺序
            await asyncio.sleep(1.5)

        # 最后补发 XML 卡片 (如果有)
        for xml_part in xml_parts:
            await self._send_appmsg_xml(to_wxid, xml_part, reply_payload=reply_payload)
            await asyncio.sleep(1.5)

    async def _send_appmsg_xml(self, to_wxid, xml_content, reply_payload=None):
        """解析并发送 appmsg XML 卡片消息"""
        try:
            # 兼容微信要求，移除所有换行排版
            xml_content = xml_content.replace('\n', '').replace('\r', '').strip()

            # 清理 XML 声明和外层 <msg> 标签
            if xml_content.startswith("<?xml"):
                xml_content = re.sub(r'<\?xml[^?]*\?>', '', xml_content).strip()
            if xml_content.startswith("<msg>"):
                xml_content = xml_content.replace("<msg>", "", 1).strip()
                if xml_content.endswith("</msg>"):
                    xml_content = xml_content[:-6].strip()

            if not xml_content.startswith("<appmsg"):
                logger.warning(f"内容不是有效的 appmsg XML: {xml_content[:80]}...")
                await self._send_text_with_optional_at(to_wxid, xml_content, payload=reply_payload)
                return

            # 解析 XML 获取消息类型
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_content)
            type_element = root.find(".//type")
            msg_type_int = 49  # 默认卡片类型
            if type_element is not None and type_element.text:
                try:
                    msg_type_int = int(type_element.text)
                except ValueError:
                    pass

            logger.info(f"发送卡片消息给 {to_wxid}，类型: {msg_type_int}")
            await self.bot.send_app_message(to_wxid, xml_content, msg_type_int)
            logger.success(f"卡片消息发送成功 (type={msg_type_int})")

        except ET.ParseError as e:
            logger.error(f"解析卡片 XML 失败: {e}")
            # 智能降级：即使 AI 把 XML 写坏了（比如少写了结尾标签），也尽量把它说的正文剥离出来发给用户
            fallback_text = re.sub(r'<[^>]+>', '', xml_content).strip()
            if fallback_text and len(fallback_text) > 800:
                fallback_text = fallback_text[:800] + "..."
            if fallback_text:
                await self._send_text_with_optional_at(to_wxid, f"[🎶 卡片显示异常，降级为文字]:\n{fallback_text}", payload=reply_payload)
            else:
                await self._send_text_with_optional_at(to_wxid, "[卡片消息格式错误]", payload=reply_payload)
        except Exception as e:
            logger.error(f"发送卡片消息失败: {e}")
            await self._send_text_with_optional_at(to_wxid, f"[卡片发送失败: {str(e)[:50]}]", payload=reply_payload)

    async def handle_callback(self, request):
        try:
            data = await request.json()
            logger.info(f"OpenClaw 回调原始内容: {data}")
            self._log_openclaw_callback_latency(data)
            
            to_wxid = data.get("to")
            content = data.get("text")
            msg_type = data.get("type", "text")

            if not to_wxid:
                 return web.Response(status=400, text="缺少 to 参数")
            
            if to_wxid.startswith("wechat:"):
                to_wxid = to_wxid.replace("wechat:", "")

            # 尝试解析 Alias (微信号) -> WXID
            # 如果 to_wxid 看起来不像 wxid (不以 wxid_ 开头，且不含 @)，则可能是微信号
            # 但要注意群 ID 也是数字@chatroom
            real_wxid = to_wxid
            if not to_wxid.startswith("wxid_") and not to_wxid.endswith("@chatroom") and not to_wxid.startswith("gh_"):
                 # 可能是微信号，查库反解
                 logger.debug(f"尝试解析微信号: {to_wxid}")
                 # 先查内存缓存
                 found = False
                 for wxid, info in self.contacts_cache.items():
                     if info.get("alias") == to_wxid:
                         real_wxid = wxid
                         found = True
                         logger.debug(f"缓存命中: {to_wxid} -> {real_wxid}")
                         break
                 
                 if not found:
                     # 查库；只使用公开的 contacts_db 接口，避免依赖框架内部私有对象。
                     try:
                         for contact in get_contacts_from_db():
                             if contact.get("alias") == to_wxid:
                                 real_wxid = contact.get("wxid") or real_wxid
                                 logger.debug(f"数据库命中: {to_wxid} -> {real_wxid}")
                                 break
                     except Exception as e:
                         logger.error(f"反查微信号失败: {e}")

            if self.bot:
                if msg_type == "text" and content:
                    # 注意：这里不能先调用 clean_markdown，否则图片链接会被洗掉
                    # 解析和清洗逻辑都搬到了 _send_text_or_appmsg 内部
                    logger.info(f"OpenClaw 收到回复任务给 {real_wxid}: {content[:50]}...")
                    await self._send_text_or_appmsg(real_wxid, content, reply_payload=data)
                elif msg_type == "media":
                    media_urls = []
                    distinct_urls = set()

                    main_url = data.get("mediaUrl", "")
                    if main_url and ("<appmsg" in main_url or "<type>" in main_url or "<title>" in main_url):
                        logger.info("检测到 media 回调中的 mediaUrl 包含 XML 内容，跳过文件下载")
                        if "<appmsg" in main_url:
                            await self._send_appmsg_xml(real_wxid, main_url[main_url.index("<appmsg"):], reply_payload=data)
                        return web.Response(text="OK")

                    if main_url:
                        media_urls.append(main_url)
                        distinct_urls.add(main_url)

                    text_content = data.get("text", "")
                    if text_content:
                        media_matches = re.findall(r"MEDIA:(.+?)(?:\s|$)", text_content)
                        for match in media_matches:
                            path = match.strip()
                            if path and path not in distinct_urls:
                                media_urls.append(path)
                                distinct_urls.add(path)

                        text_content = re.sub(r"MEDIA:.+?(?:\s|$)", "", text_content, flags=re.MULTILINE).strip()
                        if text_content:
                            text_content = self.clean_markdown(text_content)
                            if text_content:
                                await self._send_text_with_optional_at(real_wxid, text_content, payload=data)

                    for media_url in media_urls:
                        is_remote = media_url.strip().lower().startswith("http://") or media_url.strip().lower().startswith("https://")

                        if not is_remote:
                            expanded_path = os.path.abspath(os.path.expanduser(media_url))

                            if not os.path.exists(expanded_path) and self.workspace_path:
                                workspace_file_path = os.path.join(self.workspace_path, media_url)
                                workspace_file_path = os.path.abspath(os.path.expanduser(workspace_file_path))
                                if os.path.exists(workspace_file_path):
                                    logger.info(f"在 OpenClaw Workspace 中找到文件: {workspace_file_path}")
                                    expanded_path = workspace_file_path

                            if not os.path.exists(expanded_path):
                                potential_paths = []
                                if self.workspace_path:
                                    potential_paths.append(self.workspace_path)
                                potential_paths.append("/root/.openclaw/workspace")
                                potential_paths.append(os.path.expanduser("~/.openclaw/workspace"))

                                for base_path in potential_paths:
                                    if not base_path:
                                        continue
                                    candidate_path = os.path.abspath(os.path.join(base_path, media_url))
                                    if os.path.exists(candidate_path):
                                        expanded_path = candidate_path
                                        logger.info(f"在 Workspace 推断路径找到文件: {candidate_path}")
                                        break

                            if os.path.exists(expanded_path):
                                guessed_mime, _ = mimetypes.guess_type(expanded_path)
                                ext = os.path.splitext(expanded_path)[1].lower()

                                image_exts = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"]
                                image_mimes = ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp", "image/heic", "image/heif"]
                                video_exts = [".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".webm", ".m4v"]
                                video_mimes = ["video/mp4", "video/avi", "video/quicktime", "video/x-msvideo", "video/x-flv", "video/x-matroska", "video/webm"]
                                audio_exts = [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".amr"]
                                audio_mimes = ["audio/mpeg", "audio/wav", "audio/flac", "audio/aac", "audio/ogg", "audio/mp4", "audio/x-ms-wma", "audio/amr"]

                                is_image = ext in image_exts or (guessed_mime and guessed_mime in image_mimes)
                                is_video = ext in video_exts or (guessed_mime and guessed_mime in video_mimes)
                                is_audio = ext in audio_exts or (guessed_mime and guessed_mime in audio_mimes)

                                media_type = "图片" if is_image else ("视频" if is_video else ("音频" if is_audio else "文件"))
                                logger.info(f"OpenClaw 发送{media_type}给 {real_wxid}: {expanded_path} (MIME: {guessed_mime or 'unknown'})")

                                try:
                                    if is_image:
                                        await self.bot.send_image_message(real_wxid, expanded_path)
                                        logger.success(f"图片发送成功: {expanded_path}")
                                        self._cache_outbound_media(expanded_path, "image", real_wxid)
                                    elif is_video:
                                        sent = await self._send_video_path(real_wxid, expanded_path)
                                        if sent:
                                            logger.success(f"视频发送成功: {expanded_path}")
                                            self._cache_outbound_media(expanded_path, "video", real_wxid)
                                        else:
                                            logger.warning(f"视频发送失败，已回退处理: {expanded_path}")
                                    elif is_audio:
                                        sent_as_voice = False
                                        if ext in [".mp3", ".wav", ".amr"] and hasattr(self.bot, "send_voice_message"):
                                            try:
                                                from pydub import AudioSegment

                                                audio_data = AudioSegment.from_file(expanded_path)
                                                duration_ms = len(audio_data)
                                                if duration_ms < 60000:
                                                    logger.info(f"音频时长 {duration_ms/1000:.2f}s < 60s，尝试使用语音消息发送")
                                                    voice_format = ext[1:] if ext[1:] in ["amr", "wav", "mp3"] else "mp3"
                                                    with open(expanded_path, "rb") as f:
                                                        voice_bytes = f.read()
                                                    res = await self.bot.send_voice_message(real_wxid, voice_bytes, format=voice_format)
                                                    if self._is_successful_voice_send_result(res):
                                                        logger.success(f"音频以语音消息发送成功: {expanded_path}")
                                                        sent_as_voice = True
                                                    else:
                                                        logger.warning("音频以语音消息发送返回失败状态，将尝试文件发送")
                                                else:
                                                    logger.info(f"音频时长 {duration_ms/1000:.2f}s >= 60s，尝试拆分为语音片段发送")
                                                    sent_as_voice = await self._send_long_audio_as_voice_chunks(
                                                        real_wxid,
                                                        audio_data,
                                                        source_label=expanded_path,
                                                    )
                                            except Exception as audio_err:
                                                logger.warning(f"检测音频时长或发送语音失败: {audio_err}，改用文件发送")

                                        if not sent_as_voice:
                                            if hasattr(self.bot, "send_file_message"):
                                                success = await self.bot.send_file_message(real_wxid, expanded_path)
                                                if success:
                                                    logger.success(f"音频以文件方式发送成功: {expanded_path}")
                                                    self._cache_outbound_media(expanded_path, "audio", real_wxid)
                                                else:
                                                    await self._send_file_as_link(real_wxid, expanded_path, reply_payload=data)
                                            else:
                                                await self._send_file_as_link(real_wxid, expanded_path, reply_payload=data)
                                    else:
                                        logger.info(f"OpenClaw 发送文件给 {real_wxid}: {expanded_path}")
                                        try:
                                            if hasattr(self.bot, "send_file_message"):
                                                success = await self.bot.send_file_message(real_wxid, expanded_path)
                                                if success:
                                                    logger.success(f"文件卡片发送成功: {expanded_path}")
                                                    self._cache_outbound_media(expanded_path, "file", real_wxid)
                                                else:
                                                    logger.warning(f"文件卡片发送失败，回退到下载链接方式: {expanded_path}")
                                                    await self._send_file_as_link(real_wxid, expanded_path, reply_payload=data)
                                            else:
                                                await self._send_file_as_link(real_wxid, expanded_path, reply_payload=data)
                                        except Exception as file_err:
                                            logger.error(f"发送文件失败: {file_err}")
                                            await self._send_file_as_link(real_wxid, expanded_path, reply_payload=data)
                                except Exception as media_err:
                                    logger.error(f"发送{'图片' if is_image else '文件'}失败: {media_err}")
                                    logger.error(traceback.format_exc())
                                    await self._send_text_with_optional_at(real_wxid, f"[文件发送失败: {media_url}]", payload=data)
                            else:
                                logger.warning(f"本地文件不存在: {expanded_path} (Raw: {media_url})")
                                await self._send_text_with_optional_at(real_wxid, f"[文件不存在: {media_url}]", payload=data)
                        else:
                            dedup_key = f"{media_url}|{real_wxid}"
                            now_ts = time.time()
                            if dedup_key in self._recent_media_sent and (now_ts - self._recent_media_sent[dedup_key]) < 10:
                                logger.info(f"媒体去重: 跳过重复发送 {media_url} -> {real_wxid}")
                            else:
                                self._recent_media_sent[dedup_key] = now_ts
                                expired = [k for k, v in self._recent_media_sent.items() if now_ts - v > 30]
                                for k in expired:
                                    del self._recent_media_sent[k]
                                logger.info(f"OpenClaw 发送远程媒体给 {real_wxid}: {media_url}")
                                try:
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(media_url) as resp:
                                            if resp.status == 200:
                                                media_bytes = await resp.read()
                                                logger.info(f"下载远程媒体成功，大小: {len(media_bytes)} 字节")

                                                from urllib.parse import urlparse, unquote

                                                parsed_url = urlparse(media_url)
                                                url_path = unquote(parsed_url.path)
                                                original_filename = os.path.basename(url_path)
                                                url_ext = os.path.splitext(original_filename)[1].lower()

                                                content_type = resp.headers.get("Content-Type", "")
                                                if ";" in content_type:
                                                    content_type = content_type.split(";")[0].strip()

                                                ext = url_ext if url_ext and url_ext != "." else mimetypes.guess_extension(content_type) or ".bin"
                                                image_mimes = ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp", "image/heic", "image/heif"]
                                                video_mimes = ["video/mp4", "video/avi", "video/quicktime", "video/x-msvideo", "video/x-flv", "video/x-matroska", "video/webm"]
                                                audio_mimes = ["audio/mpeg", "audio/wav", "audio/flac", "audio/aac", "audio/ogg", "audio/mp4", "audio/x-ms-wma"]

                                                is_image = content_type in image_mimes or ext.lower() in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"]
                                                is_video = content_type in video_mimes or ext.lower() in [".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".webm", ".m4v"]
                                                is_audio = content_type in audio_mimes or ext.lower() in [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"]
                                                os.makedirs(FILES_DIR, exist_ok=True)

                                                md5 = hashlib.md5(media_bytes).hexdigest()
                                                if original_filename and original_filename != "/" and "." in original_filename:
                                                    safe_filename = original_filename
                                                else:
                                                    safe_filename = f"{md5}{ext}"
                                                temp_path = os.path.join(FILES_DIR, safe_filename)
                                                if os.path.exists(temp_path):
                                                    name_only, name_ext = os.path.splitext(safe_filename)
                                                    temp_path = os.path.join(FILES_DIR, f"{name_only}_{md5[:8]}{name_ext}")

                                                with open(temp_path, "wb") as f:
                                                    f.write(media_bytes)

                                                media_type = "图片" if is_image else ("视频" if is_video else ("音频" if is_audio else "文件"))
                                                logger.info(f"远程媒体类型: {media_type} (Content-Type: {content_type}, 扩展名: {ext})")

                                                if is_image:
                                                    await self.bot.send_image_message(real_wxid, temp_path)
                                                    logger.success(f"远程图片发送成功: {media_url} -> {temp_path}")
                                                elif is_video:
                                                    sent = await self._send_video_path(real_wxid, temp_path)
                                                    if sent:
                                                        logger.success(f"远程视频发送成功: {media_url} -> {temp_path}")
                                                    else:
                                                        logger.warning(f"远程视频发送失败，已回退处理: {media_url} -> {temp_path}")
                                                elif is_audio:
                                                    sent_as_voice = False
                                                    if ext in [".mp3", ".wav", ".amr"] and hasattr(self.bot, "send_voice_message"):
                                                        try:
                                                            from pydub import AudioSegment

                                                            audio_data = AudioSegment.from_file(temp_path)
                                                            duration_ms = len(audio_data)
                                                            if duration_ms < 60000:
                                                                logger.info(f"远程音频时长 {duration_ms/1000:.2f}s < 60s，使用语音消息发送")
                                                                voice_format = ext[1:] if ext[1:] in ["amr", "wav", "mp3"] else "mp3"
                                                                with open(temp_path, "rb") as f:
                                                                    voice_bytes = f.read()
                                                                try:
                                                                    await self.bot.send_voice_message(real_wxid, voice_bytes, format=voice_format)
                                                                except Exception as voice_err:
                                                                    logger.warning(f"send_voice_message 异常: {voice_err}")
                                                                logger.success(f"远程音频已调用语音接口发送: {media_url}")
                                                                sent_as_voice = True
                                                            else:
                                                                logger.info(f"远程音频时长 {duration_ms/1000:.2f}s >= 60s，尝试拆分为语音片段发送")
                                                                sent_as_voice = await self._send_long_audio_as_voice_chunks(
                                                                    real_wxid,
                                                                    audio_data,
                                                                    source_label=media_url or temp_path,
                                                                    assume_sent_on_no_exception=True,
                                                                )
                                                        except Exception as audio_err:
                                                            logger.warning(f"检测远程音频时长或发送语音失败: {audio_err}，改用文件发送")

                                                    if not sent_as_voice:
                                                        if hasattr(self.bot, "send_file_message"):
                                                            success = await self.bot.send_file_message(real_wxid, temp_path)
                                                            if success:
                                                                logger.success(f"远程音频以文件方式发送成功: {media_url} -> {temp_path}")
                                                            else:
                                                                await self._send_file_as_link(real_wxid, temp_path, reply_payload=data)
                                                        else:
                                                            await self._send_file_as_link(real_wxid, temp_path, reply_payload=data)
                                                else:
                                                    if hasattr(self.bot, "send_file_message"):
                                                        success = await self.bot.send_file_message(real_wxid, temp_path)
                                                        if success:
                                                            logger.success(f"远程文件发送成功: {media_url} -> {temp_path}")
                                                        else:
                                                            await self._send_file_as_link(real_wxid, temp_path, reply_payload=data)
                                                    else:
                                                        await self._send_file_as_link(real_wxid, temp_path, reply_payload=data)
                                            else:
                                                await self._send_text_with_optional_at(real_wxid, f"[媒体下载失败: {media_url}]", payload=data)
                                except Exception as dl_err:
                                    logger.error(f"下载远程媒体失败: {dl_err}")
                                    logger.error(traceback.format_exc())
                                    await self._send_text_with_optional_at(real_wxid, f"[远程媒体下载失败: {media_url}]", payload=data)
            
            return web.Response(text="OK")
        except Exception as e:
            logger.error(f"处理 OpenClaw 回调时出错: {e}")
            return web.Response(status=500, text=str(e))

    @on_image_message(priority=10)
    async def handle_image(self, bot, message):
        self._cache_media(message, "image")

    @on_file_message(priority=10)
    async def handle_file(self, bot, message):
        self._cache_media(message, "file")

    @on_video_message(priority=10)
    async def handle_video(self, bot, message):
        self._cache_media(message, "video")

    def _cache_outbound_media(self, file_path, media_type, wxid):
        """缓存机器人发送的媒体文件到 FILES_DIR，方便用户二次引用"""
        try:
            if not os.path.exists(file_path):
                return
            import shutil
            with open(file_path, "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            
            original_name = os.path.basename(file_path)
            cached_filename = f"{md5}_{original_name}"
            cached_path = os.path.join(FILES_DIR, cached_filename)
            
            os.makedirs(FILES_DIR, exist_ok=True)
            
            # 如果目标文件不存在才复制（避免重复写入）
            if not os.path.exists(cached_path):
                shutil.copy2(file_path, cached_path)
                logger.debug(f"已缓存机器人发送的文件到 FILES_DIR: {cached_path}")
            
            # 注册到内存缓存
            self.file_cache[md5] = {
                "path": cached_path,
                "timestamp": time.time(),
                "type": media_type,
                "name": original_name
            }
            # 这里用机器人自己的 wxid 作为 key，方便引用消息查找
            # 但也用接收者 wxid 存一份，因为引用场景是对方引用机器人发的消息
            self.user_latest_files[wxid] = {"md5": md5, "timestamp": time.time(), "type": media_type}
            logger.debug(f"已缓存机器人发送的媒体: MD5={md5}, Type={media_type}, To={wxid}")
        except Exception as e:
            logger.warning(f"缓存机器人发送的文件失败（不影响发送）: {e}")

    def _cache_media(self, message, media_type):
        """缓存用户发送的媒体文件路径"""
        sender = message["SenderWxid"] if message["IsGroup"] else message["FromWxid"]
        
        # 1. 尝试获取 MD5
        md5 = message.get("Md5") or message.get("ImgMd5")
        file_path = message.get("FilePath")
        
        # 如果消息中没有直接提供路径，尝试从其他字段获取
        if not file_path and "ThumbPath" in message:
             file_path = message["ThumbPath"]
             
        # 如果没有 MD5 但有文件，计算 MD5
        if not md5 and file_path and os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    md5 = hashlib.md5(f.read()).hexdigest()
            except Exception as e:
                logger.error(f"计算文件 MD5 失败: {e}")

        # 如果还没有 MD5，则无法缓存
        if not md5:
            return

        # 2. 查找文件路径 (优先使用全局 files 目录中的文件)
        # 很多时候 WechatAPI 会把文件下载到 files 目录，或者 Dify 插件已经下载过了
        final_path = None
        
        # 检查 files 目录下是否有该 MD5 的文件
        # 通常文件名为 {md5}.{ext} 或者需要在该目录下搜索包含此 MD5 的文件
        # 这里做一个简单的遍历查找 (假设文件名包含 MD5)
        if os.path.exists(FILES_DIR):
            for filename in os.listdir(FILES_DIR):
                if md5.lower() in filename.lower():
                    final_path = os.path.join(FILES_DIR, filename)
                    break
        
        # 如果 files 目录没找到，且消息自带路径有效，则使用消息路径
        if not final_path and file_path and os.path.exists(file_path):
            final_path = file_path
            
        if final_path:
            self.file_cache[md5] = {
                "path": final_path,
                "timestamp": time.time(),
                "type": media_type,
                "name": os.path.basename(final_path)
            }
            self.user_latest_files[sender] = {"md5": md5, "timestamp": time.time(), "type": media_type}
            logger.debug(f"已缓存媒体文件: MD5={md5}, Path={final_path}, User={sender}")
    @on_image_message(priority=30)
    async def handle_image(self, bot, message):
        """缓存图片文件，不自动转发。只有当文本消息触发时才会附带媒体一起发送。"""
        self.bot = bot
        self._cache_media(message, "image")

    @on_file_message(priority=30)
    async def handle_file(self, bot, message):
        """缓存文件，不自动转发。只有当文本消息触发时才会附带媒体一起发送。"""
        self.bot = bot
        self._cache_media(message, "file")

    @on_voice_message(priority=30)
    async def handle_voice(self, bot, message):
        """缓存语音消息，不自动转发。"""
        self.bot = bot
        # 语音消息暂不缓存，因为通常需要转文字处理

    @on_video_message(priority=30)
    async def handle_video(self, bot, message):
        """缓存视频文件，不自动转发。只有当文本消息触发时才会附带媒体一起发送。"""
        self.bot = bot
        self._cache_media(message, "video")

    def is_allowed(self, session_id):
        """检查会话(群或用户)是否允许访问 (基于白名单/黑名单)"""
        filters = self.config["filters"]
        filter_mode = filters.get("filter_mode", "None")
        whitelist = filters.get("whitelist", [])
        blacklist = filters.get("blacklist", [])

        if filter_mode == "Whitelist":
            if session_id not in whitelist:
                return False
        elif filter_mode == "Blacklist":
            if session_id in blacklist:
                return False
        return True

    @on_at_message(priority=30)
    async def handle_at(self, bot, message):
        """处理@消息（包括被 Robot Name 转换而来的唤醒消息）"""
        self.bot = bot
        
        # 强制标记为 At 机器人，确保 handle_text 能识别
        # 当通过 Robot Name 触发时，At 列表可能为空，导致 handle_text 认为不是 @消息
        if self.bot and self.bot.wxid:
             at_list = message.get("At", "")
             current_ats = []
             
             if isinstance(at_list, list):
                 current_ats = list(at_list)
             elif isinstance(at_list, str):
                 # 处理空字符串或逗号分割
                 current_ats = [x for x in at_list.split(",") if x]
             
             # 如果 robot wxid 不在列表中，则添加
             if self.bot.wxid not in current_ats:
                 logger.debug(f"[OpenClawBridge] 注入 Robot Wxid 到 At 列表: {self.bot.wxid}")
                 current_ats.append(self.bot.wxid)
                 # 更新 message["At"]。为了兼容性，如果是列表就保持列表，如果是字符串就保持字符串
                 if isinstance(at_list, list):
                     message["At"] = current_ats
                 else:
                     message["At"] = ",".join(current_ats)

        logger.info(f"OpenClawBridge 捕获到 @消息: {message.get('MsgId')}, 内容: {message.get('Content')}")
        # 复用 handle_text 的转发逻辑，因为 handle_text 内部也会检查 is_at 并设置 should_forward
        await self.handle_text(bot, message)
        
        # 检查是否已处理并转发
        if hasattr(bot, "_handled_msg_ids") and message.get("MsgId") in bot._handled_msg_ids:
            logger.info(f"OpenClawBridge 已处理该消息 {message.get('MsgId')}，停止后续插件")
            return True
        return False

    @on_quote_message(priority=30)
    async def handle_quote_message(self, bot, message):
        """处理引用回复消息"""
        logger.info(f"OpenClawBridge 收到引用消息: {message.get('MsgId')}")
        # 引用消息通常包含用户输入的文本，直接交给 handle_text 处理
        await self.handle_text(bot, message)

    @on_xml_message(priority=30)
    async def handle_xml_message(self, bot, message):
        """处理XML消息 - 捕获GroupAtFilter重发的引用消息（含文本/图片/卡片引用）"""
        if not message.get("ProcessedByGroupAtFilter", False):
            return  # 只处理 GroupAtFilter 重发的，其他XML消息不管
        logger.info(f"[OpenClawBridge] 收到 GroupAtFilter 重发的XML消息: MsgId={message.get('MsgId')}，转交 handle_text")
        await self.handle_text(bot, message)

    @on_text_message(priority=30)
    async def handle_text(self, bot, message):
        self.bot = bot
        msg_id = message.get("MsgId")
        if message.get("_is_handled"):
            logger.info(f"[OpenClawBridge] 跳过已处理消息: MsgId={msg_id}")
            return
        if hasattr(bot, "_handled_msg_ids") and msg_id in bot._handled_msg_ids:
            logger.info(f"[OpenClawBridge] 跳过重复消息: MsgId={msg_id}")
            message["_is_handled"] = True
            return
        await self.get_contacts_cache()
        content = message["Content"].strip()
        from_wxid = message["FromWxid"]
        is_group = message["IsGroup"]
        sender_wxid = message["SenderWxid"] if is_group else from_wxid
        if is_group:
            self._schedule_group_members_snapshot(from_wxid)
        
        # 0. 黑白名单检查
        filters = self.config["filters"]
        filter_mode = filters.get("filter_mode", "None")
        whitelist = filters.get("whitelist", [])
        blacklist = filters.get("blacklist", [])
        
        if filter_mode == "Whitelist":
            # 白名单模式：群ID或发送者ID任意一个在白名单即可
            if from_wxid not in whitelist and sender_wxid not in whitelist:
                return
        elif filter_mode == "Blacklist":
            # 黑名单模式：群ID或发送者ID任意一个在黑名单即拦截
            if from_wxid in blacklist or sender_wxid in blacklist:
                return
        
        # 检查是否是@消息
        at_user_list = message.get("At", "")
        # 如果是字符串，转列表
        if isinstance(at_user_list, str):
            at_user_list = at_user_list.split(",")
        # 兼容性处理：如果是列表，先复制一份
        if isinstance(at_user_list, list):
            at_user_list = list(at_user_list)
        
        is_at = False
        mention_trigger_user = False
        if self.bot and self.bot.wxid in at_user_list:
             is_at = True
             mention_trigger_user = True

        # 检查是否被 GroupAtFilter 处理过（@或触发词已清理，应当视为需要响应的消息）
        if not is_at and message.get("ProcessedByGroupAtFilter", False) and message.get("NeedsResponse", False):
            is_at = True
            logger.info(f"[OpenClawBridge] 检测到 GroupAtFilter 处理过的消息，视为@消息")
        if is_group and message.get("TriggeredBy") == "at_bot":
            mention_trigger_user = True

        logger.info(f"[OpenClawBridge Debug] MsgId={message.get('MsgId')}, At={at_user_list}, RobotWxid={self.bot.wxid if self.bot else 'None'}, is_at={is_at}, ProcessedByGroupAtFilter={message.get('ProcessedByGroupAtFilter', False)}")
        
        # 过滤逻辑
        filters = self.config["filters"]
        mention_only = filters.get("mention_only", True)
        allow_groups = filters.get("allow_groups", True)
        trigger_words = filters.get("trigger_words", [])
        
        should_forward = False
        matched_trigger = False
        
        # 1. 检查触发词 (最高优先级)
        lowered_content = content.lower()
        for trigger in trigger_words:
            normalized_trigger = str(trigger).strip()
            if not normalized_trigger:
                continue
            lowered_trigger = normalized_trigger.lower()
            if lowered_content.startswith(lowered_trigger):
                logger.info(f"[OpenClawBridge Debug] Matched trigger prefix: {normalized_trigger}")
                should_forward = True
                matched_trigger = True
                content = content[len(normalized_trigger):].strip() # 移除前缀触发词
                matched_trigger = True
                break
            if lowered_trigger in lowered_content:
                logger.info(f"[OpenClawBridge Debug] Matched trigger in content: {normalized_trigger}")
                should_forward = True
                matched_trigger = True
                break
        
        # 2. 如果未匹配触发词，则检查常规规则
        if not should_forward:
            if not is_group:
                # 检查私聊@触发禁用开关
                disable_private = filters.get("disable_private_chat_at_trigger", False)
                if not disable_private:
                    # 如果未禁用，总是转发私聊消息 (不需要触发词)
                    should_forward = True 
                else:
                    logger.debug("[OpenClawBridge Debug] Private chat trigger disabled, ignoring message without trigger word")
            else:
                if is_at:
                    should_forward = True
                elif not mention_only and allow_groups:
                    should_forward = True
        
        # 3. 特殊处理：如果是通过 aibot 唤醒词（Robot Name）触发的 At 消息，虽然内容被剥离了，
        # 但我们希望能兼容 OpenClawBridge 的 trigger_words 配置。
        # 如果 is_at 为真，且 matched_trigger 为假，说明可能原来的 Robot Name 就是 trigger word。
        # 这种情况下，我们已经在上面把 should_forward 设为 True 了，所以其实会被转发。
        # 这里主要是确认一下，如果用户只配了 "老猪" 在 Robot Name 里，没配在 trigger_words 里？
        # 用户都配了。所以 trigger_words 在这里已经没用了（因为内容被剥离了）。
        # 但只要 is_at = True，这里就会转发。
        pass
        
        if should_forward:
             # ----------------------
             # 2.5 群聊频率限制检查
             # ----------------------
             if is_group and self.limits_config.get("enable_group_limit", False):
                 # 检查发送者是否在白名单中 (白名单用户不受限制)
                 if sender_wxid in whitelist:
                     logger.info(f"发送者 {sender_wxid} 在白名单中，跳过频率限制检查")
                 else:
                     # 获取当前时间
                     now = time.time()
                     
                     # 从数据库加载群组记录
                     db_key = f"group_limit:{from_wxid}"
                     record = None
                     try:
                         conn = group_members_db_module._connect()
                         try:
                             row = conn.execute("SELECT count, reset_time FROM group_limits WHERE group_wxid=?", (from_wxid,)).fetchone()
                             if row:
                                 record = {"count": int(row[0]), "reset_time": float(row[1])}
                         finally:
                             conn.close()
                     except Exception as db_err:
                         logger.warning(f"从数据库加载群限制记录失败: {db_err}")
                     
                     if not record:
                         record = {"count": 0, "reset_time": self._get_group_limit_reset_time(now)}
                     
                     # 检查是否需要重置
                     if self._should_reset_group_limit_record(record, now):
                         record = {"count": 0, "reset_time": self._get_group_limit_reset_time(now)}
                         logger.info(f"群聊 {from_wxid} 频率限制已重置")
                     
                     # 获取该群的限制数
                     custom_limits = self.limits_config.get("custom_groups", {}) or {}
                     limit = custom_limits.get(from_wxid, self.limits_config.get("default_group_limit", 50))
                     
                     # 检查是否超限
                     if record["count"] >= limit:
                         logger.warning(f"群聊 {from_wxid} 达到频率限制 ({record['count']}/{limit})，拒绝处理")
                         if record["count"] == limit:
                             msg = self.limits_config.get("limit_reached_message", "本群今日提问次数已达上限")
                             await bot.send_text_message(from_wxid, msg)
                             record["count"] += 1
                             # 保存到数据库
                             try:
                                 conn = group_members_db_module._connect()
                                 try:
                                     conn.execute(
                                         "INSERT OR REPLACE INTO group_limits (group_wxid, count, reset_time, updated_at) VALUES (?, ?, ?, ?)",
                                         (from_wxid, int(record["count"]), float(record["reset_time"]), int(time.time())),
                                     )
                                     conn.commit()
                                 finally:
                                     conn.close()
                             except Exception:
                                 pass
                         return

                     # 未超限，增加计数
                     record["count"] += 1
                     logger.info(f"群聊 {from_wxid} 消耗一次额度 ({record['count']}/{limit})")
                     # 保存到数据库
                     try:
                         conn = group_members_db_module._connect()
                         try:
                             conn.execute(
                                 "INSERT OR REPLACE INTO group_limits (group_wxid, count, reset_time, updated_at) VALUES (?, ?, ?, ?)",
                                 (from_wxid, int(record["count"]), float(record["reset_time"]), int(time.time())),
                             )
                             conn.commit()
                         finally:
                             conn.close()
                     except Exception as db_err:
                         logger.warning(f"保存群限制记录到数据库失败: {db_err}")

             # 标记消息已被 OpenClaw 处理 (使用 bot 实例共享状态)
             if not hasattr(bot, "_handled_msg_ids"):
                 bot._handled_msg_ids = set()
             bot._handled_msg_ids.add(message["MsgId"])
             
             # 简单的内存管理：如果积压太多，清空旧的
             if len(bot._handled_msg_ids) > 1000:
                 bot._handled_msg_ids.clear()
                 bot._handled_msg_ids.add(message["MsgId"])

             # 如果不是通过触发词触发的，则尝试移除 @机器人 名称
             if not matched_trigger:
                 for name in self.robot_names:
                     content = content.replace(f"@{name}", "").strip()
             
             # 检查是否有引用或最近的媒体文件
             media_data = None
             target_md5 = None
             media_path = None  # 直接的文件路径
             quoted_text_content = None  # 引用的文本内容（已清理）
             
             # 1. 检查是否有引用消息
             quote = message.get("Quote")
             if quote:
                 quoted_content = quote.get("Content", "")
                 quoted_wxid = quote.get("FromWxid")
                 quoted_sender = quote.get("Nickname", "")
                 quoted_file_meta = self._extract_quote_file_metadata(quote, quoted_content)
                  
                 # 尝试直接从 Quote 对象获取 URL (某些版本的 API 可能直接提供)
                 direct_url = quote.get("Url") or quote.get("url")
                 
                 # 处理引用的文本消息（非媒体类型）
                 # 只有当引用内容不是媒体消息时才提取文本
                 if (quoted_content or direct_url) and not media_path:
                     # 检查是否为纯媒体消息（图片、视频、语音、表情等）
                     is_pure_media = (
                         quoted_file_meta["is_file_quote"]
                         or quote.get("MsgType") in [3, 34, 43, 47]
                         or any(tag in quoted_content for tag in [
                         "<img", "<videomsg", "<voicemsg",
                         "&lt;img", "&lt;videomsg", "&lt;voicemsg"
                         ])
                     )
                     
                     # 检查是否为公众号/链接卡片消息 (放宽判断条件)
                     is_link_card = direct_url or "<appmsg" in quoted_content or "&lt;appmsg" in quoted_content or "<url>" in quoted_content or "http" in quoted_content
                     
                     if is_link_card and not is_pure_media:
                         # 提取公众号卡片的标题和 URL
                         quoted_title = None
                         quoted_url = direct_url
                         
                         # 提取 <title>
                         title_match = re.search(r'<title>([^<]+)</title>', quoted_content)
                         if title_match:
                             quoted_title = title_match.group(1).replace("<![CDATA[", "").replace("]]>", "")
                         
                         # 如果没有直接 URL，尝试从内容提取
                         if not quoted_url:
                             # 提取 <url>
                             url_match = re.search(r'<url>([^<]+)</url>', quoted_content)
                             if url_match:
                                 quoted_url = url_match.group(1)
                                 # 解码 HTML 实体
                                 quoted_url = quoted_url.replace('&amp;', '&').replace("<![CDATA[", "").replace("]]>", "")
                             
                             # 如果没找到，尝试直接匹配公众号链接或普通 HTTP 链接
                             if not quoted_url:
                                 url_pattern = r'(https?://[^\s<>"\']+)'
                                 mp_match = re.search(url_pattern, quoted_content)
                                 if mp_match:
                                     quoted_url = mp_match.group(1).replace('&amp;', '&')
                         
                         # 构建引用文本
                         if quoted_url:
                             # 用户要求只保留 URL，去掉标题和发送者信息
                             quoted_text_content = quoted_url
                             logger.info(f"提取引用链接: 标题={quoted_title}, URL={quoted_url[:60]}...")
                         else:
                             # 虽看起来像链接卡片但没提取到 URL，回退到普通文本处理
                             is_link_card = False
                     
                     if not is_link_card and not is_pure_media:
                         # 普通文本消息处理
                         clean_text = quoted_content
                         
                         # 如果包含 XML，尝试移除所有标签
                         if "<?xml" in clean_text or "<" in clean_text:
                             clean_text = re.sub(r'<[^>]+>', ' ', clean_text).strip()
                         
                         # 处理 wxid_xxx:内容 格式
                         if ":" in clean_text and clean_text.startswith("wxid_"):
                             parts = clean_text.split(":", 1)
                             if len(parts) > 1:
                                 clean_text = parts[1].strip()
                         
                         # 移除多余空白
                         clean_text = " ".join(clean_text.split())
                         
                         if clean_text and len(clean_text) > 1:
                             quoted_text_content = f'[引用 {quoted_sender}]: {clean_text}'
                             logger.debug(f"提取引用文本: {quoted_text_content[:50]}...")
                 
                 # 1.1 检查是否有直接的 video_path（aibot.py 会解析并添加）
                 if quote.get("video_path"):
                     potential_path = quote.get("video_path")
                     if not os.path.isabs(potential_path):
                         potential_path = os.path.join(os.getcwd(), potential_path)
                     if os.path.exists(potential_path):
                         media_path = potential_path
                         logger.info(f"从引用消息获取到视频路径: {media_path}")
                 
                 # 1.1.1 检查是否有直接的 voice_path（aibot.py 会解析语音引用并添加）
                 if not media_path and quote.get("voice_path"):
                     potential_path = quote.get("voice_path")
                     if not os.path.isabs(potential_path):
                         potential_path = os.path.join(os.getcwd(), potential_path)
                     if os.path.exists(potential_path):
                         media_path = potential_path
                         logger.info(f"从引用消息获取到语音路径: {media_path}")
                 
                 # 1.2 检查是否有直接的 file_path（文件消息，如 PDF、TXT 等）
                 if not media_path and (quote.get("file_path") or quote.get("FilePath")):
                     potential_path = quote.get("file_path") or quote.get("FilePath")
                     if not os.path.isabs(potential_path):
                         potential_path = os.path.join(os.getcwd(), potential_path)
                     if os.path.exists(potential_path):
                         media_path = potential_path
                         logger.info(f"从引用消息获取到文件路径: {media_path}")
                 
                 # 1.3 尝试从 XML 中提取 aeskey（视频消息使用 aeskey 作为文件名）
                 if not media_path and quoted_content:
                     aeskey_match = re.search(r'aeskey="([a-fA-F0-9]+)"', quoted_content, re.IGNORECASE)
                     if aeskey_match:
                         video_aeskey = aeskey_match.group(1).lower()
                         potential_path = os.path.join(FILES_DIR, f"{video_aeskey}.mp4")
                         if os.path.exists(potential_path):
                             media_path = potential_path
                             target_md5 = video_aeskey
                             logger.info(f"从引用消息 XML 中提取到 aeskey，找到视频: {media_path}")
                         else:
                             # 引用视频：本地未落盘时，尝试用 869 的 SendCdnDownload 直接下载视频文件
                             try:
                                 import html as _html
                                 normalized_xml = _html.unescape(quoted_content)
                                 cdnvideo_match = re.search(r'cdnvideourl="([^"]+)"', normalized_xml, re.IGNORECASE)
                                 cdnvideo_url = cdnvideo_match.group(1).strip() if cdnvideo_match else ""
                                 playlen_match = re.search(r'playlength="(\d+)"', normalized_xml, re.IGNORECASE)
                                 playlen = int(playlen_match.group(1)) if playlen_match else 0
                                 
                                 if cdnvideo_url and self.bot and hasattr(self.bot, "download_attach"):
                                     logger.info(
                                         f"引用视频：本地未命中，尝试下载 (aeskey={video_aeskey}, cdnvideourl={cdnvideo_url[:30]}..., playlength={playlen})"
                                     )
                                     # 经验：视频下载优先尝试 FileType=4
                                     cdn_attach_id = self._build_cdn_attach_id(cdnvideo_url, video_aeskey, file_type=4)
                                     b64 = await self.bot.download_attach(cdn_attach_id) if cdn_attach_id else ""
                                     if b64:
                                         video_bytes = self._decode_download_payload(b64)
                                         if video_bytes:
                                             os.makedirs(FILES_DIR, exist_ok=True)
                                             md5hex = hashlib.md5(video_bytes).hexdigest()
                                             save_path = os.path.join(FILES_DIR, f"{md5hex}.mp4")
                                             if not os.path.exists(save_path):
                                                 with open(save_path, "wb") as f:
                                                     f.write(video_bytes)
                                             media_path = save_path
                                             target_md5 = md5hex
                                             # 更新缓存，便于后续引用复用
                                             self.file_cache[md5hex] = {
                                                 "path": media_path,
                                                 "timestamp": time.time(),
                                                 "type": "video",
                                                 "name": os.path.basename(media_path),
                                             }
                                             logger.success(f"引用视频：下载并落地成功: {media_path} ({len(video_bytes)} bytes)")
                                     else:
                                         logger.warning("引用视频：download_attach 返回空")
                             except Exception as e:
                                 logger.warning(f"引用视频：解析/下载失败: {e}")
                                 logger.debug(traceback.format_exc())
                 
                 # 1.4 尝试从 XML 中提取文件名（适用于文件消息：PDF、TXT、DOC 等）
                 if not media_path and quoted_file_meta["is_file_quote"]:
                     quoted_filename = quoted_file_meta["filename"]
                     if quoted_filename:
                         # 在 FILES_DIR 中查找包含该文件名的文件
                         if os.path.exists(FILES_DIR):
                             for f in os.listdir(FILES_DIR):
                                 if quoted_filename in f:
                                     media_path = os.path.join(FILES_DIR, f)
                                     logger.info(f"从引用消息 XML 中提取到文件名，找到文件: {media_path}")
                                     break

                     # 引用文件：本地未命中时，尝试从 appattach 元数据下载附件并刷新缓存
                     if not media_path and self.bot and hasattr(self.bot, "download_attach"):
                         try:
                             import hashlib as _hashlib
                             attach_id = quoted_file_meta["attach_id"]
                             total_len = quoted_file_meta["total_len"]
                             file_aeskey = quoted_file_meta["file_aeskey"]
                             file_url = quoted_file_meta["file_url"]
                             file_ext = quoted_file_meta["file_ext"]
                             if quoted_file_meta["md5"]:
                                 target_md5 = quoted_file_meta["md5"]

                             if file_ext and (attach_id or (file_aeskey and file_url)):
                                 logger.info(
                                     f"引用文件：本地未命中，尝试下载 (attachid={attach_id}, size={total_len}, ext={file_ext})"
                                 )
                                 download_wxid_candidates = [
                                     from_wxid,
                                     quote.get("ToWxid", ""),
                                     quote.get("FromWxid", ""),
                                     quoted_wxid,
                                     sender_wxid,
                                     getattr(self.bot, "wxid", ""),
                                 ]
                                 downloaded_file = await self._download_quote_file_payload(
                                     attach_id,
                                     file_url,
                                     file_aeskey,
                                     wxid_candidates=download_wxid_candidates,
                                 )
                                 if downloaded_file:
                                     file_bytes = self._decode_download_payload(downloaded_file)
                                     if file_bytes:
                                         os.makedirs(FILES_DIR, exist_ok=True)
                                         cache_key = target_md5 or _hashlib.md5(file_bytes).hexdigest()
                                         target_md5 = cache_key
                                         safe_name = os.path.basename(quoted_filename) if quoted_filename else ""
                                         if not safe_name:
                                             safe_name = f"{cache_key}.{file_ext}"
                                         elif file_ext and not safe_name.lower().endswith(f".{file_ext.lower()}"):
                                             safe_name = f"{safe_name}.{file_ext}"
                                         save_path = os.path.join(FILES_DIR, safe_name)
                                         with open(save_path, "wb") as f:
                                             f.write(file_bytes)
                                         media_path = save_path
                                         self.file_cache[cache_key] = {
                                             "path": media_path,
                                             "timestamp": time.time(),
                                             "type": "file",
                                             "name": os.path.basename(media_path),
                                         }
                                         logger.success(
                                             f"引用文件：下载并落地成功: {media_path} ({len(file_bytes)} bytes)"
                                         )
                                     else:
                                         logger.warning("引用文件：download_attach 返回空字节")
                                 else:
                                     logger.warning("引用文件：download_attach 返回空")
                             else:
                                 logger.warning("引用文件：appattach 元数据缺失，跳过下载回退")
                         except Exception as e:
                             logger.warning(f"引用文件：解析/下载失败: {e}")
                             logger.debug(traceback.format_exc())
                 
                 # 1.5 尝试从用户最新文件缓存获取
                 if not target_md5 and not media_path and quoted_wxid in self.user_latest_files:
                     latest_media = self.user_latest_files.get(quoted_wxid) or {}
                     latest_md5 = latest_media.get("md5") if isinstance(latest_media, dict) else latest_media
                     latest_ts = latest_media.get("timestamp", 0) if isinstance(latest_media, dict) else 0
                     if latest_md5 and (time.time() - latest_ts) < MEDIA_CACHE_TIMEOUT:
                         target_md5 = latest_md5
                         logger.debug(f"检测到引用消息，使用用户 {quoted_wxid} 的最近附件 MD5: {target_md5}")
                 
                 # 1.6 尝试从 XML 中提取 md5（通用）
                 if not target_md5 and not media_path and quoted_content:
                     md5_match = re.search(r'md5="([a-fA-F0-9]{32})"', quoted_content)
                     if not md5_match:
                         # 尝试 XML 标签格式 <md5>...</md5>
                         md5_match = re.search(r'<md5>([a-fA-F0-9]{32})</md5>', quoted_content)
                     if md5_match:
                         target_md5 = md5_match.group(1).lower()
                         quote_has_image_metadata = any(
                             quote.get(key)
                             for key in (
                                 "aeskey",
                                 "cdnmidimgurl",
                                 "cdnbigimgurl",
                                 "cdnthumburl",
                                 "cdnthumbaeskey",
                                 "tpurl",
                                 "tphdurl",
                                 "tpthumburl",
                                 "tpthumbaeskey",
                             )
                         )
                         if not media_path and quote_has_image_metadata:
                             resolved_media_path, resolved_md5 = await self._resolve_quote_image_path(quote, quoted_content)
                             if resolved_md5 and not target_md5:
                                 target_md5 = resolved_md5
                             if resolved_media_path:
                                 media_path = resolved_media_path
                         logger.debug(f"从引用消息 XML 中提取到 MD5: {target_md5}")

                 # 1.7 引用图片：如果提取到了 md5 但本地没找到文件，尝试用 aeskey + CDN URL 主动下载落地
                 quote_has_image_metadata = any(
                     quote.get(key)
                     for key in (
                         "aeskey",
                         "cdnmidimgurl",
                         "cdnbigimgurl",
                         "cdnthumburl",
                         "cdnthumbaeskey",
                         "tpurl",
                         "tphdurl",
                         "tpthumburl",
                         "tpthumbaeskey",
                     )
                 )
                 if (
                     not media_path
                     and (
                         quote_has_image_metadata
                         or (
                             quoted_content
                             and ("<img" in quoted_content or "&lt;img" in quoted_content)
                         )
                     )
                 ):
                     try:
                         import html as _html

                         normalized_xml = _html.unescape(quoted_content)
                         img_md5, _, _ = self._extract_quote_image_metadata(quote, normalized_xml)
                         if img_md5 and not target_md5:
                             target_md5 = img_md5

                         resolved_media_path, resolved_md5 = await self._resolve_quote_image_path(quote, normalized_xml)
                         if resolved_md5 and not target_md5:
                             target_md5 = resolved_md5
                         if resolved_media_path:
                             media_path = resolved_media_path
                     except Exception as e:
                         logger.warning(f"引用图片：解析/下载失败: {e}")
                         logger.debug(traceback.format_exc())
             
             # 2. 不再对普通文本自动继承发送者最近附件；
             # 仅在明确引用消息时才走上面的附件回退逻辑，避免后续每条消息都粘上旧文件。
             
             # 3. 初始化媒体变量（如果还没有设置）
             media_type = "application/octet-stream"
             media_name = "unknown"
             
             # 4. 如果已经有了 media_path（从引用消息直接获取），检测 MIME 类型并构建 media_data
             if (
                 media_path
                 and quoted_content
                 and ("<img" in quoted_content or "&lt;img" in quoted_content)
                 and not self._is_valid_image_file(media_path)
             ):
                 logger.warning(f"引用图片：跳过无效媒体路径: {media_path}")
                 media_path = None
             if media_path and os.path.exists(media_path):
                 guessed_mime, _ = mimetypes.guess_type(media_path)
                 media_type = guessed_mime or "application/octet-stream"
                 media_name = os.path.basename(media_path)
                 logger.info(f"使用直接获取的媒体路径: {media_path} ({media_type})")
                 
                 # 直接构建 media_data - 统一使用路径模式
                 media_data = {"local_path": media_path,
                     "path": media_path,
                     "mime": media_type,
                     "name": media_name
                 }
                
                 # 添加 URL，方便 OpenClaw 远程下载
                 base_url = self.config.get("openclaw", {}).get("download_base_url", "")
                 if base_url:
                     # 确保 base_url 不以 / 结尾
                     base_url = base_url.rstrip("/")
                     filename = os.path.basename(media_path)
                     media_data["url"] = f"{base_url}/files/{filename}"
                     # 关键修复: 将 path 也设置为 URL，确保 OpenClaw 将其识别为远程文件
                     media_data["path"] = media_data["url"]
                 published_path = self._attach_media_url(media_data, media_path, preferred_name=media_name)
                 file_size = os.path.getsize(published_path or media_path)
                 logger.info(f"媒体文件，使用路径模式: {media_path} ({file_size} bytes, {media_type})")
             
             # 5. 如果没有 media_path 但有 target_md5，尝试查找文件
             if not media_path and target_md5:
                 # 5.1 尝试从内存缓存中获取路径
                 if target_md5 in self.file_cache:
                     cached = self.file_cache[target_md5]
                     # 检查是否过期 (这里可以放宽一点，因为文件本身是持久存在的，主要是为了关联上下文)
                     if time.time() - cached["timestamp"] < MEDIA_CACHE_TIMEOUT:
                         media_path = cached["path"]
                         media_name = cached["name"]
                         if (
                             quoted_content
                             and ("<img" in quoted_content or "&lt;img" in quoted_content)
                             and not self._is_valid_image_file(media_path)
                         ):
                             logger.warning(f"引用图片：跳过无效缓存图片: {media_path}")
                             media_path = None
                             media_name = "unknown"
                         if not media_path:
                             pass
                         else:
                             # 使用 mimetypes 自动检测 MIME 类型
                             guessed_mime, _ = mimetypes.guess_type(media_path)
                             media_type = guessed_mime or "application/octet-stream"

                 # 5.2 如果内存缓存没找到路径 (可能是在 _cache_media 时没找到文件，只记了 MD5)
                 # 再次尝试在 FILES_DIR 搜索，因为文件可能刚刚才下载完成
                 if not media_path and os.path.exists(FILES_DIR):
                     for filename in os.listdir(FILES_DIR):
                         if target_md5.lower() in filename.lower():
                             candidate_path = os.path.join(FILES_DIR, filename)
                             if (
                                 quoted_content
                                 and ("<img" in quoted_content or "&lt;img" in quoted_content)
                                 and not self._is_valid_image_file(candidate_path)
                             ):
                                 logger.warning(f"引用图片：跳过无效本地图片: {candidate_path}")
                                 continue
                             media_path = candidate_path
                             media_name = filename
                             # 使用 mimetypes 自动检测 MIME 类型
                             guessed_mime, _ = mimetypes.guess_type(media_path)
                             media_type = guessed_mime or "application/octet-stream"
                             break
                             
                 if media_path and os.path.exists(media_path):
                     # 统一使用路径模式
                     media_data = {"local_path": media_path,
                         "path": media_path,
                         "mime": media_type,
                         "name": media_name,
                      "local_path": media_path
                     }
                     
                     # 添加 URL，方便 OpenClaw 远程下载
                     base_url = self.config.get("openclaw", {}).get("download_base_url", "")
                     if base_url:
                         # 确保 base_url 不以 / 结尾
                         base_url = base_url.rstrip("/")
                         filename = os.path.basename(media_path)
                         media_data["url"] = f"{base_url}/files/{filename}"
                         # 关键修复: 将 path 也设置为 URL，确保 OpenClaw 将其识别为远程文件
                         media_data["path"] = media_data["url"]
                     
                     published_path = self._attach_media_url(media_data, media_path, preferred_name=media_name)
                     file_size = os.path.getsize(published_path or media_path)
                     logger.info(f"媒体文件 (MD5: {target_md5}): {media_path} ({file_size} bytes, {media_type})")

             if media_data and isinstance(media_data, dict):
                 media_url = (media_data.get("url") or media_data.get("path") or "").strip()
                 if media_url.startswith("http://") or media_url.startswith("https://"):
                     quoted_text_content = media_url

             if media_data and not quoted_text_content:
                 media_hint_name = media_name if media_name and media_name != "unknown" else os.path.basename(media_path or "")
                 if media_type.startswith("image/"):
                     quoted_text_content = f"[引用图片: {media_hint_name or '未命名图片'}]"
                 elif media_type.startswith("video/"):
                     quoted_text_content = f"[引用视频: {media_hint_name or '未命名视频'}]"
                 elif media_type.startswith("audio/"):
                     quoted_text_content = f"[引用音频: {media_hint_name or '未命名音频'}]"
                 else:
                     quoted_text_content = f"[引用文件: {media_hint_name or '未命名文件'}]"

             if quote and not quoted_text_content and not media_data:
                 msg_type = quote.get("MsgType")
                 if quoted_file_meta.get("is_file_quote"):
                     file_hint_name = quoted_file_meta.get("filename") or "未命名文件"
                     quoted_text_content = f"[引用文件: {file_hint_name}]"
                 elif msg_type == 3 or any(tag in quoted_content for tag in ("<img", "&lt;img")):
                     quoted_text_content = "[引用图片]"
                 elif msg_type == 43 or any(tag in quoted_content for tag in ("<videomsg", "&lt;videomsg")):
                     quoted_text_content = "[引用视频]"
                 elif msg_type == 34 or any(tag in quoted_content for tag in ("<voicemsg", "&lt;voicemsg")):
                     quoted_text_content = "[引用音频]"
                 elif msg_type == 47:
                     quoted_text_content = "[引用表情]"

             if content or media_data or quoted_text_content:
                 # 如果有引用的文本内容，附加到消息中
                 final_content = content
                 if quoted_text_content:
                     final_content = f"{content}\n\n{quoted_text_content}".strip() if content else quoted_text_content
                 
                 sender_name = await self._resolve_sender_display_name(
                     message,
                     from_wxid,
                     sender_wxid,
                     is_group,
                 )
                 
                 # 尝试获取群名称
                 group_name = None
                 if is_group:
                     # 1. 优先从内存缓存获取
                     if from_wxid in self.contacts_cache:
                         g_info = self.contacts_cache[from_wxid]
                         group_name = g_info.get("nickname") or g_info.get("name")
                     
                     # 2. 如果缓存没有，尝试从数据库获取
                     if not group_name:
                         try:
                             group_info = get_contact_from_db(from_wxid)
                             if group_info:
                                 group_name = group_info.get("nickname") or group_info.get("remark")
                                 logger.debug(f"从数据库获取到群名: {group_name} ({from_wxid})")
                         except Exception as e:
                             logger.warning(f"从数据库查询群信息失败: {e}")

                 # 尝试获取发送者/群的 Alias (微信号)，如果存在，则使用 Alias 作为 OpenClaw 的会话 ID
                 # 这样 Dashboard 上就能显示微信号而不是 wxid
                 thread_alias = from_wxid
                 
                 # 只有私聊才尝试转 Alias，群聊 ID 通常是固定的而且没有 Alias
                 if not is_group:
                     # 1. 查缓存
                     if from_wxid in self.contacts_cache:
                         alias = self.contacts_cache[from_wxid].get("alias")
                         if alias:
                             thread_alias = alias
                             logger.debug(f"使用微信 Alias 作为会话 ID: {alias}")

                     # 2. 查库
                     if thread_alias == from_wxid:
                         try:
                             contact_info = get_contact_from_db(from_wxid)
                             if contact_info and contact_info.get("alias"):
                                 thread_alias = contact_info.get("alias")
                                 logger.debug(f"从数据库获取到 Alias: {thread_alias}")
                         except Exception:
                             pass

                 asyncio.create_task(
                     self.forward_to_openclaw(
                         sender_wxid,
                         final_content,
                         thread_alias,
                         is_group,
                         media_data,
                         sender_name,
                         group_name=group_name,
                         sender_id=sender_wxid,
                         sender_actual_name=sender_name,
                         mention_trigger_user=mention_trigger_user,
                         reply_to_wxid=from_wxid,
                     )
                 )
                 # 标记消息已被 OpenClaw 处理
                 message["_is_handled"] = True

    async def forward_to_openclaw(self, sender, content, thread_id, is_group, media_data=None, sender_name="User", group_name=None, sender_id=None, sender_actual_name=None, mention_trigger_user=False, reply_to_wxid=None):
        request_id = self._new_request_id()
        resolved_sender_id = sender_id or sender
        resolved_reply_to_wxid = reply_to_wxid or thread_id
        default_at_wxids = [resolved_sender_id] if is_group and mention_trigger_user and resolved_sender_id else []
        self._store_reply_context(request_id, {
            "to_wxid": resolved_reply_to_wxid,
            "is_group": is_group,
            "sender_wxid": resolved_sender_id,
            "mention_trigger_user": bool(mention_trigger_user),
            "default_at_wxids": default_at_wxids,
        })
        payload = {
            "from": thread_id, 
            "fromName": sender_name, 
            "content": content,
            "accountId": self.account_id or (self.bot.wxid if self.bot and hasattr(self.bot, 'wxid') else "default"),
            "requestId": request_id,
            "replyContext": {
                "mentionTriggerUser": bool(mention_trigger_user),
                "defaultAtWxids": default_at_wxids,
            },
        }
        current_config = getattr(self, "config", {})
        prompt_config = current_config.get("prompt", {}) if isinstance(current_config, dict) else {}
        if prompt_config.get("enabled", False):
            bridge_prompt = str(prompt_config.get("text", "")).strip()
            bridge_prompt_mode = str(prompt_config.get("mode", "body_for_agent")).strip() or "body_for_agent"
            if bridge_prompt:
                payload["bridgePrompt"] = bridge_prompt
                payload["bridgePromptMode"] = bridge_prompt_mode
                payload.setdefault("meta", {})
                payload["meta"]["bridgePrompt"] = bridge_prompt
                payload["meta"]["bridgePromptMode"] = bridge_prompt_mode
        if group_name:
            payload["groupName"] = group_name
        
        # 传递发送者信息
        if sender_id:
            payload["senderId"] = sender_id
        if sender_actual_name:
            payload["senderName"] = sender_actual_name

        payload["isGroup"] = is_group

        if media_data:
            try:
                media_payload = dict(media_data)
                media_url = media_payload.get("url")
                media_path = media_payload.get("path")
                m_path = media_payload.get("local_path") or media_path
                
                if media_url or (media_path and str(media_path).startswith("http")):
                    payload["media"] = media_payload
                    logger.debug(f"保留引用媒体 URL 转发给 OpenClaw: {media_payload.get('path') or media_url}")
                elif m_path and not str(m_path).startswith("http") and os.path.exists(m_path):
                    import base64
                    with open(m_path, "rb") as f:
                        b64_content = base64.b64encode(f.read()).decode("utf-8")
                    
                    # 构造完整的 base64 media 对象供 OpenClaw 消费
                    payload["media"] = {
                        "data": b64_content,
                        "name": media_payload.get("name", os.path.basename(m_path)),
                        "mime": media_payload.get("mime", "application/octet-stream")
                    }
                    logger.debug(f"已将本地媒体转换为 Base64 转发: {m_path}")
                else:
                    payload["media"] = media_payload
            except Exception as b64_err:
                logger.error(f"转发前转换 Base64 失败: {b64_err}")
                payload["media"] = media_data
        logger.debug(f"发送到 OpenClaw 的 Payload: {payload.get('from')} (Media: {'Yes' if media_data else 'No'})")
        send_started_at = time.time()
        ok = await self.send_ws_message({
            "direction": "bridge_to_openclaw",
            "event": "inbound_message",
            "payload": payload,
            "ts": int(time.time() * 1000),
        })
        if ok:
            self._remember_openclaw_request_timing(request_id, payload, send_started_at)
            logger.success(
                f"OpenClaw WS 发送成功 "
                f"(requestId: {request_id}, Content length: {len(content) or 'Media'}, "
                f"WS耗时: {(time.time() - send_started_at) * 1000:.1f}ms)"
            )
        else:
            logger.error("OpenClaw WS 发送失败: 当前连接不可用")



class _InMemoryRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


OpenClawBridge = OpenClawBridgePlugin
