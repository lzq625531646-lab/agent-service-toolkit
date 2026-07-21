from unittest.mock import AsyncMock

import pytest

from agents import tools


@pytest.mark.asyncio
async def test_database_search_uses_pgvector_store(monkeypatch):
    documents = [
        type("Document", (), {"page_content": "Employees receive 15 days of PTO."})(),
        type("Document", (), {"page_content": "PTO accrues monthly."})(),
    ]
    search = AsyncMock(return_value=documents)
    monkeypatch.setattr(tools.rag_store, "similarity_search", search)

    result = await tools.database_search_func("How much PTO is provided?")

    assert result == "Employees receive 15 days of PTO.\n\nPTO accrues monthly."
    search.assert_awaited_once_with("How much PTO is provided?")
