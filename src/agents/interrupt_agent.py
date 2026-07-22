import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from langchain_core.language_models.base import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import SystemMessagePromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from core import get_model, settings

# Added logger
logger = logging.getLogger(__name__)


class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.

    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """

    birthdate: datetime | None
    birthdate_deleted: bool
    background_summary: str
    user_request: str


def _latest_human_message(messages: Sequence[BaseMessage]) -> str:
    """Return the most recent human message as plain text."""
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        if isinstance(message.content, str):
            return message.content
        return "".join(
            item if isinstance(item, str) else str(item.get("text", "")) for item in message.content
        )
    return ""


def wrap_model(
    model: BaseChatModel | Runnable[LanguageModelInput, Any], system_prompt: BaseMessage
) -> RunnableSerializable[AgentState, Any]:
    preprocessor = RunnableLambda(
        lambda state: [system_prompt] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model


background_prompt = SystemMessagePromptTemplate.from_template("""
You are a helpful assistant that tells users there zodiac sign.
Provide a one sentence summary of the origin of zodiac signs.
Don't tell the user what their sign is, you are just demonstrating your knowledge on the topic.
""")


async def background(state: AgentState, config: RunnableConfig) -> AgentState:
    """This node is to demonstrate doing work before the interrupt"""

    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    model_runnable = wrap_model(m, background_prompt.format())
    response = await model_runnable.ainvoke(state, config)

    return {
        # This is internal graph context, not an assistant turn visible to the user.
        # Keeping it out of `messages` prevents it from polluting chat history or
        # leaving the model input terminated by an internal AIMessage.
        "background_summary": str(response.content),
        "messages": [],
    }


birthdate_extraction_prompt = SystemMessagePromptTemplate.from_template("""
You manage a user's stored birthdate. Analyze only the latest user message supplied to you.

Previously stored birthday: {stored_birthdate}

Choose exactly one action:
- "none": the user did not explicitly provide, correct, or delete a birthdate
- "set": the user explicitly provided their birthdate
- "correct": the user explicitly corrected a previously stated or stored birthdate
- "delete": the user explicitly asked to forget or delete their stored birthdate

Rules:
- Never extract a date that the user merely asks about or mentions as someone else's birthdate.
- Accept common date formats and normalize an explicit birthdate to YYYY-MM-DD.
- Reject impossible dates and future dates.
- For "none" and "delete", birthdate must be null.
""")


class BirthdateExtraction(BaseModel):
    action: Literal["none", "set", "correct", "delete"] = Field(
        description="The explicit profile operation requested by the latest user message."
    )
    birthdate: str | None = Field(
        description="The explicit birthdate in YYYY-MM-DD format for set/correct; otherwise None."
    )
    reasoning: str = Field(
        description="Explanation of how the birthdate was extracted or why no birthdate was found"
    )


async def _extract_birthdate_change(
    latest_user_message: str, config: RunnableConfig,stored_birthdate:datetime | None
) -> BirthdateExtraction:
    """Classify a profile change using only the current user turn."""
    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    model_runnable = wrap_model(
        m.with_structured_output(BirthdateExtraction), birthdate_extraction_prompt.format(stored_birthdate=stored_birthdate)
    ).with_config(tags=["skip_stream"])
    extraction_state: AgentState = {
        "messages": [HumanMessage(content=latest_user_message)],
    }
    return await model_runnable.ainvoke(extraction_state, config)


def _stored_birthdate(result: Any) -> datetime | None:
    """Read a birthdate from either an Item or the legacy list-shaped result."""
    if not result:
        return None
    user_data = result[0] if isinstance(result, list) and result else result
    birthdate_value = user_data.value.get("birthdate") if user_data else None
    return datetime.fromisoformat(birthdate_value) if birthdate_value else None


async def _record_birthdate_change(
    store: BaseStore,
    namespace: tuple[str, ...],
    old_birthdate: datetime | None,
    new_birthdate: datetime | None,
    action: str,
) -> None:
    """Best-effort audit trail for explicit profile changes."""
    try:
        await store.aput(
            (*namespace, "profile_history", "birthdate"),
            str(uuid4()),
            {
                "action": action,
                "old_value": old_birthdate.isoformat() if old_birthdate else None,
                "new_value": new_birthdate.isoformat() if new_birthdate else None,
                "changed_at": datetime.now().astimezone().isoformat(),
                "source": "explicit_user_message",
            },
        )
    except Exception:
        logger.warning("Failed to write birthdate audit history for %s", namespace, exc_info=True)


async def determine_birthdate(
    state: AgentState, config: RunnableConfig, store: BaseStore
) -> AgentState:
    """Resolve an explicit profile change before falling back to the stored birthdate."""

    # Attempt to get user_id for unique storage per user
    user_id = config["configurable"].get("user_id")
    logger.info(f"[determine_birthdate] Extracted user_id: {user_id}")
    namespace = None
    key = "birthdate"
    stored_birthdate = None

    if user_id:
        namespace = (user_id,)
        try:
            result = await store.aget(namespace, key=key)
            stored_birthdate = _stored_birthdate(result)
            if stored_birthdate:
                logger.info(
                    "[determine_birthdate] Found birthdate in store for user %s: %s",
                    user_id,
                    stored_birthdate,
                )
        except Exception as e:
            logger.error("Error reading from store for namespace %s, key %s: %s", namespace, key, e)
    else:
        logger.warning(
            "Warning: user_id not found in config. Skipping persistent birthdate storage/retrieval for this run."
        )

    latest_user_message = _latest_human_message(state.get("messages", []))
    response = await _extract_birthdate_change(latest_user_message, config,stored_birthdate=stored_birthdate)

    if response.action == "delete":
        if namespace:
            try:
                await store.adelete(namespace, key)
            except Exception as e:
                logger.error("Error deleting birthdate for namespace %s: %s", namespace, e)
                raise RuntimeError("Failed to delete the stored birthdate") from e
            await _record_birthdate_change(
                store, namespace, stored_birthdate, None, response.action
            )
        return {"birthdate": None, "birthdate_deleted": True, "messages": []}

    if response.action == "none":
        if stored_birthdate:
            return {
                "birthdate": stored_birthdate,
                "birthdate_deleted": False,
                "messages": [],
            }
        birthdate_input = interrupt("Please tell me your birthdate?")
        state["messages"].append(HumanMessage(birthdate_input))
        return await determine_birthdate(state, config, store)

    if not response.birthdate:
        birthdate_input = interrupt("Please provide the new birthdate in YYYY-MM-DD format.")
        state["messages"].append(HumanMessage(birthdate_input))
        return await determine_birthdate(state, config, store)

    try:
        birthdate = datetime.fromisoformat(response.birthdate)
    except ValueError:
        birthdate_input = interrupt(
            "I couldn't understand the date format. Please provide your birthdate in YYYY-MM-DD format."
        )
        state["messages"].append(HumanMessage(birthdate_input))
        return await determine_birthdate(state, config, store)

    if namespace:
        try:
            await store.aput(
                namespace,
                key,
                {
                    "birthdate": birthdate.isoformat(),
                    "updated_at": datetime.now().astimezone().isoformat(),
                    "source": "explicit_user_message",
                },
            )
        except Exception as e:
            logger.error("Error writing birthdate for namespace %s: %s", namespace, e)
            raise RuntimeError("Failed to update the stored birthdate") from e
        await _record_birthdate_change(
            store, namespace, stored_birthdate, birthdate, response.action
        )

    logger.info("[determine_birthdate] Returning birthdate %s for user %s", birthdate, user_id)
    return {
        "birthdate": birthdate,
        "birthdate_deleted": False,
        "messages": [],
    }


response_prompt = SystemMessagePromptTemplate.from_template("""
You are a helpful assistant.

