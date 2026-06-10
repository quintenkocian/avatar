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
