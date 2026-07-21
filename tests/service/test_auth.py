from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import SecretStr

from auth import UserRecord, user_store
from auth.security import verify_password
from core import settings
from service import app
from service.auth import get_auth_context


def make_user() -> UserRecord:
    return UserRecord(
        id=uuid4(),
        email="member@example.com",
        display_name="Member",
        password_hash="encoded-password",
        created_at=datetime.now(UTC),
    )


def use_real_auth_dependency() -> None:
    app.dependency_overrides.pop(get_auth_context, None)


def test_protected_endpoint_requires_auth(test_client, monkeypatch) -> None:
    use_real_auth_dependency()
    monkeypatch.setattr(settings, "AUTH_SECRET", None)

    response = test_client.get("/info")

    assert response.status_code == 401


def test_user_session_authenticates_protected_endpoint(test_client, monkeypatch) -> None:
    use_real_auth_dependency()
    monkeypatch.setattr(settings, "AUTH_SECRET", None)
    monkeypatch.setattr(
        user_store, "get_user_by_session_token", AsyncMock(return_value=make_user())
    )

    response = test_client.get("/info", headers={"Authorization": "Bearer user-session"})

    assert response.status_code == 200
    user_store.get_user_by_session_token.assert_awaited_once_with("user-session")


def test_service_secret_remains_supported(test_client, monkeypatch) -> None:
    use_real_auth_dependency()
    monkeypatch.setattr(settings, "AUTH_SECRET", SecretStr("service-secret"))

    response = test_client.get(
        "/info",
        headers={"Authorization": "Bearer service-secret"},
    )

    assert response.status_code == 200


def test_register_creates_hashed_user_and_session(test_client, monkeypatch) -> None:
    user = make_user()
    create_user = AsyncMock(return_value=user)
    expires_at = datetime.now(UTC) + timedelta(days=30)
    create_session = AsyncMock(return_value=("new-session", expires_at))
    monkeypatch.setattr(user_store, "create_user", create_user)
    monkeypatch.setattr(user_store, "create_session", create_session)

    response = test_client.post(
        "/auth/register",
        json={
            "email": "Member@Example.com",
            "display_name": "Member",
            "password": "correct-horse-battery-staple",
        },
    )

    assert response.status_code == 201
    assert response.json()["access_token"] == "new-session"
    encoded_password = create_user.await_args.kwargs["encoded_password"]
    assert encoded_password != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", encoded_password)
    create_session.assert_awaited_once()


def test_login_rejects_invalid_password(test_client, monkeypatch) -> None:
    monkeypatch.setattr(user_store, "get_user_by_email", AsyncMock(return_value=None))

    response = test_client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"
