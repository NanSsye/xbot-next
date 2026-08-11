"""Read-only Weiban account lookup tool for the embedded Hermes runtime."""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_TOOLSET = "weiban-readonly"
_EMAIL_MAX_LENGTH = 254
_RESPONSE_MAX_BYTES = 1_048_576
_DEFAULT_TIMEOUT_SECONDS = 15.0
_MAX_TIMEOUT_SECONDS = 60.0
_EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$",
    re.IGNORECASE,
)
_TOKEN_WINDOWS = {
    "five_hour": (
        ("five_hour_token_usage", "five_hour_usage"),
        ("five_hour_token_limit", "five_hour_limit", "five_hour_token_quota"),
    ),
    "weekly": (
        ("weekly_token_usage", "weekly_usage"),
        ("weekly_token_limit", "weekly_limit", "weekly_token_quota"),
    ),
    "monthly": (
        ("monthly_token_usage", "monthly_usage"),
        ("monthly_token_limit", "monthly_limit", "monthly_token_quota"),
    ),
}


def _error(code: str, message: str) -> str:
    return json.dumps({"success": False, "error": code, "message": message}, ensure_ascii=False)


def _email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip()
    if not email or len(email) > _EMAIL_MAX_LENGTH or not _EMAIL_PATTERN.fullmatch(email):
        return None
    return email


def _comparison_email(value: object) -> str:
    return str(value or "").strip().casefold()


def _base_url() -> str | None:
    raw_value = os.environ.get("WEIBAN_BASE_URL", "").strip()
    parsed = urlsplit(raw_value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _timeout_seconds() -> float:
    try:
        timeout = float(os.environ.get("WEIBAN_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(timeout) or timeout <= 0:
        return _DEFAULT_TIMEOUT_SECONDS
    return min(timeout, _MAX_TIMEOUT_SECONDS)


def _query_url(base_url: str, email: str) -> str:
    path = f"{urlsplit(base_url).path.rstrip('/')}/api/admin/users"
    query = urlencode({"q": email})
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _items_from_payload(payload: object) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return None
    for key in ("items", "users", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return None


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if number.is_integer() else number


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    return None


def _text(value: object, *, max_length: int = 256) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] if text else None


def _first_value(record: dict[str, Any], names: tuple[str, ...]) -> object:
    for name in names:
        if name in record:
            return record[name]
    return None


def _display_number(value: int | float) -> int | float:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _window(record: dict[str, Any], usage_names: tuple[str, ...], limit_names: tuple[str, ...]) -> dict[str, object]:
    usage = _number(_first_value(record, usage_names))
    limit = _number(_first_value(record, limit_names))
    unlimited = limit == 0
    remaining: int | float | None = None
    percent: int | float | None = None
    if not unlimited and usage is not None and limit is not None:
        remaining = _display_number(max(limit - usage, 0))
        percent = _display_number(round((usage / limit) * 100, 2)) if limit else None
    return {
        "usage": usage,
        "limit": limit,
        "remaining": remaining,
        "percent": percent,
        "unlimited": unlimited,
    }


def _account(record: dict[str, Any]) -> dict[str, object]:
    return {
        "email": _text(record.get("email")),
        "is_active": _boolean(record.get("is_active")),
        "plan_code": _text(record.get("plan_code")),
        "plan_expires_at": _text(record.get("plan_expires_at")),
        "token_usage": {
            window: _window(record, usage_names, limit_names)
            for window, (usage_names, limit_names) in _TOKEN_WINDOWS.items()
        },
        "wechat_status": _text(record.get("wechat_status")),
        "wechat_enabled": _boolean(record.get("wechat_enabled")),
        "wechat_listening": _boolean(record.get("wechat_listening")),
    }


class _NoRedirect(HTTPRedirectHandler):
    """Treat every redirect as an error so the admin key never leaves the base URL."""

    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


def _open(request: Request, timeout: float):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def query_account(args: dict[str, Any], **_: Any) -> str:
    """Look up exactly one Weiban account using its email address."""
    if not isinstance(args, dict) or set(args) - {"email"}:
        return _error("invalid_request", "账号查询只接受邮箱参数。")
    email = _email(args.get("email"))
    if email is None:
        return _error("invalid_email", "请输入有效邮箱地址。")

    base_url = _base_url()
    api_key = os.environ.get("WEIBAN_ADMIN_API_KEY", "")
    if not base_url or not api_key:
        return _error("weiban_unavailable", "账号查询暂不可用，请稍后再试。")

    request = Request(
        _query_url(base_url, email),
        headers={"Accept": "application/json", "X-Admin-Key": api_key},
        method="GET",
    )
    try:
        with _open(request, _timeout_seconds()) as response:
            body = response.read(_RESPONSE_MAX_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError):
        return _error("weiban_query_failed", "账号查询暂时失败，请稍后再试。")
    if len(body) > _RESPONSE_MAX_BYTES:
        return _error("weiban_query_failed", "账号查询暂时失败，请稍后再试。")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("weiban_query_failed", "账号查询暂时失败，请稍后再试。")

    items = _items_from_payload(payload)
    if items is None:
        return _error("weiban_query_failed", "账号查询暂时失败，请稍后再试。")
    matches = [item for item in items if _comparison_email(item.get("email")) == email.casefold()]
    if not matches:
        return _error("account_not_found", "未找到该邮箱对应的账号。")
    if len(matches) != 1:
        return _error("account_ambiguous", "找到多个匹配账号，请联系管理员处理。")
    return json.dumps({"success": True, "account": _account(matches[0])}, ensure_ascii=False)


def register_xbot_weiban_tools() -> None:
    """Register the read-only account lookup under its own toolset."""
    from tools.registry import registry

    schema = {
        "name": "weiban_query_account",
        "description": "Read one Weiban account's plan and token usage by exact email match.",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "The account email address to look up.",
                    "maxLength": _EMAIL_MAX_LENGTH,
                }
            },
            "required": ["email"],
            "additionalProperties": False,
        },
    }
    existing = registry.get_entry("weiban_query_account")
    if existing is not None and existing.handler is query_account and existing.toolset == _TOOLSET:
        return
    registry.register(
        name="weiban_query_account",
        toolset=_TOOLSET,
        schema=schema,
        handler=query_account,
        description=schema["description"],
        override=existing is not None,
    )
