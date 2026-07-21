import inspect
import json
import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, Interrupt
from langsmith import uuid7

from agents import DEFAULT_AGENT, AgentGraph, get_agent, get_all_agent_info, load_agent
from auth import ConversationAccessError, ConversationRecord, UserRecord, user_store
from core import settings
from core.observability import (
    flush_langfuse,
    get_langfuse_client,
    get_langfuse_handler,
    observe_agent_run,
)
from core.settings import DatabaseType
from memory import initialize_database, initialize_store
from rag import rag_store
from schema import (
    ChatHistory,
    ChatHistoryInput,
    ChatMessage,
    Conversation,
    Feedback,
    FeedbackResponse,
    ServiceMetadata,
    StreamInput,
    UserInput,
)
from service.agui import router as agui_router
from service.auth import AuthContext, get_auth_context, get_current_user
from service.auth import router as auth_router
from service.rag import router as rag_router
from service.utils import (
    convert_message_content_to_string,
    langchain_to_chat_message,
    remove_tool_calls,
)

warnings.filterwarnings("ignore", category=LangChainBetaWarning)
logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate idiomatic operation IDs for OpenAPI client generation."""
    return route.name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Configurable lifespan that initializes the appropriate database checkpointer, store,
    and agents with async loading - for example for starting up MCP clients.
    """
    try:
        # Initialize both checkpointer (for short-term memory) and store (for long-term memory)
        async with initialize_database() as saver, initialize_store() as store:
            user_store_open = settings.DATABASE_TYPE == DatabaseType.POSTGRES
            if user_store_open:
                await user_store.open()
            else:
                logger.warning(
                    "User registration and conversation indexing require DATABASE_TYPE=postgres; "
                    "only AUTH_SECRET service access is available with this database backend."
                )
            await rag_store.open()
            try:
                # Set up both components
                if hasattr(saver, "setup"):  # ignore: union-attr
                    await saver.setup()
                # Only setup store for Postgres as InMemoryStore doesn't need setup
                if hasattr(store, "setup"):  # ignore: union-attr
                    await store.setup()

                if not settings.AUTH_SECRET:
                    logger.info(
                        "AUTH_SECRET is not configured; browser users must authenticate with "
                        "an account session and service-to-service secret access is disabled."
                    )

                # Configure agents with both memory components and async loading
                agents = get_all_agent_info()
                for a in agents:
                    try:
                        await load_agent(a.key)
                        logger.info(f"Agent loaded: {a.key}")
                    except Exception as e:
                        logger.exception("Failed to load agent %s: %s", a.key, e)
                        # Continue with other agents rather than failing startup

                    agent = get_agent(a.key)
                    # Set checkpointer for thread-scoped memory (conversation history)
                    agent.checkpointer = saver
                    # Set store for long-term memory (cross-conversation knowledge)
                    agent.store = store
                yield
            finally:
                await rag_store.close()
                if user_store_open:
                    await user_store.close()
                flush_langfuse()
    except Exception as e:
        logger.exception("Error during database/store/agents initialization: %s", e)
        raise


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
router = APIRouter(dependencies=[Depends(get_auth_context)])
# AG-UI protocol endpoints inherit the same bearer auth - see service/agui.py
router.include_router(agui_router)
router.include_router(rag_router)


@router.get("/info")
async def info() -> ServiceMetadata:
    models = list(settings.AVAILABLE_MODELS)
    models.sort()
    return ServiceMetadata(
        agents=get_all_agent_info(),
        models=models,
        default_agent=DEFAULT_AGENT,
        default_model=settings.DEFAULT_MODEL,
    )


async def _handle_input(
    user_input: UserInput,
    agent: AgentGraph,
    run_id: UUID | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
) -> tuple[dict[str, Any], UUID]:
    """
    Parse user input and handle any required interrupt resumption.
    Returns kwargs for agent invocation and the run_id.
    """
    run_id = run_id or uuid7()
    thread_id = thread_id or user_input.thread_id or str(uuid4())
    user_id = user_id or user_input.user_id or str(uuid4())

    configurable = {"thread_id": thread_id, "user_id": user_id}
    if user_input.model is not None:
        configurable["model"] = user_input.model

    callbacks: list[Any] = []
    if langfuse_handler := get_langfuse_handler():
        callbacks.append(langfuse_handler)

    if user_input.agent_config:
        # Check for reserved keys (including 'model' even if not in configurable)
        reserved_keys = {"thread_id", "user_id", "model"}
        if overlap := reserved_keys & user_input.agent_config.keys():
            raise HTTPException(
                status_code=422,
                detail=f"agent_config contains reserved keys: {overlap}",
            )
        configurable.update(user_input.agent_config)

    config = RunnableConfig(
        configurable=configurable,
        run_id=run_id,
        callbacks=callbacks,
    )

    # Check for interrupts that need to be resumed
    state = await agent.aget_state(config=config)
    interrupted_tasks = [
        task for task in state.tasks if hasattr(task, "interrupts") and task.interrupts
    ]

    input: Command | dict[str, Any]
    if interrupted_tasks:
        # assume user input is response to resume agent execution from interrupt
        input = Command(resume=user_input.message)
    else:
        input = {"messages": [HumanMessage(content=user_input.message)]}

    kwargs = {
        "input": input,
        "config": config,
    }

    return kwargs, run_id


