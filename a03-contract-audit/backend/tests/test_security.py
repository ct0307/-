"""认证令牌的会话隔离契约。"""

from app.core.security import create_access_token, decode_access_token


def test_repeated_logins_receive_distinct_access_tokens():
    first = create_access_token("legal", "legal")
    second = create_access_token("legal", "legal")

    assert first != second
    first_payload = decode_access_token(first)
    second_payload = decode_access_token(second)
    assert first_payload is not None
    assert second_payload is not None
    assert first_payload["jti"] != second_payload["jti"]
