import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from langchain_core.documents import Document
from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from core.embeddings import get_embeddings
from core.settings import settings
from rag.documents import ProcessedDocument, process_document


class DuplicateDocumentError(ValueError):
    pass


class RagStoreNotInitializedError(RuntimeError):
    pass


@dataclass(frozen=True)
class RagDocumentRecord:
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    chunk_count: int
    created_at: datetime


async def _configure_vector_connection(connection: AsyncConnection[Any]) -> None:
    await register_vector_async(connection)


class PgVectorRagStore:
    """PostgreSQL/pgvector-backed document catalog and semantic chunk index."""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool[AsyncConnection[Any]] | None = None
        self._open_lock = asyncio.Lock()

    async def open(self) -> None:
        if self._pool is not None:
            return
        async with self._open_lock:
            if self._pool is not None:
                return

            conninfo = self._connection_string()
            async with await AsyncConnection.connect(conninfo, autocommit=True) as connection:
                await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")

            pool: AsyncConnectionPool[AsyncConnection[Any]] = AsyncConnectionPool(
                conninfo,
                min_size=settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
                max_size=settings.POSTGRES_MAX_CONNECTIONS_PER_POOL,
                open=False,
                configure=_configure_vector_connection,
                kwargs={
                    "autocommit": True,
                    "row_factory": dict_row,
                    "application_name": f"{settings.POSTGRES_APPLICATION_NAME}-rag",
                },
                check=AsyncConnectionPool.check_connection,
            )
            await pool.open(wait=True)
            try:
                await self._setup_schema(pool)
            except Exception:
                await pool.close()
                raise
            self._pool = pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ingest(
        self, filename: str, content_type: str | None, data: bytes
    ) -> RagDocumentRecord:
        processed = await asyncio.to_thread(process_document, filename, content_type, data)
        pool = self._require_pool()

        async with pool.connection() as connection:
            existing = await connection.execute(
                "SELECT id FROM rag_documents WHERE sha256 = %s",
                (processed.sha256,),
            )
            if await existing.fetchone():
                raise DuplicateDocumentError("This document has already been uploaded")

        embeddings = await get_embeddings().aembed_documents(
            [chunk.page_content for chunk in processed.chunks]
        )
        self._validate_embeddings(embeddings)
        document_id = uuid4()

        try:
            async with pool.connection() as connection, connection.transaction():
                created = await connection.execute(
                    """
                    INSERT INTO rag_documents (id, filename, content_type, size_bytes, sha256)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING created_at
                    """,
                    (
                        document_id,
                        processed.filename,
                        processed.content_type,
                        processed.size_bytes,
                        processed.sha256,
                    ),
                )
                created_row = await created.fetchone()
                if created_row is None:
                    raise RuntimeError("PostgreSQL did not return the created RAG document")
                created_at = created_row["created_at"]
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        """
                        INSERT INTO rag_chunks
                            (id, document_id, chunk_index, content, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                uuid4(),
                                document_id,
                                index,
                                chunk.page_content,
                                Jsonb(chunk.metadata),
                                Vector(embedding),
                            )
                            for index, (chunk, embedding) in enumerate(
                                zip(processed.chunks, embeddings, strict=True)
                            )
                        ],
                    )
        except UniqueViolation as exc:
            raise DuplicateDocumentError("This document has already been uploaded") from exc

        return self._record(processed, document_id, created_at)

    async def list_documents(self) -> list[RagDocumentRecord]:
        pool = self._require_pool()
        async with pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT d.id, d.filename, d.content_type, d.size_bytes, d.sha256,
                       d.created_at, count(c.id)::integer AS chunk_count
                FROM rag_documents d
                LEFT JOIN rag_chunks c ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.created_at DESC
                """
            )
            return [RagDocumentRecord(**row) for row in await cursor.fetchall()]

    async def delete_document(self, document_id: UUID) -> bool:
        pool = self._require_pool()
        async with pool.connection() as connection:
            cursor = await connection.execute(
                "DELETE FROM rag_documents WHERE id = %s",
                (document_id,),
            )
            return cursor.rowcount > 0

    async def similarity_search(self, query: str, k: int | None = None) -> list[Document]:
        query_embedding = await get_embeddings().aembed_query(query)
        self._validate_embeddings([query_embedding])
        vector = Vector(query_embedding)
        pool = self._require_pool()
        async with pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT c.content, c.metadata, d.id AS document_id, d.filename,
                       1 - (c.embedding <=> %s) AS similarity
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                ORDER BY c.embedding <=> %s
                LIMIT %s
                """,
                (vector, vector, k or settings.RAG_SEARCH_K),
            )
            rows = await cursor.fetchall()
        return [
            Document(
                page_content=row["content"],
                metadata={
                    **row["metadata"],
                    "document_id": str(row["document_id"]),
                    "source": row["filename"],
                    "similarity": float(row["similarity"]),
                },
            )
            for row in rows
        ]

    def _connection_string(self) -> str:
        if settings.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD is not set")
        return make_conninfo(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            dbname=settings.POSTGRES_DB,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD.get_secret_value(),
        )

    def _require_pool(self) -> AsyncConnectionPool[AsyncConnection[Any]]:
        if self._pool is None:
            raise RagStoreNotInitializedError("RAG store has not been initialized")
        return self._pool

    def _validate_embeddings(self, embeddings: list[list[float]]) -> None:
        dimensions = settings.RAG_EMBEDDING_DIMENSIONS
        if any(len(embedding) != dimensions for embedding in embeddings):
            raise ValueError(
                f"Embedding model must return {dimensions} dimensions. "
                "Recreate the pgvector table before changing embedding models."
            )

    async def _setup_schema(self, pool: AsyncConnectionPool[AsyncConnection[Any]]) -> None:
        dimensions = settings.RAG_EMBEDDING_DIMENSIONS
        async with pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id UUID PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
                    sha256 CHAR(64) NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id UUID PRIMARY KEY,
                    document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({dimensions}) NOT NULL,
                    UNIQUE (document_id, chunk_index)
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw_idx
                ON rag_chunks USING hnsw (embedding vector_cosine_ops)
                """
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS rag_chunks_document_id_idx ON rag_chunks (document_id)"
            )

    @staticmethod
    def _record(
        processed: ProcessedDocument, document_id: UUID, created_at: datetime
    ) -> RagDocumentRecord:
        return RagDocumentRecord(
            id=document_id,
            filename=processed.filename,
            content_type=processed.content_type,
            size_bytes=processed.size_bytes,
            sha256=processed.sha256,
            chunk_count=len(processed.chunks),
            created_at=created_at,
        )


rag_store = PgVectorRagStore()
