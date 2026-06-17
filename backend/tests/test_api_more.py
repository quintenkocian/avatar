"""Tests for the MORE admin endpoints: archive, instructions, FAQ, export, throttle.

The DB layer is mocked (conftest.FakeDB); these tests are hermetic.
"""

from __future__ import annotations

from app import notifications, rate_limit
from app.config import settings


# --- Archive -----------------------------------------------------------------


def test_archive_conversation(admin_client, fake_db):
    resp = admin_client.post("/admin/conversations/c1/archive")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "c1" in fake_db.archived


def test_list_archive_with_total(admin_client, fake_db):
    fake_db.archived_inbox = [
        {"conversation_id": "a1", "conversation_name": "Ada", "last_role": "visitor",
         "last_content": "hi", "last_at": "2026-01-01T00:00:01Z", "message_count": 1,
         "unread_count": 0, "needs_attention": False, "initials": "AD"},
    ]
    resp = admin_client.get("/admin/archive")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["conversations"][0]["conversation_id"] == "a1"


def test_open_archived_thread(admin_client, fake_db):
    fake_db.archived_conversation = [
        {"id": 1, "role": "visitor", "content": "old", "conversation_name": "Ada"},
    ]
    resp = admin_client.get("/admin/archive/a1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "a1"
    assert body["conversation_name"] == "Ada"
    assert len(body["messages"]) == 1
    # Opening an archived thread must NOT mark read or touch attention.
    assert "get_archived_conversation" in fake_db.call_names()
    assert "open_conversation" not in fake_db.call_names()


def test_restore_conversation(admin_client, fake_db):
    resp = admin_client.post("/admin/archive/a1/restore")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "a1" in fake_db.restored


def test_archive_inactive(admin_client, fake_db):
    fake_db.archive_inactive_result = ["c1", "c2"]
    resp = admin_client.post("/admin/archive-inactive")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert set(body["archived"]) == {"c1", "c2"}
    assert ("archive_inactive", (72,), {}) in fake_db.calls


# --- Export ------------------------------------------------------------------


def test_export_conversations_jsonl(admin_client, fake_db):
    fake_db.rows = [
        {"id": 1, "role": "visitor", "content": "hi"},
        {"id": 2, "role": "avatar", "content": "hello"},
    ]
    resp = admin_client.get("/admin/export/conversations")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "conversations.jsonl" in resp.headers["content-disposition"]
    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    assert len(lines) == 2  # one JSON object per row


def test_export_archive_jsonl(admin_client, fake_db):
    fake_db.archived_conversation = [{"id": 9, "role": "human", "content": "x"}]
    resp = admin_client.get("/admin/export/archive")
    assert resp.status_code == 200
    assert "archive.jsonl" in resp.headers["content-disposition"]
    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    assert len(lines) == 1


# --- Instructions ------------------------------------------------------------


def test_get_instructions_empty_default(admin_client, fake_db):
    resp = admin_client.get("/admin/instructions")
    assert resp.status_code == 200
    assert resp.json() == {"additional_instructions": ""}


def test_put_then_get_instructions(admin_client, fake_db):
    put = admin_client.put(
        "/admin/instructions",
        json={"additional_instructions": "Mention the newsletter."},
    )
    assert put.status_code == 200
    assert put.json()["additional_instructions"] == "Mention the newsletter."
    get = admin_client.get("/admin/instructions")
    assert get.json()["additional_instructions"] == "Mention the newsletter."


# --- FAQ ---------------------------------------------------------------------


def test_faq_crud_flow(admin_client, fake_db):
    # Start empty.
    assert admin_client.get("/admin/faq").json() == {"faqs": [], "total": 0}

    # Create -> id assigned.
    created = admin_client.post(
        "/admin/faq",
        json={"concise": "pricing", "question": "How much?", "answer": "Free."},
    )
    assert created.status_code == 200
    row = created.json()["faq"]
    assert row["id"] == 1
    assert row["question"] == "How much?"

    # List shows it.
    listed = admin_client.get("/admin/faq").json()
    assert listed["total"] == 1

    # Update.
    updated = admin_client.put(
        "/admin/faq/1",
        json={"concise": "pricing cost", "question": "How much?", "answer": "It's free."},
    )
    assert updated.status_code == 200
    assert updated.json()["faq"]["answer"] == "It's free."

    # Delete.
    deleted = admin_client.delete("/admin/faq/1")
    assert deleted.status_code == 200
    assert admin_client.get("/admin/faq").json()["total"] == 0


def test_faq_update_missing_returns_404(admin_client, fake_db):
    resp = admin_client.put(
        "/admin/faq/999", json={"question": "q", "answer": "a"}
    )
    assert resp.status_code == 404


# --- Login throttle + failed-login alert -------------------------------------


def test_login_throttle_after_repeated_failures(client, monkeypatch):
    """After the per-IP failure limit, further attempts return 429 (not 401)."""
    pushes = []
    monkeypatch.setattr(notifications, "push_login_failure", lambda ip: pushes.append(ip))
    rate_limit.reset()

    # The limit is 5/minute; the 6th attempt should be throttled.
    statuses = []
    for _ in range(7):
        r = client.post("/admin/login", json={"password": "wrong"})
        statuses.append(r.status_code)
    assert statuses[:5] == [401, 401, 401, 401, 401]
    assert 429 in statuses[5:]
    # A failed-login alert fired for each genuine 401 (not for throttled ones).
    assert len(pushes) == 5


def test_successful_login_not_throttled(client, monkeypatch):
    """A correct password is never throttled, even after failures."""
    monkeypatch.setattr(notifications, "push_login_failure", lambda ip: None)
    rate_limit.reset()
    for _ in range(4):
        client.post("/admin/login", json={"password": "wrong"})
    resp = client.post("/admin/login", json={"password": settings.ADMIN_PASSWORD})
    assert resp.status_code == 200
    assert settings.ADMIN_COOKIE_NAME in resp.cookies