def _conversation_title(message: str) -> str:
    compact = " ".join(message.split())
    return compact[:80] or "New conversation"


async def _prepare_conversation(
    *,
    auth: AuthContext,
    user_input: UserInput,
    agent_id: str,
    thread_id: str,
    model: str,
) -> str:
    if auth.user is None:
        return user_input.user_id or str(uuid4())
    try:
        await user_store.ensure_conversation(
            thread_id=thread_id,
            user_id=auth.user.id,
            title=_conversation_title(user_input.message),
            agent_id=agent_id,
            model=model,
        )
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        ) from exc
    return str(auth.user.id)


@router.post("/{agent_id}/invoke", operation_id="invoke_with_agent_id")
@router.post("/invoke")
async def invoke(
    user_input: UserInput,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    agent_id: str = DEFAULT_AGENT,
) -> ChatMessage:
    """
    Invoke an agent with user input to retrieve a final response.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.
    """
    # NOTE: Currently this only returns the last message or interrupt.
    # In the case of an agent outputting multiple AIMessages (such as the background step
    # in interrupt-agent, or a tool step in research-assistant), it's omitted. Arguably,
    # you'd want to include it. You could update the API to return a list of ChatMessages
    # in that case.
    agent: AgentGraph = get_agent(agent_id)
    run_id = uuid7()
    thread_id = user_input.thread_id or str(uuid4())
    model = str(user_input.model or settings.DEFAULT_MODEL)
    user_id = await _prepare_conversation(
        auth=auth,
        user_input=user_input,
        agent_id=agent_id,
        thread_id=thread_id,
        model=model,
    )
    with observe_agent_run(
        agent_id=agent_id,
        protocol="invoke",
        run_id=str(run_id),
        thread_id=thread_id,
        user_id=user_id,
        model=model,
        input_data=user_input.model_dump(mode="json", exclude_none=True),
        metadata={"streaming": False},
    ) as observation:
        try:
            kwargs, _ = await _handle_input(user_input, agent, run_id, thread_id, user_id)
            response_events: list[tuple[str, Any]] = await agent.ainvoke(**kwargs, stream_mode=["updates", "values"])  # type: ignore # fmt: skip
            response_type, response = response_events[-1]
            if response_type == "values":
                # Normal response, the agent completed successfully
                output = langchain_to_chat_message(response["messages"][-1])
            elif response_type == "updates" and "__interrupt__" in response:
                # The last thing to occur was an interrupt
                # Return the value of the first interrupt as an AIMessage
                output = langchain_to_chat_message(
                    AIMessage(content=response["__interrupt__"][0].value)
                )
            else:
                raise ValueError(f"Unexpected response type: {response_type}")

            output.run_id = str(run_id)
            if observation is not None:
                observation.update(
                    output=output.model_dump(mode="json"),
                    metadata={"response_type": response_type},
                )
            if auth.user is not None:
                await user_store.touch_conversation(auth.user.id, thread_id)
            return output
        except HTTPException as e:
            if observation is not None:
                observation.update(level="WARNING", status_message=str(e.detail))
            raise
        except Exception as e:
            if observation is not None:
                observation.update(level="ERROR", status_message=str(e))
            logger.exception("Agent invocation failed for agent %s: %s", agent_id, e)
            raise HTTPException(status_code=500, detail="Unexpected error")


