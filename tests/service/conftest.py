from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from auth import user_store
from core import settings
from core.observability import get_langfuse_client
from rag import rag_store
from service import app
from service.auth import AuthContext, get_auth_context


@pytest.fixture(autouse=True)
def disable_live_langfuse_for_unit_tests(monkeypatch):
    """Unit tests must not export traces to a developer's configured project."""
    monkeypatch.setattr(settings, "LANGFUSE_TRACING", False)
    get_langfuse_client.cache_clear()


@pytest.fixture(autouse=True)
def disable_live_rag_store_for_unit_tests(monkeypatch):
    """Unit tests must not connect to a developer's PostgreSQL RAG tables."""
    monkeypatch.setattr(rag_store, "open", AsyncMock())
    monkeypatch.setattr(rag_store, "close", AsyncMock())
    yield
    get_langfuse_client.cache_clear()


@pytest.fixture(autouse=True)
def disable_live_user_store_for_unit_tests(monkeypatch):
    """Unit tests must not open the developer's PostgreSQL user database."""
    monkeypatch.setattr(user_store, "open", AsyncMock())
    monkeypatch.setattr(user_store, "close", AsyncMock())


@pytest.fixture(autouse=True)
def use_service_auth_for_existing_endpoint_tests():
    """Existing service tests exercise machine-client compatibility via service auth."""
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(service_access=True)
    yield
    app.dependency_overrides.pop(get_auth_context, None)


@pytest.fixture
def test_client():
    """Fixture to create a FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_agent():
    """Fixture to create a mock agent that can be configured for different test scenarios."""
    agent_mock = AsyncMock()
    agent_mock.ainvoke = AsyncMock(
        return_value=[("values", {"messages": [AIMessage(content="Test response")]})]
    )
    agent_mock.get_state = Mock()  # Default empty mock for get_state
    with patch("service.service.get_agent", Mock(return_value=agent_mock)):
        yield agent_mock


@pytest.fixture
def mock_settings(mock_env):
    """Fixture to ensure settings are clean for each test."""
    with patch("service.service.settings") as mock_settings:
        yield mock_settings


@pytest.fixture
def mock_httpx():
    """Patch httpx.stream and httpx.get to use our test client."""

    with TestClient(app) as client:

        def mock_stream(method: str, url: str, **kwargs):
            # Strip the base URL since TestClient expects just the path
            path = url.replace("http://0.0.0.0", "")
            return client.stream(method, path, **kwargs)

        def mock_get(url: str, **kwargs):
            # Strip the base URL since TestClient expects just the path
            path = url.replace("http://0.0.0.0", "")
            return client.get(path, **kwargs)

        with patch("httpx.stream", mock_stream):
            with patch("httpx.get", mock_get):
                yield
