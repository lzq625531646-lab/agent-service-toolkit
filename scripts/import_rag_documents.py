import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag.documents import SUPPORTED_DOCUMENT_EXTENSIONS  # noqa: E402
from rag.store import DuplicateDocumentError, rag_store  # noqa: E402


async def main() -> None:
    data_directory = PROJECT_ROOT / "data"
    await rag_store.open()
    try:
        for path in sorted(data_directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
                continue
            try:
                record = await rag_store.ingest(
                    path.name,
                    "application/octet-stream",
                    path.read_bytes(),
                )
                print(f"Indexed {record.filename}: {record.chunk_count} chunks")  # noqa: T201
            except DuplicateDocumentError:
                print(f"Skipped {path.name}: already indexed")  # noqa: T201
    finally:
        await rag_store.close()


if __name__ == "__main__":
    asyncio.run(main())
