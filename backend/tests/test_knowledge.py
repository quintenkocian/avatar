"""Tests for app.knowledge — FAQ formatting and prompt composition."""

from __future__ import annotations

from app import knowledge


def test_seed_faqs_loaded():
    """Seed FAQs load from faq.jsonl and are keyed by their integer id."""
    assert knowledge.SEED_FAQS, "expected seed FAQs to load from faq.jsonl"
    assert all(isinstance(row["id"], int) for row in knowledge.SEED_FAQS)
    first = knowledge.SEED_FAQS[0]["id"]
    assert knowledge.SEED_FAQ_BY_ID[first]["id"] == first
    # The on-disk routing phrase maps to the canonical `concise` key.
    assert "concise" in knowledge.SEED_FAQS[0]


def test_format_faq_answer():
    """format_faq_answer returns a Q+A block for a row."""
    row = knowledge.SEED_FAQS[0]
    block = knowledge.format_faq_answer(row)
    assert f"Question {row['id']}" in block
    assert "Answer" in block
    assert row["answer"][:20] in block


def test_seed_faq_lookup():
    n = knowledge.SEED_FAQS[0]["id"]
    assert knowledge.seed_faq(n)["id"] == n
    assert knowledge.seed_faq(9999) is None


def test_format_instant_restates_question():
    """The Qn instant reply restates the question, then gives the answer."""
    row = knowledge.SEED_FAQS[0]
    md = knowledge.format_instant(row)
    assert md.startswith(f"**Q{row['id']}:** {row['question']}")
    assert row["answer"] in md


def test_build_system_prompt_uses_owner_name():
    """The owner name is interpolated everywhere, never hardcoded."""
    prompt = knowledge.build_system_prompt("Ada Lovelace")
    assert "Ada Lovelace" in prompt
    # The three-way setup must be explained.
    assert "Visitor" in prompt
    assert "Avatar" in prompt
    assert "human" in prompt.lower()
    # Tools are documented.
    assert "faq_tool" in prompt
    assert "push_tool" in prompt
    assert "fetch" in prompt
    # FAQ routing numbers are listed, and the operating rules + job section.
    assert "FAQ routing" in prompt
    assert "Operating rules" in prompt
    assert "job" in prompt.lower()


def test_build_system_prompt_uses_provided_faqs():
    """A supplied FAQ list drives the routing block (DB source of truth)."""
    faqs = [{"id": 7, "concise": "routing phrase seven", "question": "Q", "answer": "A"}]
    prompt = knowledge.build_system_prompt("Owner", faqs)
    assert "7. routing phrase seven" in prompt


def test_build_system_prompt_additional_instructions_last():
    """Additional instructions are appended LAST (cache-friendly, recency)."""
    prompt = knowledge.build_system_prompt(
        "Owner", additional_instructions="ALWAYS mention the newsletter."
    )
    assert "Additional instructions" in prompt
    assert prompt.rstrip().endswith("ALWAYS mention the newsletter.")
    # Empty instructions add no trailing section.
    plain = knowledge.build_system_prompt("Owner", additional_instructions="  ")
    assert "Additional instructions" not in plain


def test_build_system_prompt_distinct_owner_names():
    """A different owner name yields a different prompt (nothing hardcoded)."""
    a = knowledge.build_system_prompt("Owner A")
    b = knowledge.build_system_prompt("Owner B")
    assert "Owner A" in a and "Owner A" not in b
    assert "Owner B" in b and "Owner B" not in a


def test_build_user_task_labels_roles():
    """Each stored role is rendered with its transcript label."""
    messages = [
        {"role": "visitor", "content": "Hello there"},
        {"role": "avatar", "content": "Hi, I am the twin"},
        {"role": "human", "content": "Owner jumping in"},
    ]
    task = knowledge.build_user_task(messages, "Grace Hopper")
    assert "Visitor: Hello there" in task
    assert "Avatar (you): Hi, I am the twin" in task
    assert "Grace Hopper (the human): Owner jumping in" in task


def test_build_user_task_appends_pending_visitor():
    task = knowledge.build_user_task(
        [{"role": "avatar", "content": "previous"}],
        "Owner",
        pending_visitor="a new question",
    )
    assert task.rstrip().endswith("Visitor: a new question")


def test_build_user_task_bounds_long_transcript():
    """A very long transcript is trimmed to the most recent within budget."""
    # Many large early messages, then a small final visitor line.
    messages = [
        {"role": "visitor", "content": "X" * 5000} for _ in range(20)
    ]
    messages.append({"role": "visitor", "content": "FINAL question"})
    task = knowledge.build_user_task(messages, "Owner")
    assert "FINAL question" in task  # latest is always kept
    assert "omitted" in task  # truncation note present
    assert len(task) < 20 * 5000  # genuinely trimmed


def test_role_label_unknown_role():
    """An unexpected stored role falls back to a capitalized label."""
    assert knowledge._role_label("unknown_role", "Owner") == "Unknown_role"


def test_build_user_task_handles_missing_keys():
    """Rows missing role/content keys degrade gracefully, never raising."""
    task_no_role = knowledge.build_user_task([{"content": "hello"}], "Owner")
    assert "hello" in task_no_role
    task_no_content = knowledge.build_user_task([{"role": "visitor"}], "Owner")
    assert "Visitor:" in task_no_content


def test_load_seed_faqs_skips_malformed(tmp_path):
    """A malformed JSONL line is skipped, not fatal."""
    p = tmp_path / "faq.jsonl"
    p.write_text(
        '{"faq": 1, "question": "Q?", "answer": "A.", "query": "q"}\n'
        "this is not json\n"
        '{"faq": 2, "question": "Q2?", "answer": "A2.", "query": "q2"}\n',
        encoding="utf-8",
    )
    rows = knowledge._load_seed_faqs(p)
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["concise"] == "q"
