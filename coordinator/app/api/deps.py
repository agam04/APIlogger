"""FastAPI dependency injection."""

import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import JWTError, decode_access_token
from app.db.base import get_db
from app.db.models import User

_bearer = HTTPBearer()

# Shared redis pool — created once at startup
_redis_pool: aioredis.Redis | None = None


def get_redis_pool() -> aioredis.Redis:
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialised")
    return _redis_pool


async def init_redis() -> None:
    global _redis_pool
    _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    if _redis_pool:
        await _redis_pool.aclose()


# ---- DB session ----
DBSession = Annotated[AsyncSession, Depends(get_db)]

# ---- Redis ----
RedisConn = Annotated[aioredis.Redis, Depends(get_redis_pool)]


# ---- Current authenticated user ----
async def get_current_user(
    db: DBSession,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(creds.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception from None

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
