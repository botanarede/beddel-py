"""Integration tests for the standalone A2UI static renderer routes.

Verifies ``register_static_routes`` wires ``GET /`` (the zero-dependency
A2UI HTML renderer) and ``GET /favicon.ico`` (204) onto a FastAPI app.
"""

from __future__ import annotations

from beddel_serve_fastapi.static_routes import register_static_routes
from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_client() -> TestClient:
    """Create a test client with the static routes registered."""
    app = FastAPI()
    register_static_routes(app)
    return TestClient(app)


def test_index_returns_html() -> None:
    """GET / returns 200 with an HTML content type."""
    response = _make_client().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_index_contains_renderer_markers() -> None:
    """The served page is the A2UI renderer (key markers present)."""
    response = _make_client().get("/")
    assert "Beddel" in response.text
    assert "a2ui_surface" in response.text
    assert "/workflows/" in response.text


def test_favicon_returns_204() -> None:
    """GET /favicon.ico returns 204 No Content."""
    response = _make_client().get("/favicon.ico")
    assert response.status_code == 204
