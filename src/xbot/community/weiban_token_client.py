from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


class TokenGrantError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


def _grant_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TokenGrantError("weiban_unavailable", retryable=False)
    path = f"{parsed.path.rstrip('/')}/api/admin/token-grants"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _character_image_grant_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TokenGrantError("weiban_unavailable", retryable=False)
    path = f"{parsed.path.rstrip('/')}/api/admin/character-image-grants"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


async def grant_token_pack(
    *,
    invite_code: str,
    amount_tokens: int,
    idempotency_key: str,
    reason: str,
) -> dict[str, Any]:
    base_url = os.environ.get("WEIBAN_BASE_URL", "").strip()
    api_key = os.environ.get("WEIBAN_ADMIN_API_KEY", "")
    if not base_url or not api_key:
        raise TokenGrantError("weiban_unavailable", retryable=False)
    try:
        timeout = min(max(float(os.environ.get("WEIBAN_TIMEOUT_SECONDS", "15")), 1), 60)
    except (TypeError, ValueError):
        timeout = 15.0
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            response = await client.post(
                _grant_url(base_url),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Admin-Key": api_key,
                },
                json={
                    "identifier": invite_code,
                    "amount_tokens": int(amount_tokens),
                    "idempotency_key": idempotency_key,
                    "reason": reason,
                },
            )
    except httpx.ConnectError as exc:
        raise TokenGrantError("weiban_connect_failed", retryable=False) from exc
    except httpx.TimeoutException as exc:
        raise TokenGrantError("weiban_timeout", retryable=True) from exc
    except httpx.RequestError as exc:
        raise TokenGrantError("weiban_request_uncertain", retryable=True) from exc
    if response.status_code >= 500 or response.status_code in {408, 409, 425, 429}:
        raise TokenGrantError(f"weiban_http_{response.status_code}", retryable=True)
    if response.status_code >= 400:
        raise TokenGrantError(f"weiban_http_{response.status_code}", retryable=False)
    try:
        payload = response.json()
    except ValueError as exc:
        raise TokenGrantError("weiban_invalid_response", retryable=True) from exc
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise TokenGrantError("weiban_rejected", retryable=False)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if data.get("applied") is not True and data.get("replayed") is not True:
        raise TokenGrantError("weiban_rejected", retryable=False)
    return data


async def grant_character_image_count(
    *, invite_code: str, amount: int, idempotency_key: str, reason: str
) -> dict[str, Any]:
    base_url = os.environ.get("WEIBAN_BASE_URL", "").strip()
    api_key = os.environ.get("WEIBAN_ADMIN_API_KEY", "")
    if not base_url or not api_key or not 1 <= int(amount) <= 1_000_000:
        raise TokenGrantError("weiban_unavailable", retryable=False)
    try:
        timeout = min(max(float(os.environ.get("WEIBAN_TIMEOUT_SECONDS", "15")), 1), 60)
    except (TypeError, ValueError):
        timeout = 15.0
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            response = await client.post(
                _character_image_grant_url(base_url),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Admin-Key": api_key,
                },
                json={
                    "identifier": invite_code,
                    "amount": int(amount),
                    "idempotency_key": idempotency_key,
                    "reason": reason,
                },
            )
    except httpx.ConnectError as exc:
        raise TokenGrantError("weiban_connect_failed", retryable=False) from exc
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        raise TokenGrantError("weiban_request_uncertain", retryable=True) from exc
    if response.status_code >= 500 or response.status_code in {408, 425, 429}:
        raise TokenGrantError(f"weiban_http_{response.status_code}", retryable=True)
    if response.status_code >= 400:
        raise TokenGrantError(f"weiban_http_{response.status_code}", retryable=False)
    try:
        payload = response.json()
    except ValueError as exc:
        raise TokenGrantError("weiban_invalid_response", retryable=True) from exc
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise TokenGrantError("weiban_rejected", retryable=False)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if data.get("applied") is not True and data.get("replayed") is not True:
        raise TokenGrantError("weiban_rejected", retryable=False)
    return data
