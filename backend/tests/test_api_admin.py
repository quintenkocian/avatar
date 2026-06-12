"""Tests for the admin HTTP API and its session-cookie auth gate.

SPEC requirement: every /admin/* data route must be unavailable without a valid
admin session. The DB layer is mocked (conftest.FakeDB).
"""

from __future__ import annotations

import pytest

from app.config import settings

# (method, path) for every guarded admin data route.
GUARDED_ROUTES = [
    ("get", "/admin/me"),
    ("get", "/admin/conversations"),
    ("get", "/admin/conversations/c1"),
    ("post", "/admin/conversations/c1/message"),
    ("post", "/admin/conversations/c1/resolve"),
]


@pytest.mark.parametrize("method,path", GUARDED_ROUTES)
def test_admin_routes_require_auth(client, fake_db, method, path):
    """Without a session cookie, every admin data route returns 401."""
    kwargs = {}
    if path.endswith("/message"):
        kwargs["json"] = {"content": "hi"}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401, f"{method.upper()} {path} should be 401"


def test_login_wrong_password(client):
    resp = client.post("/admin/login", json={"password": "definitely-wrong"})
    assert resp.status_code == 401
    assert resp.json() == {"ok": False}
    assert settings.ADMIN_COOKIE_NAME not in resp.cookies


def test_login_correct_password_sets_cookie(client):
    resp = client.post(
        "/admin/login", json={"password": settings.ADMIN_PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert settings.ADMIN_COOKIE_NAME in resp.cookies


def test_login_then_access_me(client):
    """A real login flow yields access to a guarded route."""
    client.post("/admin/login", json={"password": settings.ADMIN_PASSWORD})
    resp = client.get("/admin/me")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_admin_me_with_fixture_cookie(admin_client):
    resp = admin_client.get("/admin/me")
    assert resp.status_code == 200


def test_admin_list_conversations(admin_client, fake_db):
    fake_db.inbox = [
        {
            "conversation_id": "c1",
            "conversation_name": "Ada",
            "last_role": "visitor",
            "last_content": "hi",
            "last_at": "2026-01-01T00:00:01Z",
            "message_count": 1,
            "unread_count": 1,
            "needs_attention": False,
            "initials": "AD",
        }
    ]
    resp = admin_client.get("/admin/conversations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversations"][0]["conversation_id"] == "c1"
    assert "list_conversations" in fake_db.call_names()


def test_admin_open_conversation_marks_read(admin_client, fake_db):
    fake_db.conversation = [
        {"id": 1, "role": "visitor", "content": "hi", "conversation_name": "Ada"},
        {
            "id": 2,
            "role": "avatar",
            "content": "hello",
            "conversation_name": None,
            "needs_attention": True,
        },
    ]
    resp = admin_client.get("/admin/conversations/c1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "c1"
    assert body["conversation_name"] == "Ada"
    assert len(body["messages"]) == 2
    # Opening marks read via open_conversation but does NOT clear attention:
    # the flag persists in the returned rows until "Mark resolved".
    assert "c1" in fake_db.opened
    assert body["messages"][1]["needs_attention"] is True


def test_admin_post_message_inserts_human_row(admin_client, fake_db):
    resp = admin_client.post(
        "/admin/conversations/c1/message", json={"content": "Owner here"}
    )
    assert resp.status_code == 200
    row = resp.json()["message"]
    assert row["role"] == "human"
    assert row["content"] == "Owner here"
    insert = [c for c in fake_db.calls if c[0] == "insert"][0]
    # Human messages are stored read and not needing attention.
    assert insert[1][1] == "human"
    assert insert[2]["read"] is True
    assert insert[2]["needs_attention"] is False


def test_admin_resolve(admin_client, fake_db):
    resp = admin_client.post("/admin/conversations/c1/resolve")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "c1" in fake_db.resolved


def test_admin_logout_clears_cookie(admin_client):
    resp = admin_client.post("/admin/logout")
    assert resp.status_code == 200
    # A delete-cookie header is emitted for the admin cookie.
    assert settings.ADMIN_COOKIE_NAME in resp.headers.get("set-cookie", "")


def test_admin_logout_is_ungated(client):
    """Logout is intentionally NOT gated: a caller can always clear their cookie."""
    resp = client.post("/admin/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert settings.ADMIN_COOKIE_NAME in resp.headers.get("set-cookie", "")
