from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from xbot.agent.runtime import AgentRuntime
from xbot.agent.tools import hermes_weiban
from xbot.core.config import AgentConfig


class _Response:
    def __init__(self, body: object) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self, size: int | None = None) -> bytes:
        return self.body if size is None else self.body[:size]


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("WEIBAN_BASE_URL", "https://weiban.example.test/base")
    monkeypatch.setenv("WEIBAN_ADMIN_API_KEY", "test-admin-key")


def _record(email: str = "case@example.com", invite_code: str = "AB12CD34") -> dict[str, object]:
    return {
        "id": "internal-user-id",
        "email": f"  {email}  ",
        "invite_code": f"  {invite_code}  ",
        "username": "  lemon  ",
        "is_active": "true",
        "plan_code": " pro ",
        "plan_expires_at": " 2026-12-31T00:00:00Z ",
        "five_hour_token_usage": "2",
        "five_hour_token_limit": 10,
        "weekly_token_usage": 5,
        "weekly_token_limit": 0,
        "monthly_token_usage": 75,
        "monthly_token_limit": 100,
        "five_hour_recovery_at": "2026-08-11T12:00:00Z",
        "weekly_reset_at": "2026-08-16T16:00:00Z",
        "monthly_reset_at": "2026-08-31T16:00:00Z",
        "token_wallet": {
            "available_tokens": 80,
            "used_tokens": 20,
            "total_tokens": 100,
            "reserved_tokens": 0,
        },
        "wechat_status": " listening ",
        "wechat_enabled": "1",
        "wechat_listening": 0,
        "character_image_limit": 12,
        "character_image_used": 3,
        "character_image_remaining": 9,
        "character_image_period": "lifetime",
        "unrelated_secret": "must-not-leak",
    }


def test_weiban_query_account_reads_wallet_and_returns_minimal_normalized_fields(monkeypatch):
    _configure(monkeypatch)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response({"items": [_record("Case@Example.com")]})

    monkeypatch.setattr(hermes_weiban, "_open", fake_urlopen)

    result = json.loads(hermes_weiban.query_account({"email": "case@example.com"}))

    assert result == {
        "success": True,
        "account": {
            "email": "Case@Example.com",
            "is_active": True,
            "plan_code": "pro",
            "plan_expires_at": "2026-12-31T00:00:00Z",
            "token_usage": {
                "five_hour": {
                    "usage": 2,
                    "limit": 10,
                    "remaining": 8,
                    "percent": 20,
                    "unlimited": False,
                    "reset_at": "2026-08-11T12:00:00Z",
                    "reset_known": True,
                },
                "weekly": {
                    "usage": 5,
                    "limit": 0,
                    "remaining": None,
                    "percent": None,
                    "unlimited": True,
                    "reset_at": "2026-08-16T16:00:00Z",
                    "reset_known": True,
                },
                "monthly": {
                    "usage": 75,
                    "limit": 100,
                    "remaining": 25,
                    "percent": 75,
                    "unlimited": False,
                    "reset_at": "2026-08-31T16:00:00Z",
                    "reset_known": True,
                },
            },
            "token_wallet": {
                "usage": 20,
                "limit": 100,
                "remaining": 80,
                "percent": 20,
                "unlimited": False,
            },
            "wechat_status": "listening",
            "wechat_enabled": True,
            "wechat_listening": False,
            "character_image": {
                "limit": 12,
                "used": 3,
                "remaining": 9,
                "period": "lifetime",
            },
        },
    }
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.get_method() == "GET"
    assert request.data is None
    parsed = urlsplit(request.full_url)
    assert parsed.path == "/base/api/admin/users"
    assert parse_qs(parsed.query) == {"q": ["case@example.com"]}
    assert timeout == 15.0
    assert "internal-user-id" not in json.dumps(result)
    assert "must-not-leak" not in json.dumps(result)
    assert "test-admin-key" not in json.dumps(result)
    assert "lemon" not in json.dumps(result)


@pytest.mark.parametrize("container_key", [None, "items", "users", "data"])
def test_weiban_query_account_accepts_supported_response_containers(monkeypatch, container_key):
    _configure(monkeypatch)
    records = [_record()]
    payload: object = records if container_key is None else {container_key: records}
    monkeypatch.setattr(hermes_weiban, "_open", lambda request, timeout: _Response(payload))

    result = json.loads(hermes_weiban.query_account({"email": "case@example.com"}))

    assert result["success"] is True
    assert result["account"]["email"] == "case@example.com"


