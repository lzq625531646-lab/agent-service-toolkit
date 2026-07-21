from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from core.settings import settings


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    """Return the Ollama embedding client shared by indexing and retrieval."""
    return OllamaEmbeddings(
        model=settings.OLLAMA_EMBEDDING_MODEL,
        base_url=settings.OLLAMA_EMBEDDING_BASE_URL,
        validate_model_on_init=True,
    )
