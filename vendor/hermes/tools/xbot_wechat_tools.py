"""xbot-native WeChat send tools for embedded Hermes sessions."""

from __future__ import annotations

import asyncio
import contextvars
import json
from typing import Any, Callable
from xml.sax.saxutils import escape as xml_escape


_SEND_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xbot_wechat_send_context", default=None
)


def set_send_context(context: dict[str, Any]):
    return _SEND_CONTEXT.set(context)


def reset_send_context(token) -> None:
    _SEND_CONTEXT.reset(token)


def _send(kind: str, args: dict[str, Any], *, content: str | None = None, metadata: dict | None = None) -> str:
    context = _SEND_CONTEXT.get()
    if not context:
        return json.dumps({"error": "WeChat send context is unavailable."})

    content_key = "text" if kind == "text" else "path"
    content = str(content if content is not None else args.get(content_key) or "").strip()
    if not content:
        return json.dumps({"error": f"{content_key} is required."})

    target = str(args.get("to_wxid") or context.get("conversation_id") or "").strip()
    if not target:
        return json.dumps({"error": "to_wxid is required outside a WeChat conversation."})

    sender: Callable[..., Any] = context["sender"]
    future = asyncio.run_coroutine_threadsafe(
        sender(
            platform="wechat",
            adapter=context["adapter"],
            conversation_id=target,
            message_type=kind,
            content=content,
            metadata=metadata or {},
        ),
        context["loop"],
    )
    future.result(timeout=120)
    return json.dumps(
        {"success": True, "adapter": context["adapter"], "to_wxid": target, "type": kind},
        ensure_ascii=False,
    )


def send_text(args: dict[str, Any], **_: Any) -> str:
    return _send("text", args)


def send_image(args: dict[str, Any], **_: Any) -> str:
    return _send("image", args)


def send_file(args: dict[str, Any], **_: Any) -> str:
    return _send("file", args)


def send_voice(args: dict[str, Any], **_: Any) -> str:
    return _send("voice", args, metadata={
        "format": str(args.get("format") or "wav"),
        "seconds": int(args.get("seconds") or 0),
    })


def send_video(args: dict[str, Any], **_: Any) -> str:
    return _send("video", args)


def _link_xml(args: dict[str, Any]) -> str:
    return (
        "<appmsg appid='' sdkver='0'>"
        f"<title>{xml_escape(str(args.get('title') or ''))}</title>"
        f"<des>{xml_escape(str(args.get('desc') or ''))}</des>"
        f"<url>{xml_escape(str(args.get('url') or ''))}</url>"
        f"<thumburl>{xml_escape(str(args.get('thumb_url') or ''))}</thumburl>"
        "<type>5</type></appmsg>"
    )


def send_link(args: dict[str, Any], **_: Any) -> str:
    url = str(args.get("url") or "").strip()
    return _send("link", args, content=url, metadata={"content_xml": _link_xml(args), "content_type": 5})


def _music_xml(args: dict[str, Any]) -> str:
    title = xml_escape(str(args.get("title") or ""))
    singer = xml_escape(str(args.get("singer") or ""))
    url = xml_escape(str(args.get("url") or ""))
    music_url = xml_escape(str(args.get("music_url") or ""))
    cover = xml_escape(str(args.get("cover_url") or ""))
    lyric = xml_escape(str(args.get("lyric") or ""))
    return (
        '<appmsg appid="wx79f2c4418704b4f8" sdkver="0">'
        f"<title>{title}</title><des>{singer}</des><action>view</action><type>3</type><showtype>0</showtype>"
        f"<content/><url>{url}</url><dataurl>{music_url}</dataurl><lowurl>{url}</lowurl>"
        f"<lowdataurl>{music_url}</lowdataurl><thumburl>{cover}</thumburl><songlyric>{lyric}</songlyric>"
        f"<songalbumurl>{cover}</songalbumurl><appattach><totallen>0</totallen><attachid/>"
        f"<emoticonmd5/><fileext/><cdnthumburl>{cover}</cdnthumburl><cdnthumbheight>100</cdnthumbheight>"
        "<cdnthumbwidth>100</cdnthumbwidth></appattach><weappinfo><pagepath/><username/><appid/>"
        "<appservicetype>0</appservicetype></weappinfo><websearch/></appmsg><fromusername></fromusername><scene>0</scene>"
    )


def send_music_card(args: dict[str, Any], **_: Any) -> str:
    music_url = str(args.get("music_url") or "").strip()
    return _send(
        "music_card", args, content=music_url,
        metadata={"content_xml": _music_xml(args), "content_type": 3},
    )


def _schema(name: str, kind: str) -> dict[str, Any]:
    content_key = "text" if kind == "text" else "path"
    return {
        "name": name,
        "description": f"Send a WeChat {kind} through xbot's current WeChat adapter.",
        "parameters": {
            "type": "object",
            "properties": {
                "to_wxid": {
                    "type": "string",
                    "description": "Optional recipient wxid or group id; defaults to the current conversation.",
                },
                content_key: {
                    "type": "string",
                    "description": "Message text." if kind == "text" else f"Local {kind} path.",
                },
            },
            "required": [content_key],
        },
    }


from tools.registry import registry

registry.register(
    name="wechat_send_text",
    toolset="wechat",
    schema=_schema("wechat_send_text", "text"),
    handler=send_text,
    description="Send WeChat text through the current xbot adapter.",
)
registry.register(
    name="wechat_send_image",
    toolset="wechat",
    schema=_schema("wechat_send_image", "image"),
    handler=send_image,
    description="Send a WeChat image through the current xbot adapter.",
)
registry.register(
    name="wechat_send_file",
    toolset="wechat",
    schema=_schema("wechat_send_file", "file"),
    handler=send_file,
    description="Send a WeChat file through the current xbot adapter.",
)
registry.register(
    name="wechat_send_voice", toolset="wechat",
    schema={"name": "wechat_send_voice", "description": "Send a WeChat voice message.", "parameters": {
        "type": "object", "properties": {
            "to_wxid": {"type": "string"}, "path": {"type": "string"},
            "format": {"type": "string", "enum": ["amr", "wav", "mp3"]},
            "seconds": {"type": "integer", "minimum": 0}}, "required": ["path"]}},
    handler=send_voice, description="Send a WeChat voice message through xbot.",
)
registry.register(
    name="wechat_send_video", toolset="wechat", schema=_schema("wechat_send_video", "video"),
    handler=send_video, description="Send a WeChat video through xbot.",
)
registry.register(
    name="wechat_send_link", toolset="wechat",
    schema={"name": "wechat_send_link", "description": "Send a WeChat link card.", "parameters": {
        "type": "object", "properties": {
            "to_wxid": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"},
            "desc": {"type": "string"}, "thumb_url": {"type": "string"}}, "required": ["url"]}},
    handler=send_link, description="Send a WeChat link card through xbot.",
)
registry.register(
    name="wechat_send_music_card", toolset="wechat",
    schema={"name": "wechat_send_music_card", "description": "Send a WeChat music card.", "parameters": {
        "type": "object", "properties": {
            "to_wxid": {"type": "string"}, "title": {"type": "string"}, "singer": {"type": "string"},
            "url": {"type": "string"}, "music_url": {"type": "string"}, "cover_url": {"type": "string"},
            "lyric": {"type": "string"}}, "required": ["title", "music_url"]}},
    handler=send_music_card, description="Send a WeChat music card through xbot.",
)
