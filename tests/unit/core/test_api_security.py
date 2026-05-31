from xbot.app.security import token_matches


def test_token_matches_uses_exact_secret() -> None:
    assert token_matches("secret-token", "secret-token") is True
    assert token_matches("secret-token", "other-token") is False
    assert token_matches("", "secret-token") is False
    assert token_matches("secret-token", "") is False