async def message_generator(
    user_input: StreamInput,
    agent_id: str = DEFAULT_AGENT,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    authenticated_user_id: UUID | None = None,
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    agent: AgentGraph = get_agent(agent_id)
    run_id = uuid7()
    thread_id = thread_id or user_input.thread_id or str(uuid4())
    user_id = user_id or user_input.user_id or str(uuid4())
    model = str(user_input.model or settings.DEFAULT_MODEL)
    with observe_agent_run(
        agent_id=agent_id,
        protocol="stream",
        run_id=str(run_id),
        thread_id=thread_id,
        user_id=user_id,
        model=model,
        input_data=user_input.model_dump(mode="json", exclude_none=True),
        metadata={"streaming": True, "stream_tokens": user_input.stream_tokens},
    ) as observation:
        event_count = 0
        token_character_count = 0
        try:
            kwargs, _ = await _handle_input(user_input, agent, run_id, thread_id, user_id)
            # Process streamed events from the graph and yield messages over the SSE stream.
            async for stream_event in agent.astream(
                **kwargs, stream_mode=["updates", "messages", "custom"], subgraphs=True
            ):
                event_count += 1
                if not isinstance(stream_event, tuple):
                    continue
                # Handle different stream event structures based on subgraphs
                if len(stream_event) == 3:
                    # With subgraphs=True: (node_path, stream_mode, event)
                    _, stream_mode, event = stream_event
                else:
                    # Without subgraphs: (stream_mode, event)
                    stream_mode, event = stream_event
                new_messages = []
                if stream_mode == "updates":
                    for node, updates in event.items():
                        # A simple approach to handle agent interrupts.
                        # In a more sophisticated implementation, we could add
                        # some structured ChatMessage type to return the interrupt value.
                        if node == "__interrupt__":
                            interrupt: Interrupt
                            for interrupt in updates:
                                new_messages.append(AIMessage(content=interrupt.value))
                            continue
                        updates = updates or {}
                        update_messages = updates.get("messages", [])
                        # special cases for using langgraph-supervisor library
                        if "supervisor" in node or "sub-agent" in node:
                            # the only tools that come from the actual agent are the handoff and handback tools
                            if isinstance(update_messages[-1], ToolMessage):
                                if "sub-agent" in node and len(update_messages) > 1:
                                    # If this is a sub-agent, we want to keep the last 2 messages - the handback tool, and it's result
                                    update_messages = update_messages[-2:]
                                else:
                                    # If this is a supervisor, we want to keep the last message only - the handoff result. The tool comes from the 'agent' node.
                                    update_messages = [update_messages[-1]]
                            else:
                                update_messages = []
                        new_messages.extend(update_messages)

                if stream_mode == "custom":
                    new_messages = [event]

                # LangGraph streaming may emit tuples: (field_name, field_value)
                # e.g. ('content', <str>), ('tool_calls', [ToolCall,...]), ('additional_kwargs', {...}), etc.
                # We accumulate only supported fields into `parts` and skip unsupported metadata.
                # More info at: https://langchain-ai.github.io/langgraph/cloud/how-tos/stream_messages/
                processed_messages = []
                current_message: dict[str, Any] = {}
                for message in new_messages:
                    if isinstance(message, tuple):
                        key, value = message
                        # Store parts in temporary dict
                        current_message[key] = value
                    else:
                        # Add complete message if we have one in progress
                        if current_message:
                            processed_messages.append(_create_ai_message(current_message))
                            current_message = {}
                        processed_messages.append(message)

                # Add any remaining message parts
                if current_message:
                    processed_messages.append(_create_ai_message(current_message))

                for message in processed_messages:
                    try:
                        chat_message = langchain_to_chat_message(message)
                        chat_message.run_id = str(run_id)
                    except Exception as e:
                        logger.exception("Error parsing streamed message: %s", e)
                        yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
                        continue
                    # LangGraph re-sends the input message, which feels weird, so drop it
                    if chat_message.type == "human" and chat_message.content == user_input.message:
                        continue
                    yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

                if stream_mode == "messages":
                    if not user_input.stream_tokens:
                        continue
                    msg, metadata = event
                    if "skip_stream" in metadata.get("tags", []):
                        continue
                    # For some reason, astream("messages") causes non-LLM nodes to send extra messages.
                    # Drop them.
                    if not isinstance(msg, AIMessageChunk):
                        continue
                    content = remove_tool_calls(msg.content)
                    if content:
                        # Empty content in the context of OpenAI usually means
                        # that the model is asking for a tool to be invoked.
                        # So we only print non-empty content.
                        token_content = convert_message_content_to_string(content)
                        token_character_count += len(token_content)
                        yield f"data: {json.dumps({'type': 'token', 'content': token_content})}\n\n"
            if observation is not None:
                observation.update(
                    output={"status": "completed"},
                    metadata={
                        "stream_event_count": event_count,
                        "streamed_token_characters": token_character_count,
                    },
                )
        except Exception as e:
            if observation is not None:
                observation.update(output={"status": "error"}, level="ERROR", status_message=str(e))
            logger.exception("Message generator failed for agent %s: %s", agent_id, e)
            yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'})}\n\n"
        finally:
            if authenticated_user_id is not None:
                try:
                    await user_store.touch_conversation(authenticated_user_id, thread_id)
                except Exception as e:
                    logger.warning("Failed to update conversation activity: %s", e, exc_info=True)
            yield "data: [DONE]\n\n"


def _create_ai_message(parts: dict) -> AIMessage:
    sig = inspect.signature(AIMessage)
    valid_keys = set(sig.parameters)
    filtered = {k: v for k, v in parts.items() if k in valid_keys}
    return AIMessage(**filtered)


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@router.post(
    "/{agent_id}/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
    operation_id="stream_with_agent_id",
)
@router.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream(
    user_input: StreamInput,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    agent_id: str = DEFAULT_AGENT,
) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    thread_id = user_input.thread_id or str(uuid4())
    model = str(user_input.model or settings.DEFAULT_MODEL)
    user_id = await _prepare_conversation(
        auth=auth,
        user_input=user_input,
        agent_id=agent_id,
        thread_id=thread_id,
        model=model,
    )
    return StreamingResponse(
        message_generator(
            user_input,
            agent_id,
            thread_id=thread_id,
            user_id=user_id,
            authenticated_user_id=auth.user.id if auth.user else None,
        ),
        media_type="text/event-stream",
    )


@router.post("/feedback")
async def feedback(feedback: Feedback) -> FeedbackResponse:
    """
    Record feedback for a run as a Langfuse trace score.

    Feedback remains best-effort so an observability outage does not break the
    user-facing request. The run ID deterministically maps to the same Langfuse
    trace ID used by the invoke and stream endpoints.
    """
    kwargs = feedback.kwargs or {}
    if langfuse := get_langfuse_client():
        try:
            langfuse.create_score(
                trace_id=langfuse.create_trace_id(seed=feedback.run_id),
                name=feedback.key,
                value=feedback.score,
                data_type="NUMERIC",
                comment=kwargs.get("comment"),
                metadata={"source": "feedback-api", **kwargs},
            )
        except Exception as e:
            logger.warning("Failed to record Langfuse feedback: %s", e, exc_info=True)
    else:
        logger.warning("Langfuse feedback skipped because Langfuse is disabled or unavailable")
    return FeedbackResponse()


async def _conversation_history(conversation: ConversationRecord) -> ChatHistory:
    agent: AgentGraph = get_agent(conversation.agent_id)
    config = RunnableConfig(configurable={"thread_id": conversation.thread_id})
    channels = getattr(agent, "channels", {})
    checkpointer: Any = agent.checkpointer
    if isinstance(channels, dict) and "__previous__" in channels and checkpointer:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        previous = (
            checkpoint_tuple.checkpoint["channel_values"].get("__previous__", {})
            if checkpoint_tuple
            else {}
        )
        messages: list[AnyMessage] = previous.get("messages", [])
    else:
        state_snapshot = await agent.aget_state(config=config)
        messages = state_snapshot.values.get("messages", [])
    return ChatHistory(messages=[langchain_to_chat_message(message) for message in messages])


@router.get("/conversations", response_model=list[Conversation])
async def conversations(
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> list[ConversationRecord]:
    return await user_store.list_conversations(user.id)


@router.get("/conversations/{thread_id}/messages", response_model=ChatHistory)
async def conversation_messages(
    thread_id: str,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> ChatHistory:
    conversation = await user_store.get_conversation(user.id, thread_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    try:
        return await _conversation_history(conversation)
    except Exception as e:
        logger.exception("Failed to retrieve history for thread %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail="Unexpected error") from e


@router.post("/history")
async def history(
    input: ChatHistoryInput,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> ChatHistory:
    """
    Get chat history.
    """
    if auth.user is not None:
        conversation = await user_store.get_conversation(auth.user.id, input.thread_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
    else:
        now = datetime.now().astimezone()
        conversation = ConversationRecord(
            thread_id=input.thread_id,
            user_id=UUID(int=0),
            title="Service conversation",
            agent_id=DEFAULT_AGENT,
            model=str(settings.DEFAULT_MODEL),
            created_at=now,
            updated_at=now,
        )
    try:
        return await _conversation_history(conversation)
    except Exception as e:
        logger.exception("Failed to retrieve history for thread %s: %s", input.thread_id, e)
        raise HTTPException(status_code=500, detail="Unexpected error") from e


@app.get("/health")
async def health_check():
    """Health check endpoint."""

    health_status = {"status": "ok"}

    if settings.LANGFUSE_TRACING:
        try:
            langfuse = get_langfuse_client()
            health_status["langfuse"] = (
                "connected" if langfuse is not None and langfuse.auth_check() else "disconnected"
            )
        except Exception as e:
            logger.exception("Langfuse health check failed: %s", e)
            health_status["langfuse"] = "disconnected"

    return health_status


app.include_router(router)
