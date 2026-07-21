import os
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import docx2txt  # type: ignore[import-untyped]
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from core.settings import settings

SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class UnsupportedDocumentError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedDocument:
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    chunks: list[Document]


def process_document(filename: str, content_type: str | None, data: bytes) -> ProcessedDocument:
    """Extract and split an uploaded RAG document without persisting the original file."""
    safe_filename = Path(filename).name
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise UnsupportedDocumentError(f"Unsupported document type. Supported: {supported}")
    if not data:
        raise EmptyDocumentError("The uploaded document is empty")

    documents = _extract_documents(safe_filename, suffix, data)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.RAG_CHUNK_SIZE,
        chunk_overlap=settings.RAG_CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)
    chunks = [chunk for chunk in chunks if chunk.page_content.strip()]
    if not chunks:
        raise EmptyDocumentError("No readable text was found in the uploaded document")

    for index, chunk in enumerate(chunks):
        chunk.metadata.update({"source": safe_filename, "chunk_index": index})

    return ProcessedDocument(
        filename=safe_filename,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        chunks=chunks,
    )


def _extract_documents(filename: str, suffix: str, data: bytes) -> list[Document]:
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(data))
        return [
            Document(page_content=page.extract_text() or "", metadata={"page": index + 1})
            for index, page in enumerate(reader.pages)
        ]

    if suffix == ".docx":
        path = ""
        try:
            with NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
                temporary_file.write(data)
                path = temporary_file.name
            return [Document(page_content=docx2txt.process(path), metadata={})]
        finally:
            if path:
                os.unlink(path)

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedDocumentError(f"{filename} must use UTF-8 text encoding") from exc
    return [Document(page_content=text, metadata={})]