def test_weiban_query_account_requires_exact_unique_email_match(monkeypatch):
    _configure(monkeypatch)
    payloads = iter(
        [
            {"users": [_record("not-case@example.com")]},
            {"data": [_record(" CASE@example.com "), _record("case@example.com")]},
        ]
    )
    monkeypatch.setattr(hermes_weiban, "_open", lambda request, timeout: _Response(next(payloads)))

    not_found = json.loads(hermes_weiban.query_account({"email": "case@example.com"}))
    ambiguous = json.loads(hermes_weiban.query_account({"email": "case@example.com"}))

    assert not_found == {
        "success": False,
        "error": "account_not_found",
        "message": "未找到该邮箱对应的账号。",
    }
    assert ambiguous == {
        "success": False,
        "error": "account_ambiguous",
        "message": "找到多个匹配账号，请联系管理员处理。",
    }


def test_weiban_query_account_accepts_invite_code_without_exposing_identity(monkeypatch):
    _configure(monkeypatch)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response({"items": [_record(invite_code="AB12CD34")]})

    monkeypatch.setattr(hermes_weiban, "_open", fake_urlopen)

    result = json.loads(
        hermes_weiban.query_account({"email": "", "invite_code": " ab12cd34 "})
    )

    assert result["success"] is True
    assert set(result["account"]) == {
        "is_active",
        "plan_code",
        "plan_expires_at",
        "token_usage",
        "token_wallet",
        "wechat_status",
        "wechat_enabled",
        "wechat_listening",
        "character_image",
    }
    assert parse_qs(urlsplit(requests[0].full_url).query) == {"q": ["AB12CD34"]}
    serialized = json.dumps(result)
    for private_value in (
        "case@example.com",
        "internal-user-id",
        "AB12CD34",
        "lemon",
        "must-not-leak",
    ):
        assert private_value not in serialized


def test_weiban_query_account_keeps_account_when_wallet_is_unavailable(monkeypatch):
    _configure(monkeypatch)

    def fake_urlopen(request, timeout):
        if urlsplit(request.full_url).path.endswith("/token-wallet"):
            raise URLError("wallet unavailable")
        record = _record()
        record.pop("token_wallet")
        return _Response([record])

    monkeypatch.setattr(hermes_weiban, "_open", fake_urlopen)

    result = json.loads(hermes_weiban.query_account({"invite_code": "AB12CD34"}))

    assert result["success"] is True
    assert result["account"]["token_wallet"] is None


def test_weiban_query_account_requires_exact_unique_invite_code_match(monkeypatch):
    _configure(monkeypatch)
    payloads = iter(
        [
            {"users": [_record(invite_code="ZZ99ZZ99")]},
            {"data": [_record(invite_code="AB12CD34"), _record(invite_code="ab12cd34")]},
        ]
    )
    monkeypatch.setattr(hermes_weiban, "_open", lambda request, timeout: _Response(next(payloads)))

    not_found = json.loads(hermes_weiban.query_account({"invite_code": "AB12CD34"}))
    ambiguous = json.loads(hermes_weiban.query_account({"invite_code": "AB12CD34"}))

    assert not_found["error"] == "account_not_found"
    assert not_found["message"] == "未找到该邀请码对应的账号。"
    assert ambiguous["error"] == "account_ambiguous"


def test_weiban_query_account_rejects_invalid_or_extra_input_without_request(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        hermes_weiban,
        "_open",
        lambda request, timeout: pytest.fail("invalid input must not make an HTTP request"),
    )

    malformed = json.loads(hermes_weiban.query_account({"email": "not-an-email"}))
    extra = json.loads(
        hermes_weiban.query_account({"email": "case@example.com", "url": "https://other.example"})
    )
    malformed_invite_code = json.loads(hermes_weiban.query_account({"invite_code": "ABC-123"}))
    neither = json.loads(hermes_weiban.query_account({}))
    both = json.loads(
        hermes_weiban.query_account(
            {"email": "case@example.com", "invite_code": "AB12CD34"}
        )
    )

    assert malformed["error"] == "invalid_email"
    assert malformed_invite_code["error"] == "invalid_invite_code"
    assert extra["error"] == "invalid_request"
    assert neither["error"] == "invalid_request"
    assert both["error"] == "invalid_request"


