"""Langfuse observability helpers shared by all agent transports."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from typing import Any

from langfuse import Langfuse, propagate_attributes  # type: ignore[import-untyped]
from langfuse.langchain import CallbackHandler  # type: ignore[import-untyped]

from core.settings import settings

logger = logging.getLogger(__name__)


@cache
def get_langfuse_client() -> Langfuse | None:
    """Return the configured singleton client, or None when tracing is disabled."""
    if not settings.LANGFUSE_TRACING:
        return None
    if settings.LANGFUSE_PUBLIC_KEY is None or settings.LANGFUSE_SECRET_KEY is None:
        logger.error(
            "LANGFUSE_TRACING is enabled but LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY are missing"
        )
        return None

    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY.get_secret_value(),
        secret_key=settings.LANGFUSE_SECRET_KEY.get_secret_value(),
        base_url=settings.LANGFUSE_HOST,
        environment=settings.LANGFUSE_ENVIRONMENT,
        release=settings.LANGFUSE_RELEASE,
        debug=settings.LANGFUSE_DEBUG,
        tracing_enabled=True,
    )


def get_langfuse_handler() -> CallbackHandler | None:
    """Create a per-run LangChain handler backed by the configured singleton client."""
    client = get_langfuse_client()
    if client is None or settings.LANGFUSE_PUBLIC_KEY is None:
        return None
    return CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY.get_secret_value())


@contextmanager
def observe_agent_run(
    *,
    agent_id: str,
    protocol: str,
    run_id: str,
    thread_id: str | None,
    user_id: str | None,
    model: str | None,
    input_data: Any,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create one root trace around a complete agent request.

    LangChain/LangGraph callbacks created inside this context become child
    observations. A deterministic trace id derived from the public run id lets
    the feedback endpoint attach scores to the same trace later.
    """
    client = get_langfuse_client()
    if client is None:
        yield None
        return

    trace_id = client.create_trace_id(seed=run_id)
    trace_name = f"{agent_id}:{protocol}"
    trace_metadata = {
        "service": "agent-service-toolkit",
        "agent_id": agent_id,
        "protocol": protocol,
        "run_id": run_id,
        "model": model,
        **(metadata or {}),
    }
    tags = ["agent-service-toolkit", f"agent:{agent_id}", f"protocol:{protocol}"]

    with client.start_as_current_observation(
        trace_context={"trace_id": trace_id},
        name=trace_name,
        as_type="agent",
        input=input_data,
        metadata=trace_metadata,
    ) as observation:
        with propagate_attributes(
            trace_name=trace_name,
            user_id=user_id,
            session_id=thread_id,
            tags=tags,
            metadata=trace_metadata,
            environment=settings.LANGFUSE_ENVIRONMENT,
            version=settings.LANGFUSE_RELEASE,
        ):
            yield observation


def flush_langfuse() -> None:
    """Flush queued telemetry without making shutdown depend on observability."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.exception("Failed to flush Langfuse telemetry")


__all__ = [
    "flush_langfuse",
    "get_langfuse_client",
    "get_langfuse_handler",
    "observe_agent_run",
]
