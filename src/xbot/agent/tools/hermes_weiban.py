"""Read-only Weiban account lookup tool for the embedded Hermes runtime."""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_TOOLSET = "weiban-readonly"
_EMAIL_MAX_LENGTH = 254
_INVITE_CODE_LENGTH = 8
_RESPONSE_MAX_BYTES = 1_048_576
_DEFAULT_TIMEOUT_SECONDS = 15.0
_MAX_TIMEOUT_SECONDS = 60.0
_EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$",
    re.IGNORECASE,
)
_INVITE_CODE_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
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


def _invite_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    invite_code = value.strip().upper()
    if not _INVITE_CODE_PATTERN.fullmatch(invite_code):
        return None
    return invite_code


def _comparison_email(value: object) -> str:
    return str(value or "").strip().casefold()


def _comparison_invite_code(value: object) -> str:
    return str(value or "").strip().upper()


def _has_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


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


def _query_url(base_url: str, query_value: str) -> str:
    path = f"{urlsplit(base_url).path.rstrip('/')}/api/admin/users"
    query = urlencode({"q": query_value})
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _wallet_url(base_url: str, user_id: object) -> str | None:
    normalized_id = str(user_id or "").strip()
    if not normalized_id or len(normalized_id) > 128:
        return None
    parsed = urlsplit(base_url)
    path = (
        f"{parsed.path.rstrip('/')}/api/admin/users/"
        f"{quote(normalized_id, safe='')}/token-wallet"
    )
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


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
    window: dict[str, object] = {
        "usage": usage,
        "limit": limit,
        "remaining": remaining,
        "percent": percent,
        "unlimited": unlimited,
    }
    reset_names = {
        "five_hour_token_usage": ("five_hour_recovery_at",),
        "weekly_token_usage": ("weekly_reset_at",),
        "monthly_token_usage": ("monthly_reset_at",),
    }.get(usage_names[0], ())
    if any(name in record for name in reset_names):
        window["reset_at"] = _text(_first_value(record, reset_names))
        window["reset_known"] = True
    return window


def _wallet(record: object) -> dict[str, object] | None:
    if not isinstance(record, dict):
        return None
    used = _number(record.get("used_tokens"))
    total = _number(record.get("total_tokens"))
    available = _number(record.get("available_tokens"))
    if total is None and used is not None and available is not None:
        total = _display_number(used + available)
    if used is None and total is not None and available is not None:
        used = _display_number(max(total - available, 0))
    if available is None and total is not None and used is not None:
        available = _display_number(max(total - used, 0))
    if used is None and total is None and available is None:
        return None
    percent = None
    if used is not None and total is not None:
        percent = _display_number(round((used / total) * 100, 2)) if total else 0
    return {
        "usage": used,
        "limit": total,
        "remaining": available,
        "percent": percent,
        "unlimited": False,
    }


def _account(
    record: dict[str, Any],
    *,
    include_email: bool = True,
    token_wallet: dict[str, object] | None = None,
    quota: dict[str, Any] | None = None,
) -> dict[str, object]:
    quota_record = {**record, **quota} if quota else record
    account: dict[str, object] = {
        "is_active": _boolean(record.get("is_active")),
        "plan_code": _text(record.get("plan_code")),
        "plan_expires_at": _text(record.get("plan_expires_at")),
        "token_usage": {
            window: _window(quota_record, usage_names, limit_names)
            for window, (usage_names, limit_names) in _TOKEN_WINDOWS.items()
        },
        "token_wallet": token_wallet,
        "wechat_status": _text(record.get("wechat_status")),
        "wechat_enabled": _boolean(record.get("wechat_enabled")),
        "wechat_listening": _boolean(record.get("wechat_listening")),
        "character_image": {
            "limit": _number(record.get("character_image_limit")),
            "used": _number(record.get("character_image_used")),
            "remaining": _number(record.get("character_image_remaining")),
            "period": _text(record.get("character_image_period")),
        },
    }
    if include_email:
        account = {"email": _text(record.get("email")), **account}
    return account


class _NoRedirect(HTTPRedirectHandler):
    """Treat every redirect as an error so the admin key never leaves the base URL."""

    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


