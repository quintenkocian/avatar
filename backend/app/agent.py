"""OpenAI Agents SDK agent wired to OpenRouter.

Builds the digital-twin ``Agent`` (system prompt from ``knowledge.py``, the two
tools) backed by an OpenRouter-hosted model, and exposes ``stream_reply`` which
runs the agent and yields normalized stream pieces:

- ``{"type": "token", "text": <delta>}`` for streamed text,
- ``{"type": "tool", "phase": "calling"|"done", "name": <tool>, "detail": <str?>}``
  for tool invocations and their results.

The OpenAI client and model are created lazily so importing this module never
requires an API key or a network connection.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import requests
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent

from . import knowledge
from .config import settings

logger = logging.getLogger("avatar.agent")

# No OpenAI key is set; we only talk to OpenRouter, so disable tracing exports.
set_tracing_disabled(True)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Lazily-created singletons.
_client: AsyncOpenAI | None = None
_model: OpenAIChatCompletionsModel | None = None


def _get_model() -> OpenAIChatCompletionsModel:
    """Return the shared chat-completions model backed by OpenRouter."""
    global _client, _model
    if _model is None:
        _client = AsyncOpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
        )
        _model = OpenAIChatCompletionsModel(
            model=settings.MODEL, openai_client=_client
        )
    return _model


# --- Tools -------------------------------------------------------------------


def _push(message: str) -> str:
    """Send a Pushover notification. No-op (logged) if creds are missing."""
    if not settings.PUSHOVER_USER or not settings.PUSHOVER_TOKEN:
        logger.warning(
            "Pushover credentials missing; skipping push. Message was: %s",
            message,
        )
        return "Push notification skipped (operator notifications not configured)."
    try:
        resp = requests.post(
            PUSHOVER_URL,
            data={
                "user": settings.PUSHOVER_USER,
                "token": settings.PUSHOVER_TOKEN,
                "message": message,
            },
            timeout=10,
        )
        return f"Message pushed with status code {resp.status_code}."
    except requests.RequestException as exc:  # pragma: no cover - network error
        logger.warning("Pushover request failed: %s", exc)
        return "Push notification could not be delivered right now."


@function_tool
def faq_tool(question_number: int) -> str:
    """Look up a frequently-asked question by its number.

    Returns the canonical question and answer for that FAQ so you can relay it
    verbatim. If the number is unknown, says so.

    Args:
        question_number: The FAQ number to look up.
    """
    found = knowledge.find_faq(question_number)
    if found is None:
        return (
            f"There is no FAQ number {question_number}. Do not invent an answer; "
            "answer from your other knowledge or use push_tool if you cannot."
        )
    return found


@function_tool
def push_tool(message: str) -> str:
    """Send a push notification to the human operator (your human twin).

    Use this when the visitor wants to get in touch (push their email and
    request) or when you cannot answer a question (push the question).

    Args:
        message: The message to send to the human operator.
    """
    return _push(message)


# --- Agent construction ------------------------------------------------------


def build_agent(owner_name: str) -> Agent:
    """Build the digital-twin agent for the given owner name."""
    return Agent(
        name="Avatar",
        instructions=knowledge.build_system_prompt(owner_name),
        model=_get_model(),
        tools=[faq_tool, push_tool],
    )


def _tool_name(item: Any) -> str:
    """Best-effort extraction of a tool name from a stream item."""
    raw = getattr(item, "raw_item", None)
    for attr in ("name", "tool_name"):
        name = getattr(raw, attr, None)
        if name:
            return str(name)
    name = getattr(item, "name", None)
    return str(name) if name else "tool"


def _tool_detail(item: Any) -> str | None:
    """Best-effort short detail (e.g. the FAQ number) for a tool call."""
    raw = getattr(item, "raw_item", None)
    arguments = getattr(raw, "arguments", None)
    if not arguments:
        return None
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    # Prefer a compact, human-friendly detail.
    if "question_number" in parsed:
        return f"Q{parsed['question_number']}"
    if "message" in parsed:
        text = str(parsed["message"])
        return text[:60] + ("…" if len(text) > 60 else "")
    return None


async def stream_reply(
    task: str, owner_name: str
) -> AsyncIterator[dict[str, Any]]:
    """Run the agent on ``task`` and yield normalized stream pieces.

    Yields dicts of shape ``{"type": "token", ...}`` or ``{"type": "tool", ...}``.
    The caller accumulates ``token`` text into the final reply and collects the
    tool pieces for persistence. Errors are surfaced as a final ``error`` piece.
    """
    agent = build_agent(owner_name)
    result = Runner.run_streamed(agent, task)

    try:
        async for event in result.stream_events():
            etype = getattr(event, "type", None)

            if etype == "raw_response_event":
                data = getattr(event, "data", None)
                if isinstance(data, ResponseTextDeltaEvent):
                    delta = data.delta
                    if delta:
                        yield {"type": "token", "text": delta}
                continue

            if etype == "run_item_stream_event":
                item = getattr(event, "item", None)
                name = getattr(event, "name", None)
                if item is None:
                    continue
                if name == "tool_called":
                    yield {
                        "type": "tool",
                        "phase": "calling",
                        "name": _tool_name(item),
                        "detail": _tool_detail(item),
                    }
                elif name == "tool_output":
                    yield {
                        "type": "tool",
                        "phase": "done",
                        "name": _tool_name(item),
                        "detail": None,
                    }
                continue
    except Exception as exc:  # pragma: no cover - defensive against SDK/network
        logger.exception("Streaming agent run failed")
        yield {"type": "error", "message": str(exc)}


__all__ = [
    "faq_tool",
    "push_tool",
    "build_agent",
    "stream_reply",
]
