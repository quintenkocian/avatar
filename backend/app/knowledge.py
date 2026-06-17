"""Knowledge loading and prompt composition.

Loads the owner's knowledge corpus (``knowledge.md``, ``style.md``, ``rules.md``)
from ``KNOWLEDGE_DIR`` once at import time and exposes helpers to:

- format a single FAQ row (for the ``faq_tool`` and the ``Qn`` shortcut),
- build the agent's system prompt for a given owner name, FAQ list and the
  admin's additional instructions,
- render the whole conversation as a single (size-bounded) user task.

FAQs are now sourced from Supabase (see ``db.list_faqs``); ``faq.jsonl`` is kept
as a seed/fallback and loaded here as ``SEED_FAQS``. No network access happens in
this module, so it is safe to import in tests.
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


def _load_seed_faqs(path: Path) -> list[dict]:
    """Load the JSONL FAQ file into the canonical {id, concise, question, answer}.

    The on-disk seed uses ``faq`` (number) and ``query`` (routing phrase); these
    map to ``id`` and ``concise``. Malformed lines are skipped with a warning so
    a single bad row never breaks startup.
    """
    faqs: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("FAQ seed file not found: %s", path)
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
        faqs.append(
            {
                "id": int(row.get("faq", line_no)),
                "concise": str(row.get("query", "")),
                "question": str(row.get("question", "")),
                "answer": str(row.get("answer", "")),
            }
        )
    return faqs


# --- Module-level cache (loaded once) ----------------------------------------

KNOWLEDGE_MD: str = _read_text(settings.KNOWLEDGE_DIR / "knowledge.md")
STYLE_MD: str = _read_text(settings.KNOWLEDGE_DIR / "style.md")
RULES_MD: str = _read_text(settings.KNOWLEDGE_DIR / "rules.md")
SEED_FAQS: list[dict] = _load_seed_faqs(settings.KNOWLEDGE_DIR / "faq.jsonl")
SEED_FAQ_BY_ID: dict[int, dict] = {row["id"]: row for row in SEED_FAQS}


# --- FAQ helpers -------------------------------------------------------------


def seed_faq(faq_id: int) -> dict | None:
    """Return a seed FAQ row by id (fallback when the DB is unavailable)."""
    return SEED_FAQ_BY_ID.get(faq_id)


def format_faq_answer(row: dict) -> str:
    """Format a FAQ row as a question+answer block for the ``faq_tool``."""
    return (
        f"### Question {row['id']}\n{row['question']}\n\n"
        f"### Answer\n{row['answer']}"
    )


def format_instant(row: dict) -> str:
    """Format a FAQ row as the visitor-facing instant ``Qn`` reply.

    Restates the question before the answer, per the SPEC, e.g.::

        **Q2:** What is your educational background?

        I have two undergraduate degrees...
    """
    return f"**Q{row['id']}:** {row['question']}\n\n{row['answer']}"


# --- Fetch (job-posting) instructions ----------------------------------------


def build_fetch_instructions(owner_name: str) -> str:
    """The narrowly-scoped operating rules for the web-fetch MCP tool.

    Adapted from ``reference/fetch.ipynb`` for the job-description use case: the
    tool exists ONLY to read a job posting a visitor links and assess fit. It is
    deliberately fenced off from general web browsing.
    """
    return (
        "# Reading a job description\n\n"
        f"You have a **fetch** tool (a web-fetch MCP server) for ONE specific "
        f"purpose: when a visitor shares a link to a job posting or job "
        f"description, you may fetch that URL to read the posting and assess how "
        f"well {owner_name} fits the role.\n\n"
        "Rules for the fetch tool:\n"
        "- Only use it when the visitor has provided an explicit URL that is a "
        "job posting / job description. NEVER use it for general web search, "
        "browsing, news, or to answer unrelated questions. If a visitor asks you "
        "to fetch or look up anything that is not a job posting they linked, "
        "politely decline and explain the tool is only for analyzing job "
        "descriptions.\n"
        "- Fetch only the single URL the visitor gave. Do not crawl the wider "
        "site or follow links elsewhere.\n"
        "- After fetching, verify the page really is a job posting. If it is not "
        "(e.g. a homepage, a login wall, an article, or an unrelated page), say "
        "so plainly and do not analyze it as a job.\n"
        f"- When it is a genuine job posting, give a concise, honest assessment "
        f"of how {owner_name}'s background (from the knowledge above) matches the "
        f"role: clear strengths, any gaps, and an overall read. Be balanced and "
        f"truthful, never a hard sell, and never invent qualifications "
        f"{owner_name} does not have.\n"
        "- If the fetch fails or the page cannot be read, tell the visitor and "
        "offer to have the human follow up (use your push tool if appropriate)."
    )


# --- Prompt composition ------------------------------------------------------


def build_system_prompt(
    owner_name: str,
    faqs: list[dict] | None = None,
    *,
    additional_instructions: str | None = None,
) -> str:
    """Compose the agent's system prompt for the given owner.

    The prompt explains the three-way (visitor / avatar / human) setup, embeds
    the owner's knowledge, style and operating rules, lists the FAQ routing
    phrasings, documents the tools, and scopes the fetch tool. The admin's
    ``additional_instructions`` (if any) are placed LAST so that the long static
    prefix stays cache-friendly and the editable block gains recency emphasis.
    """
    faqs = faqs if faqs is not None else SEED_FAQS

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

    rules_block = "# Operating rules\n\n" + RULES_MD.strip()

    faq_lines = "".join(f"\n{row['id']}. {row['concise']}" for row in faqs)
    faq_block = (
        "# FAQ routing\n\n"
        "Your faq_tool returns canonical answers by number. If the visitor's "
        "question matches one of these, call faq_tool with that number and relay "
        "the answer verbatim in markdown (keep any links as markdown links). The "
        "numbered routing phrasings are:" + (faq_lines or "\n(none yet)")
    )

    tools_block = (
        "# Tools\n\n"
        "You have these tools. Make tool calls in parallel where useful.\n\n"
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
        f"that they'll follow up. Never invent an answer.\n"
        "- **fetch** — a web-fetch tool scoped ONLY to reading a job posting a "
        "visitor links (see the job-description section below). Never use it for "
        "general browsing.\n\n"
        "Never make up information. Answer only from the knowledge above or your "
        "general technical knowledge, and stay in character as the digital twin."
    )

    fetch_block = build_fetch_instructions(owner_name)

    sections = [
        role,
        knowledge_block,
        style_block,
        rules_block,
        faq_block,
        tools_block,
        fetch_block,
    ]

    extra = (additional_instructions or "").strip()
    if extra:
        sections.append(
            "# Additional instructions from " + owner_name + "\n\n"
            "These are extra, up-to-date instructions the human has set. Follow "
            "them carefully; if they conflict with anything above, these win.\n\n"
            + extra
        )

    return "\n\n".join(sections).strip()


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
    """Render the whole conversation as a single, size-bounded user task.

    ``messages`` is the stored conversation in chronological order. To keep
    per-turn cost bounded (and never overflow the model's context window on a
    very long thread), only the most recent messages that fit within
    ``settings.TRANSCRIPT_CHAR_BUDGET`` are included; older lines are dropped with
    a short note. The latest visitor line is always kept. The full history is
    still stored in the database — this only bounds what is sent to the model.
    """
    rendered: list[str] = []
    for row in messages:
        label = _role_label(row.get("role", ""), owner_name)
        content = (row.get("content") or "").strip()
        rendered.append(f"{label}: {content}")
    if pending_visitor is not None:
        rendered.append(f"Visitor: {pending_visitor.strip()}")

    kept, truncated = _bound_transcript(rendered, settings.TRANSCRIPT_CHAR_BUDGET)

    header = [
        "Here is the full conversation so far. Respond as the Avatar to the "
        "latest Visitor message.",
        "",
    ]
    if truncated:
        header.append(
            "[Earlier messages were omitted to keep this prompt concise; the "
            "most recent messages follow.]"
        )
        header.append("")

    return "\n".join(header + kept).strip()


def _bound_transcript(lines: list[str], budget: int) -> tuple[list[str], bool]:
    """Keep the most recent ``lines`` that fit in ``budget`` characters.

    Returns ``(kept_lines_in_order, truncated)``. Always keeps at least the last
    line so the latest visitor message is never dropped.
    """
    if budget <= 0:
        return lines, False
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        cost = len(line) + 1  # +1 for the newline join
        if kept and total + cost > budget:
            return list(reversed(kept)), True
        kept.append(line)
        total += cost
    return list(reversed(kept)), False


__all__ = [
    "KNOWLEDGE_MD",
    "STYLE_MD",
    "RULES_MD",
    "SEED_FAQS",
    "SEED_FAQ_BY_ID",
    "seed_faq",
    "format_faq_answer",
    "format_instant",
    "build_fetch_instructions",
    "build_system_prompt",
    "build_user_task",
]
