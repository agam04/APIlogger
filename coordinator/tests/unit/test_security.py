"""Unit tests for security utilities."""

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_round_trip():
    plain = "s3cur3P@ss!"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed)


def test_wrong_password_rejected():
    hashed = hash_password("correct")
    assert not verify_password("wrong", hashed)


def test_jwt_round_trip():
    token = create_access_token("user-uuid-123")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-uuid-123"


def test_tampered_jwt_rejected():
    token = create_access_token("user-id") + "tampered"
    with pytest.raises(JWTError):
        decode_access_token(token)


def test_extra_claims_preserved():
    token = create_access_token("uid", extra={"role": "admin"})
    payload = decode_access_token(token)
    assert payload["role"] == "admin"
