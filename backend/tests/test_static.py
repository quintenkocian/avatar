"""Tests for static frontend serving and asset routes."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app import main
from app.config import settings

_DIST_BUILT = (settings.STATIC_DIR / "index.html").is_file()


def test_serve_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    if _DIST_BUILT:
        # Real build: the visitor document.
        assert "<html" in resp.text.lower()
    else:
        # Placeholder when the frontend has not been built.
        assert "backend is running" in resp.text.lower()


def test_serve_admin(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_png_missing_returns_404(client):
    resp = client.get("/definitely-not-a-real-asset.png")
    assert resp.status_code == 404


def test_png_traversal_rejected():
    """The /{name}.png handler rejects path-traversal filenames."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.serve_png("../../etc/passwd"))
    assert exc.value.status_code == 404


@pytest.mark.skipif(not _DIST_BUILT, reason="frontend not built")
def test_avatar_png_served(client):
    resp = client.get("/avatar-human.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_favicon(client):
    resp = client.get("/favicon.ico")
    # Either a real favicon file (200) or a friendly 204 no-content.
    assert resp.status_code in (200, 204)


# --- Open Graph card -----------------------------------------------------------

_RELATIVE_OG_INDEX = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:url" content="/" />'
    '<meta property="og:image" content="/og-avatar.png" />'
    '<meta name="twitter:image" content="/og-avatar.png" />'
    "</head><body>hi</body></html>"
)


def test_public_base_url_prefers_setting(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://avatar.example.com/")

    class _Req:
        headers: dict[str, str] = {}

        class url:
            scheme = "http"
            netloc = "ignored"

    # The explicit setting wins and the trailing slash is trimmed.
    assert main._public_base_url(_Req()) == "https://avatar.example.com"


def test_public_base_url_honours_forwarded_headers(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")

    class _Req:
        headers = {
            "x-forwarded-proto": "https",
            "x-forwarded-host": "avatar.example.com",
        }

        class url:
            scheme = "http"
            netloc = "internal:8080"

    assert main._public_base_url(_Req()) == "https://avatar.example.com"


def test_serve_index_rewrites_og_to_absolute(client, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text(_RELATIVE_OG_INDEX, encoding="utf-8")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")

    resp = client.get(
        "/",
        headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "avatar.example.com",
        },
    )
    assert resp.status_code == 200
    assert (
        '<meta property="og:image" '
        'content="https://avatar.example.com/og-avatar.png" />' in resp.text
    )
    assert (
        '<meta name="twitter:image" '
        'content="https://avatar.example.com/og-avatar.png" />' in resp.text
    )
    assert (
        '<meta property="og:url" content="https://avatar.example.com/" />'
        in resp.text
    )
    # No root-relative remnants once rewritten.
    assert 'content="/og-avatar.png"' not in resp.text