def _open(request: Request, timeout: float):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def _request_json(request: Request) -> object | None:
    try:
        with _open(request, _timeout_seconds()) as response:
            body = response.read(_RESPONSE_MAX_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError):
        return None
    if len(body) > _RESPONSE_MAX_BYTES:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def query_account(args: dict[str, Any], **_: Any) -> str:
    """Look up exactly one Weiban account using its email or permanent invite code."""
    if not isinstance(args, dict) or set(args) - {"email", "invite_code"}:
        return _error("invalid_request", "账号查询只接受邮箱或邀请码参数。")
    has_email = "email" in args and _has_value(args.get("email"))
    has_invite_code = "invite_code" in args and _has_value(args.get("invite_code"))
    if has_email == has_invite_code:
        return _error("invalid_request", "邮箱和邀请码必须二选一。")

    if has_email:
        query_value = _email(args.get("email"))
        if query_value is None:
            return _error("invalid_email", "请输入有效邮箱地址。")
        match_field = "email"
        comparison = _comparison_email
        not_found_message = "未找到该邮箱对应的账号。"
    else:
        query_value = _invite_code(args.get("invite_code"))
        if query_value is None:
            return _error("invalid_invite_code", "请输入有效的 8 位永久邀请码。")
        match_field = "invite_code"
        comparison = _comparison_invite_code
        not_found_message = "未找到该邀请码对应的账号。"

    base_url = _base_url()
    api_key = os.environ.get("WEIBAN_ADMIN_API_KEY", "")
    if not base_url or not api_key:
        return _error("weiban_unavailable", "账号查询暂不可用，请稍后再试。")

    request = Request(
        _query_url(base_url, query_value),
        headers={"Accept": "application/json", "X-Admin-Key": api_key},
        method="GET",
    )
    payload = _request_json(request)
    if payload is None:
        return _error("weiban_query_failed", "账号查询暂时失败，请稍后再试。")

    items = _items_from_payload(payload)
    if items is None:
        return _error("weiban_query_failed", "账号查询暂时失败，请稍后再试。")
    expected = comparison(query_value)
    matches = [item for item in items if comparison(item.get(match_field)) == expected]
    if not matches:
        return _error("account_not_found", not_found_message)
    if len(matches) != 1:
        return _error("account_ambiguous", "找到多个匹配账号，请联系管理员处理。")
    record = matches[0]
    wallet = _wallet(record.get("token_wallet"))
    wallet_url = _wallet_url(base_url, record.get("id"))
    if wallet is None and wallet_url is not None:
        wallet_payload = _request_json(
            Request(
                wallet_url,
                headers={"Accept": "application/json", "X-Admin-Key": api_key},
                method="GET",
            )
        )
        if isinstance(wallet_payload, dict) and isinstance(wallet_payload.get("data"), dict):
            wallet_payload = wallet_payload["data"]
        wallet = _wallet(wallet_payload)
    return json.dumps(
        {
            "success": True,
            "account": _account(
                record,
                include_email=has_email,
                token_wallet=wallet,
                quota=record,
            ),
        },
        ensure_ascii=False,
    )