Known information:
- The user's birthdate is {birthdate_str}

Based on the user's birthday, explain their zodiac sign, the meaning of the zodiac sign,
 and the corresponding strengths and weaknesses of the personality.
""")


async def generate_response(state: AgentState, config: RunnableConfig) -> AgentState:
    """Generates the final response based on the user's query and the available birthdate."""
    birthdate = state.get("birthdate")

    if state.get("birthdate_deleted"):
        return {"messages": [AIMessage(content="I've deleted your stored birthdate.")]}

    if not birthdate:
        # This should ideally not be reached if determine_birthdate worked correctly and possibly interrupted.
        # Handle cases where birthdate might still be missing.
        return {
            "messages": [
                AIMessage(
                    content="I couldn't determine your birthdate. Could you please provide it?"
                )
            ]
        }

    birthdate_str = birthdate.strftime("%B %d, %Y")  # Format for display
    conversation_messages = list(state.get("messages", []))
    if not conversation_messages:
        return {
            "messages": [
                AIMessage(content="I couldn't find the conversation context. Please try again.")
            ]
        }

    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    system_prompt = response_prompt.format(
        birthdate_str=birthdate_str,
    )

    # MessagesState plus the checkpointer contains the conversation accumulated for
    # this thread_id. Pass it intact so follow-up questions retain their context.
    # Internal node output such as `background_summary` is deliberately stored in a
    # separate state field and therefore cannot masquerade as a conversation turn.
    response = await m.ainvoke(
        [system_prompt, *conversation_messages],
        config,
    )

    if not response.content:
        logger.error(
            "[generate_response] Model returned empty content for conversation ending with: %r",
            conversation_messages[-1],
        )
        return {
            "messages": [AIMessage(content="I couldn't generate a response. Please try again.")]
        }

    return {"messages": [AIMessage(content=response.content)]}


# Define the graph
agent = StateGraph(AgentState)
# agent.add_node("background", background)
agent.add_node("determine_birthdate", determine_birthdate)
agent.add_node("generate_response", generate_response)

agent.set_entry_point("determine_birthdate")

# agent.add_edge("background", "determine_birthdate")
agent.add_edge("determine_birthdate", "generate_response")
agent.add_edge("generate_response", END)

interrupt_agent = agent.compile()
interrupt_agent.name = "interrupt-agent"
