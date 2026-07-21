import logging
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status

from core import settings
from rag.documents import EmptyDocumentError, UnsupportedDocumentError
from rag.store import DuplicateDocumentError, rag_store
from schema import RagDocument

router = APIRouter(prefix="/rag", tags=["rag"])
logger = logging.getLogger(__name__)


@router.get("/documents")
async def list_rag_documents() -> list[RagDocument]:
    records = await rag_store.list_documents()
    return [RagDocument(**asdict(record)) for record in records]


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_rag_document(file: UploadFile = File(...)) -> RagDocument:
    if not file.filename:
        raise HTTPException(status_code=422, detail="A filename is required")

    data = await file.read(settings.RAG_MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > settings.RAG_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Document exceeds the {settings.RAG_MAX_UPLOAD_BYTES} byte upload limit",
        )

    try:
        record = await rag_store.ingest(file.filename, file.content_type, data)
    except DuplicateDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (UnsupportedDocumentError, EmptyDocumentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to index RAG document %s: %s", file.filename, exc)
        raise HTTPException(status_code=500, detail="Failed to index document") from exc
    return RagDocument(**asdict(record))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rag_document(document_id: UUID) -> Response:
    if not await rag_store.delete_document(document_id):
        raise HTTPException(status_code=404, detail="RAG document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
