from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import DuplicateUserError, UserRecord, user_store
from auth.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from core import settings
from schema import AuthResponse, LoginRequest, RegisterRequest, UserProfile

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: UserRecord | None = None
    service_access: bool = False
    token: str | None = None


def to_user_profile(user: UserRecord) -> UserProfile:
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
    )


async def get_auth_context(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> AuthContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if settings.AUTH_SECRET and token == settings.AUTH_SECRET.get_secret_value():
        return AuthContext(service_access=True, token=token)

    user = await user_store.get_user_by_session_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthContext(user=user, token=token)


async def get_current_user(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> UserRecord:
    if auth.user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A user login is required for this operation",
        )
    return auth.user


async def _issue_auth_response(user: UserRecord) -> AuthResponse:
    token, expires_at = await user_store.create_session(
        user.id,
        timedelta(days=settings.USER_SESSION_DAYS),
    )
    return AuthResponse(
        access_token=token,
        expires_at=expires_at,
        user=to_user_profile(user),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(input: RegisterRequest) -> AuthResponse:
    try:
        user = await user_store.create_user(
            email=str(input.email),
            display_name=input.display_name,
            encoded_password=hash_password(input.password),
        )
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _issue_auth_response(user)


@router.post("/login", response_model=AuthResponse)
async def login(input: LoginRequest) -> AuthResponse:
    user = await user_store.get_user_by_email(str(input.email))
    encoded_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_valid = verify_password(input.password, encoded_hash)
    if user is None or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _issue_auth_response(user)


@router.get("/me", response_model=UserProfile)
async def me(user: Annotated[UserRecord, Depends(get_current_user)]) -> UserProfile:
    return to_user_profile(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> None:
    if auth.user is not None and auth.token is not None:
        await user_store.revoke_session(auth.token)
