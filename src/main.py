from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NO_PROXY = "localhost,127.0.0.1,0.0.0.0,::1"

load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("NO_PROXY", NO_PROXY)
os.environ.setdefault("no_proxy", NO_PROXY)

from core import settings  # noqa: E402
from service import app  # noqa: E402


def main() -> None:
    """Start the FastAPI agent service without uvicorn reload."""
    logging.basicConfig(level=settings.LOG_LEVEL.to_logging_level())
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        timeout_graceful_shutdown=settings.GRACEFUL_SHUTDOWN_TIMEOUT,
    )


if __name__ == "__main__":
    main()
