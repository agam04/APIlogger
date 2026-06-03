from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {"sub": subject, "exp": expire, **(extra or {})}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)  # type: ignore[no-any-return]


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises JWTError on invalid / expired tokens."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])  # type: ignore[no-any-return]


__all__ = ["hash_password", "verify_password", "create_access_token", "decode_access_token", "JWTError"]
