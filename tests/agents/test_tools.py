from concurrent.futures import ThreadPoolExecutor
from time import sleep
from unittest.mock import Mock

from agents import tools


def test_load_chroma_db_initializes_once_under_concurrency(monkeypatch):
    retriever = Mock()
    chroma = Mock()
    chroma.as_retriever.return_value = retriever

    def create_chroma(**kwargs):
        sleep(0.01)
        return chroma

    monkeypatch.setattr(tools, "_chroma_retriever", None)
    monkeypatch.setattr(tools, "get_embeddings", Mock(return_value=Mock()))
    chroma_factory = Mock(side_effect=create_chroma)
    monkeypatch.setattr(tools, "Chroma", chroma_factory)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: tools.load_chroma_db(), range(20)))

    assert all(result is retriever for result in results)
    chroma_factory.assert_called_once()
    chroma.as_retriever.assert_called_once_with(search_kwargs={"k": 5})
