"""OpenAI Agents SDK agent wired to OpenRouter.

Builds the digital-twin ``Agent`` (system prompt from ``knowledge.py``, the FAQ /
push tools, and a narrowly-scoped web-fetch MCP server) backed by an
OpenRouter-hosted model, and exposes ``stream_reply`` which runs the agent and
yields normalized stream pieces:

- ``{"type": "token", "text": <delta>}`` for streamed text,
- ``{"type": "tool", "phase": "calling"|"done", "name": <tool>, "detail": <str?>}``
  for tool invocations and their results,
- ``{"type": "error", "message": <str>}`` on failure.

The OpenAI client and model are created lazily so importing this module never
requires an API key or a network connection. The fetch MCP server is started per
chat turn (per ``reference/fetch.ipynb``); if it can't start, the turn proceeds
with just the FAQ and push tools.
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any, AsyncIterator

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from agents.mcp import MCPServerStdio
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent

from . import db, knowledge, notifications
from .config import settings

logger = logging.getLogger("avatar.agent")

# No OpenAI key is set; we only talk to OpenRouter, so disable tracing exports.
set_tracing_disabled(True)

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


@function_tool
def faq_tool(question_number: int) -> str:
    """Look up a frequently-asked question by its number.

    Returns the canonical question and answer for that FAQ so you can relay it
    verbatim. If the number is unknown, says so.

    Args:
        question_number: The FAQ number to look up.
    """
    row = None
    try:
        row = db.get_faq(question_number)
    except Exception:  # pragma: no cover - defensive; fall back to the seed
        logger.exception("faq_tool DB lookup failed; using seed FAQ")
    if row is None:
        row = knowledge.seed_faq(question_number)
    if row is None:
        return (
            f"There is no FAQ number {question_number}. Do not invent an answer; "
            "answer from your other knowledge or use push_tool if you cannot."
        )
    return knowledge.format_faq_answer(row)


@function_tool
def push_tool(message: str) -> str:
    """Send a push notification to the human operator (your human twin).

    Use this when the visitor wants to get in touch (push their email and
    request) or when you cannot answer a question (push the question).

    Args:
        message: The message to send to the human operator.
    """
    return notifications.push_human(message)


# --- Agent construction ------------------------------------------------------


def build_agent(
    owner_name: str,
    system_prompt: str | None = None,
    *,
    mcp_servers: list[Any] | None = None,
) -> Agent:
    """Build the digital-twin agent for the given owner name.

    ``system_prompt`` is the fully-composed prompt (built by the caller with the
    live FAQ list and the admin's additional instructions). When omitted it is
    built from the seed knowledge so the function stays usable on its own.
    """
    if system_prompt is None:
        system_prompt = knowledge.build_system_prompt(owner_name)
    return Agent(
        name="Avatar",
        instructions=system_prompt,
        model=_get_model(),
        model_settings=ModelSettings(max_tokens=settings.MODEL_MAX_TOKENS),
        tools=[faq_tool, push_tool],
        mcp_servers=mcp_servers or [],
    )


def _fetch_mcp_params() -> dict[str, Any] | None:
    """Resolve the stdio params for the web-fetch MCP server, or None if disabled.

    Prefers a pre-installed ``mcp-server-fetch`` on PATH (the Docker image) so the
    first request pays no download; otherwise falls back to the configured command
    (``uvx mcp-server-fetch`` by default for local dev).
    """
    command = settings.FETCH_MCP_COMMAND.strip()
    if not command:
        return None
    direct = shutil.which("mcp-server-fetch")
    if direct:
        return {"command": direct, "args": []}
    resolved = shutil.which(command) or command
    args = settings.FETCH_MCP_ARGS.split() if settings.FETCH_MCP_ARGS else []
    return {"command": resolved, "args": args}


# --- Stream parsing helpers --------------------------------------------------


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
    """Best-effort short detail (FAQ number, pushed text, or fetched URL)."""
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
    if "question_number" in parsed:
        return f"Q{parsed['question_number']}"
    if "url" in parsed:
        text = str(parsed["url"])
        return text[:80] + ("…" if len(text) > 80 else "")
    if "message" in parsed:
        text = str(parsed["message"])
        return text[:60] + ("…" if len(text) > 60 else "")
    return None


def _was_truncated(result: Any) -> bool:
    """True if the last model response hit the output-token ceiling."""
    try:
        responses = getattr(result, "raw_responses", None) or []
        if not responses:
            return False
        usage = getattr(responses[-1], "usage", None)
        out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return out_tokens >= settings.MODEL_MAX_TOKENS
    except Exception:  # pragma: no cover - defensive
        return False


async def _run_streamed(
    agent: Agent, task: str
) -> AsyncIterator[dict[str, Any]]:
    """Run ``agent`` on ``task`` and yield normalized stream pieces."""
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
        notifications.push_error("chat", str(exc))
        yield {"type": "error", "message": str(exc)}
        return

    if _was_truncated(result):
        yield {
            "type": "token",
            "text": "\n\n_(I kept that reply brief to stay within length limits.)_",
        }


async def stream_reply(
    task: str, owner_name: str, system_prompt: str | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Run the agent on ``task`` and yield normalized stream pieces.

    Starts the fetch MCP server for the turn (best effort — the turn proceeds
    without it if it can't start), builds the agent with the supplied
    ``system_prompt``, and streams the reply. Errors are surfaced as a final
    ``error`` piece (and alert the owner via Pushover).
    """
    if system_prompt is None:
        system_prompt = knowledge.build_system_prompt(owner_name)

    server = None
    params = _fetch_mcp_params()
    if params is not None:
        try:
            server = MCPServerStdio(
                params,
                cache_tools_list=True,
                client_session_timeout_seconds=240,
                name="fetch",
            )
            await server.connect()
        except Exception as exc:  # pragma: no cover - env-dependent
            logger.warning(
                "Fetch MCP server unavailable (%s); continuing without it", exc
            )
            server = None

    try:
        agent = build_agent(
            owner_name,
            system_prompt,
            mcp_servers=[server] if server is not None else [],
        )
        async for piece in _run_streamed(agent, task):
            yield piece
    finally:
        if server is not None:
            try:
                await server.cleanup()
            except Exception:  # pragma: no cover - best-effort teardown
                logger.debug("Fetch MCP cleanup failed", exc_info=True)


__all__ = [
    "faq_tool",
    "push_tool",
    "build_agent",
    "stream_reply",
]
