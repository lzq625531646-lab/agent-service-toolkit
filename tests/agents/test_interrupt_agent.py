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
async def test_determine_birthdate_returns_value_from_store(monkeypatch) -> None:
    store = SimpleNamespace(
        aget=AsyncMock(return_value=SimpleNamespace(value={"birthdate": "1996-12-27T00:00:00"})),
        aput=AsyncMock(),
        adelete=AsyncMock(),
    )
    extract = AsyncMock(
        return_value=interrupt_agent.BirthdateExtraction(
            action="none", birthdate=None, reasoning="The user only asked a question."
        )
    )
    monkeypatch.setattr(interrupt_agent, "_extract_birthdate_change", extract)
    state = {"messages": [HumanMessage(content="What is my zodiac sign?")]}
    config = {"configurable": {"user_id": "user-1"}}

    result = await interrupt_agent.determine_birthdate(state, config, store)

    assert result == {
        "birthdate": datetime(1996, 12, 27),
        "birthdate_deleted": False,
        "messages": [],
    }
    store.aget.assert_awaited_once_with(("user-1",), key="birthdate")
    store.aput.assert_not_awaited()
    extract.assert_awaited_once_with("What is my zodiac sign?", config)


@pytest.mark.asyncio
async def test_determine_birthdate_correction_overwrites_store(monkeypatch) -> None:
    store = SimpleNamespace(
        aget=AsyncMock(return_value=SimpleNamespace(value={"birthdate": "1996-12-27T00:00:00"})),
        aput=AsyncMock(),
        adelete=AsyncMock(),
    )
    monkeypatch.setattr(
        interrupt_agent,
        "_extract_birthdate_change",
        AsyncMock(
            return_value=interrupt_agent.BirthdateExtraction(
                action="correct",
                birthdate="1999-05-08",
                reasoning="The user explicitly corrected their birthdate.",
            )
        ),
    )
    state = {"messages": [HumanMessage(content="1999年5月8日才是正确的")]}
    config = {"configurable": {"user_id": "user-1"}}

    result = await interrupt_agent.determine_birthdate(state, config, store)

    assert result == {
        "birthdate": datetime(1999, 5, 8),
        "birthdate_deleted": False,
        "messages": [],
    }
    assert store.aput.await_count == 2
    current_write = store.aput.await_args_list[0]
    assert current_write.args[:2] == (("user-1",), "birthdate")
    assert current_write.args[2]["birthdate"] == "1999-05-08T00:00:00"
    audit_write = store.aput.await_args_list[1]
    assert audit_write.args[0] == ("user-1", "profile_history", "birthdate")
    assert audit_write.args[2]["old_value"] == "1996-12-27T00:00:00"
    assert audit_write.args[2]["new_value"] == "1999-05-08T00:00:00"


@pytest.mark.asyncio
async def test_determine_birthdate_delete_clears_store(monkeypatch) -> None:
    store = SimpleNamespace(
        aget=AsyncMock(return_value=SimpleNamespace(value={"birthdate": "1996-12-27T00:00:00"})),
        aput=AsyncMock(),
        adelete=AsyncMock(),
    )
    monkeypatch.setattr(
        interrupt_agent,
        "_extract_birthdate_change",
        AsyncMock(
            return_value=interrupt_agent.BirthdateExtraction(
                action="delete", birthdate=None, reasoning="The user asked to forget it."
            )
        ),
    )
    state = {"messages": [HumanMessage(content="Forget my birthdate")]}
    config = {"configurable": {"user_id": "user-1"}}

    result = await interrupt_agent.determine_birthdate(state, config, store)

    assert result == {"birthdate": None, "birthdate_deleted": True, "messages": []}
    store.adelete.assert_awaited_once_with(("user-1",), "birthdate")
    assert store.aput.await_count == 1


@pytest.mark.asyncio
async def test_generate_response_passes_complete_conversation_history(monkeypatch) -> None:
    model = RecordingModel("Your zodiac sign is Capricorn.")
    monkeypatch.setattr(interrupt_agent, "get_model", lambda _: model)
    history = [
        HumanMessage(content="What is my zodiac sign?"),
        AIMessage(content="Your zodiac sign is Capricorn."),
        HumanMessage(content="What are its weaknesses?"),
    ]
    state = {
        "messages": history,
        "birthdate": datetime(1996, 12, 27),
    }
    config = {"configurable": {}}

    result = await interrupt_agent.generate_response(state, config)

    assert result == {"messages": [AIMessage(content="Your zodiac sign is Capricorn.")]}
    assert len(model.messages) == 4
    assert isinstance(model.messages[0], SystemMessage)
    assert "December 27, 1996" in model.messages[0].content
    assert model.messages[1:] == history
    assert isinstance(model.messages[-1], HumanMessage)
    assert model.messages[-1].content == "What are its weaknesses?"


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
