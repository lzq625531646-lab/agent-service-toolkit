from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents import interrupt_agent


class RecordingModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages = []

    async def ainvoke(self, messages, config):
        self.messages = messages
        return AIMessage(content=self.content)


def test_latest_human_message_ignores_trailing_ai_message() -> None:
    messages = [
        HumanMessage(content="What is my zodiac sign?"),
        AIMessage(content="Zodiac signs have ancient origins."),
    ]

    assert interrupt_agent._latest_human_message(messages) == "What is my zodiac sign?"


@pytest.mark.asyncio
async def test_determine_birthdate_returns_value_from_store() -> None:
    store = SimpleNamespace(
        aget=AsyncMock(return_value=SimpleNamespace(value={"birthdate": "1996-12-27T00:00:00"}))
    )
    state = {"messages": [HumanMessage(content="What is my zodiac sign?")]}
    config = {"configurable": {"user_id": "user-1"}}

    result = await interrupt_agent.determine_birthdate(state, config, store)

    assert result == {"birthdate": datetime(1996, 12, 27), "messages": []}
    store.aget.assert_awaited_once_with(("user-1",), key="birthdate")


@pytest.mark.asyncio
async def test_generate_response_ends_model_input_with_original_user_request(monkeypatch) -> None:
    model = RecordingModel("Your zodiac sign is Capricorn.")
    monkeypatch.setattr(interrupt_agent, "get_model", lambda _: model)
    state = {
        "messages": [
            HumanMessage(content="What is my zodiac sign?"),
            AIMessage(content="Zodiac signs have ancient origins."),
        ],
        "birthdate": datetime(1996, 12, 27),
        "user_request": "What is my zodiac sign?",
    }
    config = {"configurable": {}}

    result = await interrupt_agent.generate_response(state, config)

    assert result == {"messages": [AIMessage(content="Your zodiac sign is Capricorn.")]}
    assert len(model.messages) == 2
    assert isinstance(model.messages[0], SystemMessage)
    assert "December 27, 1996" in model.messages[0].content
    assert isinstance(model.messages[1], HumanMessage)
    assert model.messages[1].content == "What is my zodiac sign?"


@pytest.mark.asyncio
async def test_generate_response_replaces_empty_model_response(monkeypatch) -> None:
    model = RecordingModel("")
    monkeypatch.setattr(interrupt_agent, "get_model", lambda _: model)
    state = {
        "messages": [HumanMessage(content="What is my zodiac sign?")],
        "birthdate": datetime(1996, 12, 27),
        "user_request": "What is my zodiac sign?",
    }
    config = {"configurable": {}}

    result = await interrupt_agent.generate_response(state, config)

    assert result == {
        "messages": [AIMessage(content="I couldn't generate a response. Please try again.")]
    }
