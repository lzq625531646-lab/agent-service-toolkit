"""AG-UI protocol endpoint for the agent service.

Exposes any agent in the service over the AG-UI protocol (https://docs.ag-ui.com)
so it can be used with AG-UI compatible frontends like CopilotKit. The
LangGraph -> AG-UI event translation is handled by the official `ag-ui-langgraph`
package; this module only wires it into the service's agent registry, auth, and
tracing.

See docs/AGUI.md for usage, including how to connect a client.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from ag_ui.core import EventType, RunAgentInput
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph import LangGraphAgent
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig

from agents import DEFAULT_AGENT, AgentGraph, get_agent
from auth import ConversationAccessError, user_store
from core import settings
from core.observability import get_langfuse_handler, observe_agent_run
from service.auth import AuthContext, get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agui")

# Managed by the protocol (thread_id comes from RunAgentInput) or the checkpointer,
# so clients may not override them via forwardedProps.configurable.
RESERVED_CONFIGURABLE_KEYS = {"thread_id", "checkpoint_id", "checkpoint_ns"}


def _base_config(input_data: RunAgentInput) -> RunnableConfig:
    """Build the base RunnableConfig for an AG-UI run.

    Clients can pass configurable values (e.g. `model`, `user_id`, or custom agent
    config) in `forwardedProps.configurable` - the AG-UI equivalent of the vanilla
    API's `model` / `user_id` / `agent_config` fields. `thread_id` is taken from
    the AG-UI input by the `ag-ui-langgraph` package itself.
    """
    forwarded: dict[str, Any] = input_data.forwarded_props or {}
    configurable = forwarded.get("configurable") or {}
    if not isinstance(configurable, dict):
        raise HTTPException(status_code=422, detail="forwardedProps.configurable must be an object")
    if overlap := RESERVED_CONFIGURABLE_KEYS & configurable.keys():
        raise HTTPException(
            status_code=422,
            detail=f"forwardedProps.configurable contains reserved keys: {overlap}",
        )

    callbacks: list[Any] = []
    if langfuse_handler := get_langfuse_handler():
        callbacks.append(langfuse_handler)

    return RunnableConfig(configurable=dict(configurable), callbacks=callbacks)


def _conversation_title(input_data: RunAgentInput) -> str:
    for message in input_data.messages:
        if message.role == "user" and isinstance(message.content, str):
            compact = " ".join(message.content.split())
            return compact[:80] or "New conversation"
    return "New conversation"


async def _prepare_config(
    input_data: RunAgentInput,
    auth: AuthContext,
    agent_id: str,
) -> RunnableConfig:
    config = _base_config(input_data)
    if auth.user is None:
        return config

    configurable = config.setdefault("configurable", {})
    configurable["user_id"] = str(auth.user.id)
    model = str(configurable.get("model", settings.DEFAULT_MODEL))
    try:
        await user_store.ensure_conversation(
            thread_id=input_data.thread_id,
            user_id=auth.user.id,
            title=_conversation_title(input_data),
            agent_id=agent_id,
            model=model,
        )
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc
    return config


async def _event_stream(
    agent_id: str,
    graph: AgentGraph,
    input_data: RunAgentInput,
    config: RunnableConfig,
    encoder: EventEncoder,
) -> AsyncGenerator[str, None]:
    # A new LangGraphAgent per request: it holds per-run state and is cheap to build.
    agent = LangGraphAgent(name=agent_id, graph=graph, config=config)  # type: ignore[arg-type]
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")
    model = configurable.get("model", settings.DEFAULT_MODEL)
    event_counts: dict[str, int] = {}
    with observe_agent_run(
        agent_id=agent_id,
        protocol="agui",
        run_id=input_data.run_id,
        thread_id=input_data.thread_id,
        user_id=str(user_id) if user_id is not None else None,
        model=str(model),
        input_data=input_data.model_dump(mode="json", by_alias=True),
        metadata={"streaming": True, "transport": "sse"},
    ) as observation:
        try:
            async for event in agent.run(input_data):
                event_name = str(event.type)
                event_counts[event_name] = event_counts.get(event_name, 0) + 1
                # Don't forward RAW passthrough events. Standard AG-UI clients ignore them,
                # and they expose server-side internals - including fully rendered prompts
                # from on_chat_model_start - to the caller. Remove this filter only if the
                # endpoint is consumed by a trusted middle layer and you want the full
                # event firehose (e.g. for the AG-UI Event Inspector).
                if event.type == EventType.RAW:
                    continue
                yield encoder.encode(event)
            if observation is not None:
                observation.update(output={"status": "completed", "event_counts": event_counts})
        except Exception as e:
            if observation is not None:
                observation.update(
                    output={"status": "error", "event_counts": event_counts},
                    level="ERROR",
                    status_message=str(e),
                )
            logger.exception("AG-UI run failed for agent %s: %s", agent_id, e)
            raise


@router.post("/run", operation_id="agui_run_default")
@router.post("/{agent_id}/run", operation_id="agui_run")
async def agui_run(
    input_data: RunAgentInput,
    request: Request,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    agent_id: str = DEFAULT_AGENT,
) -> StreamingResponse:
    """
    Run an agent over the AG-UI protocol, streaming AG-UI events via SSE.

    Point an AG-UI client (e.g. CopilotKit's runtime or HttpAgent) at this endpoint.
    Use the same threadId across runs to continue a conversation - threads are
    persisted in the service's checkpointer and shared with the vanilla API.
    """
    try:
        graph: AgentGraph = get_agent(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    config = await _prepare_config(input_data, auth, agent_id)
    encoder = EventEncoder(accept=request.headers.get("accept", ""))
    return StreamingResponse(
        _event_stream(agent_id, graph, input_data, config, encoder),
        media_type=encoder.get_content_type(),
    )