def grant_character_images(args: dict[str, Any], **_: Any) -> str:
    """Grant manual character-image count after an explicit admin confirmation."""
    allowed = {"identifier", "amount", "idempotency_key", "reason", "confirmed"}
    if not isinstance(args, dict) or set(args) - allowed or args.get("confirmed") is not True:
        return _error("confirmation_required", "请先展示用户、增加次数和原因，并获得管理员明确确认。")
    identifier = str(args.get("identifier") or "").strip()
    idempotency_key = str(args.get("idempotency_key") or "").strip()
    reason = str(args.get("reason") or "").strip()
    try:
        amount = int(args.get("amount"))
    except (TypeError, ValueError):
        amount = 0
    if not identifier or not idempotency_key or not reason or not 1 <= amount <= 1_000_000:
        return _error("invalid_request", "用户、次数、唯一幂等键和原因均为必填，次数范围为 1～1000000。")
    base_url = _base_url()
    api_key = os.environ.get("WEIBAN_ADMIN_API_KEY", "")
    if not base_url or not api_key:
        return _error("weiban_unavailable", "手动生图额度发放暂不可用，请稍后再试。")
    query_request = Request(
        _query_url(base_url, identifier),
        headers={"Accept": "application/json", "X-Admin-Key": api_key},
        method="GET",
    )
    items = _items_from_payload(_request_json(query_request))
    if items is None:
        return _error("weiban_query_failed", "用户查询失败，未执行发放。")
    normalized = identifier.casefold()
    matches = [
        item
        for item in items
        if normalized
        in {
            str(item.get("id") or "").strip().casefold(),
            str(item.get("email") or "").strip().casefold(),
            str(item.get("invite_code") or "").strip().casefold(),
        }
    ]
    if len(matches) != 1:
        code = "account_not_found" if not matches else "account_ambiguous"
        return _error(code, "用户不存在或标识不唯一，未执行发放。")
    record = matches[0]
    payload = json.dumps(
        {
            "amount": amount,
            "idempotency_key": idempotency_key,
            "reason": reason,
        }
    ).encode("utf-8")
    parsed = urlsplit(base_url)
    url = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{parsed.path.rstrip('/')}/api/admin/users/{quote(str(record.get('id')), safe='')}/character-image-grants",
            "",
            "",
        )
    )
    try:
        response = _open(
            Request(
                url,
                data=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Admin-Key": api_key,
                },
                method="POST",
            ),
            _timeout_seconds(),
        )
        with response:
            body = response.read(_RESPONSE_MAX_BYTES + 1)
        result = json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        messages = {403: "管理员认证失败。", 404: "用户不存在。", 409: "幂等键冲突或用户标识不明确，禁止更换幂等键重试。"}
        return _error(f"weiban_http_{exc.code}", messages.get(exc.code, "手动生图额度发放失败。"))
    except (URLError, OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        return _error("weiban_grant_uncertain", "发放结果暂时无法确认，请使用原幂等键核对，禁止生成新键重试。")
    data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
    if not isinstance(data, dict) or (data.get("applied") is not True and data.get("replayed") is not True):
        return _error("weiban_rejected", "手动生图额度未确认增加。")
    return json.dumps(
        {
            "success": True,
            "user": {
                "id": record.get("id"),
                "email": _text(record.get("email")),
                "invite_code": _text(record.get("invite_code")),
            },
            "amount": amount,
            "applied": data.get("applied") is True,
            "replayed": data.get("replayed") is True,
            "before": data.get("before"),
            "after": data.get("after"),
        },
        ensure_ascii=False,
    )


def register_xbot_weiban_tools() -> None:
    """Register the read-only account lookup under its own toolset."""
    from tools.registry import registry

    schema = {
        "name": "weiban_query_account",
        "description": (
            "Read one Weiban account's plan and token usage by exact email or permanent invite "
            "code match. Provide exactly one lookup field."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": (
                        "The account email address to look up. Omit this field entirely when "
                        "querying by invite code."
                    ),
                    "maxLength": _EMAIL_MAX_LENGTH,
                },
                "invite_code": {
                    "type": "string",
                    "description": (
                        "The account's 8-character permanent invite code. Omit this field "
                        "entirely when querying by email."
                    ),
                    "minLength": _INVITE_CODE_LENGTH,
                    "maxLength": _INVITE_CODE_LENGTH,
                },
            },
            "oneOf": [{"required": ["email"]}, {"required": ["invite_code"]}],
            "additionalProperties": False,
        },
    }
    existing = registry.get_entry("weiban_query_account")
    if not (existing is not None and existing.handler is query_account and existing.toolset == _TOOLSET):
        registry.register(
            name="weiban_query_account",
            toolset=_TOOLSET,
            schema=schema,
            handler=query_account,
            description=schema["description"],
            override=existing is not None,
        )
    grant_schema = {
        "name": "weiban_grant_character_images",
        "description": "Admin-only: add manual character-image count after exact user lookup and explicit confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string"},
                "amount": {"type": "integer", "minimum": 1, "maximum": 1000000},
                "idempotency_key": {"type": "string"},
                "reason": {"type": "string"},
                "confirmed": {"type": "boolean", "const": True},
            },
            "required": ["identifier", "amount", "idempotency_key", "reason", "confirmed"],
            "additionalProperties": False,
        },
    }
    existing_grant = registry.get_entry("weiban_grant_character_images")
    registry.register(
        name="weiban_grant_character_images",
        toolset="weiban-admin",
        schema=grant_schema,
        handler=grant_character_images,
        description=grant_schema["description"],
        override=existing_grant is not None,
    )
