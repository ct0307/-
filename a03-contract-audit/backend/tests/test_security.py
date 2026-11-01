"""认证令牌的会话隔离契约。"""

import bcrypt
import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_repeated_logins_receive_distinct_access_tokens():
    first = create_access_token("legal", "legal")
    second = create_access_token("legal", "legal")

    assert first != second
    first_payload = decode_access_token(first)
    second_payload = decode_access_token(second)
    assert first_payload is not None
    assert second_payload is not None
    assert first_payload["jti"] != second_payload["jti"]


@pytest.mark.parametrize("password", ["a" * 72, "密" * 24])
def test_password_at_72_utf8_bytes_remains_supported(password):
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True


@pytest.mark.parametrize("password", ["a" * 73, "密" * 25])
def test_hash_rejects_password_over_72_utf8_bytes_without_echoing_it(password):
    with pytest.raises(ValueError, match="密码.*72.*字节") as caught:
        hash_password(password)

    assert password not in str(caught.value)


@pytest.mark.parametrize("suffix", ["first", "second"])
def test_passwords_with_same_72_byte_prefix_cannot_log_in(suffix):
    prefix = "a" * 72
    legacy_hash = bcrypt.hashpw(prefix.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    assert verify_password(prefix + suffix, legacy_hash) is False
    assert verify_password(prefix, legacy_hash) is True


def test_short_password_remains_compatible_with_existing_bcrypt_hash():
    legacy_hash = bcrypt.hashpw(b"legacy123", bcrypt.gensalt()).decode("utf-8")

    assert verify_password("legacy123", legacy_hash) is True
    assert verify_password("wrong", legacy_hash) is False
    assert verify_password("legacy123", "invalid_hash") is False
