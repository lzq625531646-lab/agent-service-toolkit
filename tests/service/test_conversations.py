from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage

from auth import ConversationRecord, UserRecord, user_store
from service import app
from service.auth import AuthContext, get_auth_context, get_current_user


def make_user(email: str = "owner@example.com") -> UserRecord:
    return UserRecord(
        id=uuid4(),
        email=email,
        display_name="Owner",
        password_hash="unused",
        created_at=datetime.now(UTC),
    )


def make_conversation(user: UserRecord, thread_id: str = "thread-1") -> ConversationRecord:
    now = datetime.now(UTC)
    return ConversationRecord(
        thread_id=thread_id,
        user_id=user.id,
        title="Company policy",
        agent_id="rag-assistant",
        model="openai-compatible",
        created_at=now,
        updated_at=now,
    )


def test_list_conversations_is_scoped_to_current_user(test_client, monkeypatch) -> None:
    user = make_user()
    list_conversations = AsyncMock(return_value=[make_conversation(user)])
    monkeypatch.setattr(user_store, "list_conversations", list_conversations)
    app.dependency_overrides[get_current_user] = lambda: user

    response = test_client.get("/conversations")

    assert response.status_code == 200
    assert response.json()[0]["thread_id"] == "thread-1"
    list_conversations.assert_awaited_once_with(user.id)
    app.dependency_overrides.pop(get_current_user, None)


def test_conversation_history_rejects_unowned_thread(test_client, monkeypatch) -> None:
    user = make_user()
    monkeypatch.setattr(user_store, "get_conversation", AsyncMock(return_value=None))
    app.dependency_overrides[get_current_user] = lambda: user

    response = test_client.get("/conversations/not-mine/messages")

    assert response.status_code == 404
    app.dependency_overrides.pop(get_current_user, None)


def test_authenticated_invoke_uses_account_user_id(test_client, mock_agent, monkeypatch) -> None:
    user = make_user()
    conversation = make_conversation(user)
    ensure_conversation = AsyncMock(return_value=conversation)
    touch_conversation = AsyncMock()
    monkeypatch.setattr(user_store, "ensure_conversation", ensure_conversation)
    monkeypatch.setattr(user_store, "touch_conversation", touch_conversation)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user, token="session")
    mock_agent.ainvoke.return_value = [
        ("values", {"messages": [AIMessage(content="Account scoped response")]})
    ]

    with patch("service.service.get_agent", return_value=mock_agent):
        response = test_client.post(
            "/rag-assistant/invoke",
            json={
                "message": "Company policy",
                "thread_id": "thread-1",
                "user_id": "attacker-controlled-id",
                "model": "openai-compatible",
            },
        )

    assert response.status_code == 200
    config = mock_agent.ainvoke.await_args.kwargs["config"]
    assert config["configurable"]["user_id"] == str(user.id)
    ensure_conversation.assert_awaited_once()
    touch_conversation.assert_awaited_once_with(user.id, "thread-1")
