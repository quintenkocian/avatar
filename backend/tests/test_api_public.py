"""Tests for the public HTTP API: config, conversation, instant, chat.

The DB layer and the agent stream are mocked (see conftest.FakeDB and
make_fake_stream), so these tests are hermetic — no network, no LLM, no Supabase.
"""

from __future__ import annotations

from app import agent, knowledge, rate_limit
from app.config import settings
from conftest import make_fake_stream, parse_sse


def test_config_returns_owner_name(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == {"owner_name": settings.OWNER_NAME}


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_conversation_restore(client, fake_db):
    fake_db.conversation = [
        {"id": 1, "role": "visitor", "content": "hi", "conversation_name": "Ada"},
        {"id": 2, "role": "avatar", "content": "hello", "conversation_name": None},
    ]
    resp = client.get("/api/conversation", params={"conversation_id": "c1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "c1"
    assert body["conversation_name"] == "Ada"
    assert len(body["messages"]) == 2


def test_conversation_poll_passes_after_id(client, fake_db):
    fake_db.conversation = [
        {"id": 1, "role": "visitor", "content": "hi", "conversation_name": "Ada"},
        {"id": 2, "role": "human", "content": "owner here", "conversation_name": None},
    ]
    resp = client.get(
        "/api/conversation", params={"conversation_id": "c1", "after_id": 1}
    )
    assert resp.status_code == 200
    body = resp.json()
    # Only the row with id > 1 is returned.
    assert [m["id"] for m in body["messages"]] == [2]
    # The DB layer was called with after_id=1.
    assert ("get_conversation", ("c1", 1), {}) in fake_db.calls


def test_instant_known_qn_persists_two_rows(client, fake_db):
    n = knowledge.FAQS[0]["faq"]
    resp = client.post(
        "/api/instant",
        json={"conversation_id": "c1", "name": "Ada", "message": f"Q{n}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["question_number"] == n
    assert body["content"].startswith(f"**Q{n}:**")
    # A visitor row and an avatar row were inserted.
    inserts = [c for c in fake_db.calls if c[0] == "insert"]
    assert len(inserts) == 2
    roles = [c[1][1] for c in inserts]
    assert roles == ["visitor", "avatar"]


def test_instant_unknown_qn_persists_nothing(client, fake_db):
    resp = client.post(
        "/api/instant", json={"conversation_id": "c1", "message": "Q9999"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"found": False}
    assert not [c for c in fake_db.calls if c[0] == "insert"]


def test_instant_non_qn_returns_not_found(client, fake_db):
    resp = client.post(
        "/api/instant", json={"conversation_id": "c1", "message": "hello there"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"found": False}
    assert not [c for c in fake_db.calls if c[0] == "insert"]


def test_instant_rate_limited(client, fake_db, monkeypatch):
    monkeypatch.setattr(rate_limit, "check", lambda cid: False)
    n = knowledge.FAQS[0]["faq"]
    resp = client.post(
        "/api/instant", json={"conversation_id": "c1", "message": f"Q{n}"}
    )
    assert resp.status_code == 429
    assert resp.json() == {"error": "rate_limited"}
    assert not fake_db.calls


def test_chat_streams_start_tokens_done(client, fake_db, monkeypatch):
    fake_db.conversation = []
    monkeypatch.setattr(
        agent, "stream_reply", make_fake_stream(tokens=["Hello", " world"])
    )
    resp = client.post(
        "/api/chat",
        json={"conversation_id": "c1", "name": "Ada", "message": "hi"},
    )
    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    types = [f["type"] for f in frames]
    assert types[0] == "start"
    assert "token" in types
    assert types[-1] == "done"
    # The done frame references the persisted avatar row id.
    done = frames[-1]
    assert done["message_id"] is not None
    # The reassembled text matches the tokens.
    text = "".join(f["text"] for f in frames if f["type"] == "token")
    assert text == "Hello world"


def test_chat_persists_visitor_then_avatar(client, fake_db, monkeypatch):
    monkeypatch.setattr(agent, "stream_reply", make_fake_stream(tokens=["reply"]))
    client.post(
        "/api/chat", json={"conversation_id": "c1", "name": "Ada", "message": "hi"}
    )
    inserts = [c for c in fake_db.calls if c[0] == "insert"]
    roles = [c[1][1] for c in inserts]
    assert roles == ["visitor", "avatar"]
    # Avatar row text is the streamed reply and stored as read.
    avatar_insert = inserts[-1]
    assert avatar_insert[1][2] == "reply"
    assert avatar_insert[2]["read"] is True


def test_chat_stores_tool_calls(client, fake_db, monkeypatch):
    monkeypatch.setattr(
        agent,
        "stream_reply",
        make_fake_stream(
            tokens=["answer"], tools=[{"name": "faq_tool", "detail": "Q1"}]
        ),
    )
    resp = client.post(
        "/api/chat", json={"conversation_id": "c1", "message": "what degree?"}
    )
    frames = parse_sse(resp.text)
    tool_frames = [f for f in frames if f["type"] == "tool"]
    assert any(f.get("phase") == "calling" for f in tool_frames)
    # The avatar insert carries the tool_calls payload.
    avatar_insert = [c for c in fake_db.calls if c[0] == "insert"][-1]
    tool_calls = avatar_insert[2]["tool_calls"]
    assert tool_calls and tool_calls[0]["name"] == "faq_tool"
    # A non-push tool must NOT raise the needs-attention flag.
    assert avatar_insert[2]["needs_attention"] is False


def test_chat_push_tool_flags_needs_attention(client, fake_db, monkeypatch):
    monkeypatch.setattr(
        agent,
        "stream_reply",
        make_fake_stream(
            tokens=["I've let them know"],
            tools=[{"name": agent.push_tool.name, "detail": "wants to connect"}],
        ),
    )
    client.post(
        "/api/chat",
        json={"conversation_id": "c1", "message": "can I get in touch?"},
    )
    # The avatar row is flagged so the admin "Needs You" indicator appears.
    avatar_insert = [c for c in fake_db.calls if c[0] == "insert"][-1]
    assert avatar_insert[2]["needs_attention"] is True


def test_chat_rate_limited_before_any_model_call(client, fake_db, monkeypatch):
    called = {"stream": False}

    def _should_not_run(*a, **k):  # pragma: no cover - must never be called
        called["stream"] = True
        raise AssertionError("agent.stream_reply called despite rate limit")

    monkeypatch.setattr(rate_limit, "check", lambda cid: False)
    monkeypatch.setattr(agent, "stream_reply", _should_not_run)
    resp = client.post(
        "/api/chat", json={"conversation_id": "c1", "message": "hi"}
    )
    assert resp.status_code == 429
    assert called["stream"] is False
    assert not fake_db.calls


def test_chat_error_with_no_text_persists_nothing(client, fake_db, monkeypatch):
    """If the agent errors before any token, no avatar row is stored."""
    monkeypatch.setattr(
        agent, "stream_reply", make_fake_stream(tokens=[], error="boom")
    )
    resp = client.post(
        "/api/chat", json={"conversation_id": "c1", "message": "hi"}
    )
    frames = parse_sse(resp.text)
    types = [f["type"] for f in frames]
    assert "error" in types
    assert types[-1] == "done"
    assert frames[-1]["message_id"] is None
    # Only the visitor row was inserted; no avatar row.
    roles = [c[1][1] for c in fake_db.calls if c[0] == "insert"]
    assert roles == ["visitor"]


def test_chat_partial_text_then_error_persists_partial(client, fake_db, monkeypatch):
    """Partial text before an error is still persisted so the owner sees it."""
    monkeypatch.setattr(
        agent,
        "stream_reply",
        make_fake_stream(tokens=["half a "], error="boom"),
    )
    resp = client.post(
        "/api/chat", json={"conversation_id": "c1", "message": "hi"}
    )
    frames = parse_sse(resp.text)
    assert frames[-1]["type"] == "done"
    assert frames[-1]["message_id"] is not None
    avatar_insert = [c for c in fake_db.calls if c[0] == "insert"][-1]
    assert avatar_insert[1][1] == "avatar"
    assert avatar_insert[1][2] == "half a"  # stripped


def test_chat_existing_name_not_overwritten(client, fake_db, monkeypatch):
    """When the thread already has a name, a new provided name is not stored."""
    fake_db.conversation = [
        {"id": 1, "role": "visitor", "content": "earlier", "conversation_name": "Ada"}
    ]
    monkeypatch.setattr(agent, "stream_reply", make_fake_stream(tokens=["ok"]))
    client.post(
        "/api/chat",
        json={"conversation_id": "c1", "name": "Grace", "message": "hi again"},
    )
    visitor_insert = [c for c in fake_db.calls if c[0] == "insert"][0]
    # conversation_name kwarg is None because the thread already had a name.
    assert visitor_insert[2]["conversation_name"] is None


def test_chat_clamps_long_message(client, fake_db, monkeypatch):
    monkeypatch.setattr(agent, "stream_reply", make_fake_stream(tokens=["ok"]))
    long_message = "z" * (settings.MAX_MESSAGE_CHARS + 100)
    client.post(
        "/api/chat", json={"conversation_id": "c1", "message": long_message}
    )
    visitor_insert = [c for c in fake_db.calls if c[0] == "insert"][0]
    stored = visitor_insert[1][2]
    assert len(stored) == settings.MAX_MESSAGE_CHARS + len(settings.TRUNCATION_NOTE)
    assert stored.endswith(settings.TRUNCATION_NOTE)


def test_chat_clamped_text_is_sent_to_the_llm(client, fake_db, monkeypatch):
    """SPEC #12: the clamped text is what is BOTH stored AND sent to the model.

    Capture the task handed to agent.stream_reply and assert it carries the
    truncation note (i.e. the clamped body), not the full original message.
    """
    captured: dict[str, str] = {}

    async def capturing_stream(task: str, owner_name: str):
        captured["task"] = task
        yield {"type": "token", "text": "ok"}

    monkeypatch.setattr(agent, "stream_reply", capturing_stream)
    long_message = "z" * (settings.MAX_MESSAGE_CHARS + 100)
    client.post(
        "/api/chat", json={"conversation_id": "c1", "message": long_message}
    )
    task = captured["task"]
    assert settings.TRUNCATION_NOTE.strip() in task
    # The original (over-limit) message length never reaches the model verbatim.
    assert ("z" * (settings.MAX_MESSAGE_CHARS + 100)) not in task
