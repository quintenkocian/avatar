"""Tests for app.knowledge — FAQ lookups and prompt composition."""

from __future__ import annotations

from app import knowledge


def test_faqs_loaded():
    """FAQs load from faq.jsonl and are keyed by their integer number."""
    assert knowledge.FAQS, "expected FAQs to load from faq.jsonl"
    assert all(isinstance(row["faq"], int) for row in knowledge.FAQS)
    first = knowledge.FAQS[0]["faq"]
    assert knowledge.FAQ_BY_NUMBER[first]["faq"] == first


def test_find_faq_known():
    """find_faq returns a formatted Q+A block for a known number."""
    n = knowledge.FAQS[0]["faq"]
    block = knowledge.find_faq(n)
    assert block is not None
    assert f"Question {n}" in block
    assert "Answer" in block
    assert knowledge.FAQ_BY_NUMBER[n]["answer"][:20] in block


def test_find_faq_unknown():
    assert knowledge.find_faq(9999) is None


def test_instant_answer_restates_question():
    """The Qn instant reply restates the question, then gives the answer."""
    n = knowledge.FAQS[0]["faq"]
    row = knowledge.FAQ_BY_NUMBER[n]
    md = knowledge.instant_answer_markdown(n)
    assert md is not None
    assert md.startswith(f"**Q{n}:** {row['question']}")
    assert row["answer"] in md


def test_instant_answer_unknown():
    assert knowledge.instant_answer_markdown(9999) is None


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
    # FAQ routing numbers are listed.
    assert "FAQ routing" in prompt


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


def test_role_label_unknown_role():
    """An unexpected stored role falls back to a capitalized label."""
    assert knowledge._role_label("unknown_role", "Owner") == "Unknown_role"


def test_build_user_task_handles_missing_keys():
    """Rows missing role/content keys degrade gracefully, never raising."""
    task_no_role = knowledge.build_user_task([{"content": "hello"}], "Owner")
    assert "hello" in task_no_role
    task_no_content = knowledge.build_user_task([{"role": "visitor"}], "Owner")
    assert "Visitor:" in task_no_content


def test_load_faqs_skips_malformed(tmp_path):
    """A malformed JSONL line is skipped, not fatal."""
    p = tmp_path / "faq.jsonl"
    p.write_text(
        '{"faq": 1, "question": "Q?", "answer": "A.", "query": "q"}\n'
        "this is not json\n"
        '{"faq": 2, "question": "Q2?", "answer": "A2.", "query": "q2"}\n',
        encoding="utf-8",
    )
    rows = knowledge._load_faqs(p)
    assert [r["faq"] for r in rows] == [1, 2]
