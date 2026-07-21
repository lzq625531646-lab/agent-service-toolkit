import pytest

from rag.documents import EmptyDocumentError, UnsupportedDocumentError, process_document


def test_process_text_document_splits_and_adds_metadata(monkeypatch):
    from rag import documents

    monkeypatch.setattr(documents.settings, "RAG_CHUNK_SIZE", 20)
    monkeypatch.setattr(documents.settings, "RAG_CHUNK_OVERLAP", 0)

    processed = process_document(
        "../handbook.txt",
        "text/plain",
        b"Employee handbook content that is long enough to split.",
    )

    assert processed.filename == "handbook.txt"
    assert processed.content_type == "text/plain"
    assert processed.size_bytes > 0
    assert len(processed.sha256) == 64
    assert len(processed.chunks) > 1
    assert processed.chunks[0].metadata == {"source": "handbook.txt", "chunk_index": 0}


def test_process_document_rejects_unsupported_extension():
    with pytest.raises(UnsupportedDocumentError):
        process_document("archive.zip", "application/zip", b"not a document")


def test_process_document_rejects_empty_content():
    with pytest.raises(EmptyDocumentError):
        process_document("empty.txt", "text/plain", b"")
