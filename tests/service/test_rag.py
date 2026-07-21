from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from rag.store import DuplicateDocumentError, RagDocumentRecord, rag_store


def make_record() -> RagDocumentRecord:
    return RagDocumentRecord(
        id=uuid4(),
        filename="handbook.txt",
        content_type="text/plain",
        size_bytes=12,
        sha256="a" * 64,
        chunk_count=2,
        created_at=datetime.now(UTC),
    )


def test_upload_rag_document(test_client, monkeypatch):
    record = make_record()
    ingest = AsyncMock(return_value=record)
    monkeypatch.setattr(rag_store, "ingest", ingest)

    response = test_client.post(
        "/rag/documents",
        files={"file": ("handbook.txt", b"handbook text", "text/plain")},
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(record.id)
    assert response.json()["chunk_count"] == 2
    ingest.assert_awaited_once_with("handbook.txt", "text/plain", b"handbook text")


def test_upload_duplicate_rag_document_returns_conflict(test_client, monkeypatch):
    monkeypatch.setattr(
        rag_store,
        "ingest",
        AsyncMock(side_effect=DuplicateDocumentError("already uploaded")),
    )

    response = test_client.post(
        "/rag/documents",
        files={"file": ("handbook.txt", b"handbook text", "text/plain")},
    )

    assert response.status_code == 409


def test_list_rag_documents(test_client, monkeypatch):
    record = make_record()
    monkeypatch.setattr(rag_store, "list_documents", AsyncMock(return_value=[record]))

    response = test_client.get("/rag/documents")

    assert response.status_code == 200
    assert response.json()[0]["filename"] == "handbook.txt"


def test_delete_rag_document(test_client, monkeypatch):
    document_id = uuid4()
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(rag_store, "delete_document", delete)

    response = test_client.delete(f"/rag/documents/{document_id}")

    assert response.status_code == 204
    delete.assert_awaited_once_with(document_id)


def test_delete_missing_rag_document(test_client, monkeypatch):
    monkeypatch.setattr(rag_store, "delete_document", AsyncMock(return_value=False))

    response = test_client.delete(f"/rag/documents/{uuid4()}")

    assert response.status_code == 404
