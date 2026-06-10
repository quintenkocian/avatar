"""Knowledge loading and prompt composition.

Loads the owner's knowledge corpus (``knowledge.md``, ``style.md``, ``faq.jsonl``)
from ``KNOWLEDGE_DIR`` once at import time and exposes helpers to:

- look up a single FAQ by number (for the ``faq_tool`` and the ``Qn`` shortcut),
- build the agent's system prompt for a given owner name,
- render the whole conversation as a single user task.

No network access happens here; this module is safe to import in tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import settings

logger = logging.getLogger("avatar.knowledge")


def _read_text(path: Path) -> str:
    """Read a text file, returning an empty string (with a warning) if missing."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Knowledge file not found: %s", path)
        return ""


def _load_faqs(path: Path) -> list[dict]:
    """Load the JSONL FAQ file into a list of dicts.

    Each row is expected to carry ``faq`` (int), ``question``, ``answer`` and a
    short ``query`` used for routing. Malformed lines are skipped with a warning
    so a single bad row never breaks startup.
    """
    faqs: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("FAQ file not found: %s", path)
        return faqs

    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed FAQ line %d in %s", line_no, path)
            continue
        # Normalise: ensure the keys we rely on exist with sensible defaults.
        faqs.append(
            {
                "faq": int(row.get("faq", line_no)),
                "question": str(row.get("question", "")),
                "answer": str(row.get("answer", "")),
                "query": str(row.get("query", "")),
            }
        )
    return faqs


# --- Module-level cache (loaded once) ----------------------------------------

KNOWLEDGE_MD: str = _read_text(settings.KNOWLEDGE_DIR / "knowledge.md")
STYLE_MD: str = _read_text(settings.KNOWLEDGE_DIR / "style.md")
FAQS: list[dict] = _load_faqs(settings.KNOWLEDGE_DIR / "faq.jsonl")
FAQ_BY_NUMBER: dict[int, dict] = {row["faq"]: row for row in FAQS}


# --- FAQ lookups -------------------------------------------------------------


def find_faq(n: int) -> str | None:
    """Return a formatted question+answer block for FAQ ``n``, or None.

    Used by the ``faq_tool`` so the model relays the canonical answer verbatim.
    """
    row = FAQ_BY_NUMBER.get(n)
    if row is None:
        return None
    return f"### Question {n}\n{row['question']}\n\n### Answer\n{row['answer']}"


def instant_answer_markdown(n: int) -> str | None:
    """Return the visitor-facing instant reply for the ``Qn`` shortcut, or None.

    Restates the question before the answer, per the SPEC, e.g.::

        **Q2:** What is your educational background?

        I have two undergraduate degrees...
    """
    row = FAQ_BY_NUMBER.get(n)
    if row is None:
        return None
    return f"**Q{n}:** {row['question']}\n\n{row['answer']}"


# --- Prompt composition ------------------------------------------------------


def build_system_prompt(owner_name: str) -> str:
    """Compose the agent's system prompt for the given owner.

    The prompt explains the three-way (visitor / avatar / human) setup, embeds
    the owner's knowledge and style guides, lists the FAQ routing phrasings, and
    documents the two tools.
    """
    role = (
        f"# Your role\n\n"
        f"You are the AI **digital twin** of {owner_name}, running on "
        f"{owner_name}'s personal website and chatting with visitors. You speak "
        f"in the first person as {owner_name}'s twin, representing them faithfully "
        f"using the knowledge below. If a visitor asks, say plainly that you are "
        f"an AI digital twin of {owner_name}.\n\n"
        f"## The three-way conversation\n\n"
        f"This is not a normal one-on-one chat. There are three possible "
        f"participants:\n"
        f"- **Visitor** — the person browsing the site, who you are replying to.\n"
        f"- **Avatar (you)** — the digital twin, that is you.\n"
        f"- **{owner_name} (the human)** — the real {owner_name}, who may join the "
        f"conversation asynchronously from an admin dashboard and post their own "
        f"messages.\n\n"
        f"The full transcript you are given below labels every line with its "
        f"speaker. When {owner_name} (the human) has posted, their message is "
        f"already in the transcript and visible to the visitor. Do NOT impersonate "
        f"the human or repeat what they said as if it were yours. Instead, build "
        f"naturally on what they contributed. You only ever speak as the Avatar; "
        f"respond to the latest Visitor message.\n"
    )

    knowledge_block = (
        "# Everything about " + owner_name + "\n\n" + KNOWLEDGE_MD.strip()
    )

    style_block = "# How to respond\n\n" + STYLE_MD.strip()

    faq_lines = "".join(f"\n{row['faq']}. {row['query']}" for row in FAQS)
    faq_block = (
        "# FAQ routing\n\n"
        "Your faq_tool returns canonical answers by number. If the visitor's "
        "question matches one of these, call faq_tool with that number and relay "
        "the answer verbatim in markdown (keep any links as markdown links). The "
        "numbered routing phrasings are:\n" + faq_lines
    )

    tools_block = (
        "# Tools\n\n"
        "You have two tools. Make tool calls in parallel where useful.\n\n"
        "- **faq_tool(question_number: int)** — returns the canonical question and "
        "answer for that FAQ number. Use it when the visitor's question matches a "
        "routing phrasing above; relay the returned answer verbatim in markdown.\n"
        f"- **push_tool(message: str)** — sends a push notification to the real "
        f"{owner_name}. Use it in two situations:\n"
        f"  1. The visitor wants to get in touch with {owner_name}. First ask for "
        f"their email, then push their email and what they want so {owner_name} can "
        f"follow up.\n"
        f"  2. You cannot answer a question from your knowledge. Push the question "
        f"to {owner_name}, then tell the visitor you've notified {owner_name} and "
        f"that they'll follow up. Never invent an answer.\n\n"
        "Never make up information. Answer only from the knowledge above or your "
        "general technical knowledge, and stay in character as the digital twin."
    )

    return "\n\n".join(
        [role, knowledge_block, style_block, faq_block, tools_block]
    ).strip()


def _role_label(role: str, owner_name: str) -> str:
    """Map a stored role to its transcript label."""
    if role == "visitor":
        return "Visitor"
    if role == "avatar":
        return "Avatar (you)"
    if role == "human":
        return f"{owner_name} (the human)"
    return role.capitalize()


def build_user_task(
    messages: list[dict], owner_name: str, pending_visitor: str | None = None
) -> str:
    """Render the whole conversation as a single user task.

    ``messages`` is the stored conversation in chronological order. The latest
    visitor row that we want answered is normally already the last element of
    ``messages`` (the chat route stores it before building the task). For callers
    that pass the prior history plus a separate ``pending_visitor`` string, the
    pending line is appended explicitly. Passing both an in-list pending line and
    a ``pending_visitor`` would duplicate it, so callers pick exactly one.
    """
    lines: list[str] = [
        "Here is the full conversation so far. Respond as the Avatar to the "
        "latest Visitor message.",
        "",
    ]
    for row in messages:
        label = _role_label(row.get("role", ""), owner_name)
        content = (row.get("content") or "").strip()
        lines.append(f"{label}: {content}")

    if pending_visitor is not None:
        lines.append(f"Visitor: {pending_visitor.strip()}")

    return "\n".join(lines).strip()


__all__ = [
    "KNOWLEDGE_MD",
    "STYLE_MD",
    "FAQS",
    "FAQ_BY_NUMBER",
    "find_faq",
    "instant_answer_markdown",
    "build_system_prompt",
    "build_user_task",
]