def test_weiban_query_account_config_error_never_exposes_secret_or_url(monkeypatch):
    monkeypatch.delenv("WEIBAN_BASE_URL", raising=False)
    monkeypatch.setenv("WEIBAN_ADMIN_API_KEY", "config-secret")
    monkeypatch.setattr(
        hermes_weiban,
        "_open",
        lambda request, timeout: pytest.fail("invalid configuration must not make an HTTP request"),
    )

    result = hermes_weiban.query_account({"email": "case@example.com"})

    assert json.loads(result)["error"] == "weiban_unavailable"
    assert "config-secret" not in result
    assert "WEIBAN_BASE_URL" not in result


@pytest.mark.parametrize(
    "fake_open",
    [
        lambda request, timeout: (_ for _ in ()).throw(
            HTTPError(
                "https://internal.example.test/api/admin/users?key=http-secret",
                500,
                "http-secret",
                hdrs=None,
                fp=None,
            )
        ),
        lambda request, timeout: (_ for _ in ()).throw(URLError("http-secret")),
        lambda request, timeout: (_ for _ in ()).throw(TimeoutError("http-secret")),
        lambda request, timeout: _Response(b"not-json"),
    ],
)
def test_weiban_query_account_transport_and_json_errors_are_stable_and_private(monkeypatch, fake_open):
    _configure(monkeypatch)
    monkeypatch.setattr(hermes_weiban, "_open", fake_open)

    result = hermes_weiban.query_account({"email": "case@example.com"})

    assert json.loads(result) == {
        "success": False,
        "error": "weiban_query_failed",
        "message": "账号查询暂时失败，请稍后再试。",
    }
    assert "http-secret" not in result
    assert "internal.example.test" not in result
    assert "test-admin-key" not in result


def test_weiban_query_account_rejects_oversized_response_without_leaking_data(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        hermes_weiban,
        "_open",
        lambda request, timeout: _Response(b"x" * (hermes_weiban._RESPONSE_MAX_BYTES + 1)),
    )

    result = hermes_weiban.query_account({"email": "case@example.com"})

    assert json.loads(result) == {
        "success": False,
        "error": "weiban_query_failed",
        "message": "账号查询暂时失败，请稍后再试。",
    }


def test_weiban_query_account_disables_redirects_before_sending_admin_key():
    handler = hermes_weiban._NoRedirect()
    request = hermes_weiban.Request("https://weiban.example.test/api/admin/users?q=case@example.com")

    assert handler.redirect_request(request, None, 302, "Found", {}, "https://other.example.test") is None


def test_grant_character_images_requires_confirmation_without_http(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        hermes_weiban,
        "_open",
        lambda request, timeout: pytest.fail("unconfirmed grant must not make an HTTP request"),
    )

    result = json.loads(
        hermes_weiban.grant_character_images(
            {
                "identifier": "AB12CD34",
                "amount": 1,
                "idempotency_key": "grant-once",
                "reason": "客服补发",
                "confirmed": False,
            }
        )
    )

    assert result["error"] == "confirmation_required"


def test_weiban_query_account_is_in_xbot_hermes_catalog():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)

    tool = runtime.tools.get("weiban_query_account")

    assert tool is not None
    assert tool.toolset == "hermes"
    assert tool.source == "hermes"


def test_agent_chat_prompt_directs_readonly_weiban_queries_and_keeps_writes_admin_only():
    project_root = Path(__file__).resolve().parents[3]
    expected_fragments = (
        "use weiban_query_account with exactly one of the user's email or permanent invite code",
        "never pass both fields and omit the unused field entirely",
        "do not say that an administrator must enable query access",
        "only admin may perform them; guest and member must refuse them",
    )

    for relative_path in (
        "plugins/agent_chat/main.py",
        "tests/fixtures/plugins/agent_chat/main.py",
    ):
        prompt_source = (project_root / relative_path).read_text(encoding="utf-8")
        for fragment in expected_fragments:
            assert fragment in prompt_source
