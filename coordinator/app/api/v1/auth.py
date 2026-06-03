"""Auth endpoints: register + login."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DBSession
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    model_config = {"json_schema_extra": {"example": {"email": "user@example.com", "password": "s3cret"}}}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str

    model_config = {"from_attributes": True}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DBSession) -> UserResponse:
    user = User(email=body.email, hashed_pw=hash_password(body.password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None
    return UserResponse(id=str(user.id), email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DBSession) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)
