"""Unit tests for /api/kits and /api/flows FastAPI endpoints.

Tests the index API endpoints added to _build_runtime_app().
Uses httpx.AsyncClient with ASGITransport to test the FastAPI app
directly (no server needed).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from beddel.adapters.index_store import IndexStore


def _create_test_app(index_store: IndexStore | None) -> FastAPI:
    """Build a minimal FastAPI app with the /api/kits and /api/flows endpoints."""
    app = FastAPI()
    _index_store = index_store

    @app.get("/api/kits")
    async def api_kits(enabled: str | None = Query(None)) -> JSONResponse:
        if _index_store is None:
            return JSONResponse(
                status_code=503,
                content={"error": "Index unavailable. Run beddel connect to build the index."},
            )
        if enabled == "true":
            kits = await _index_store.list_kits(enabled_only=True)
        else:
            kits = await _index_store.list_kits()
        for kit_row in kits:
            kit_row["enabled"] = bool(kit_row["enabled"])
        return JSONResponse(content=kits)

    @app.get("/api/flows")
    async def api_flows(enabled: str | None = Query(None)) -> JSONResponse:
        if _index_store is None:
            return JSONResponse(
                status_code=503,
                content={"error": "Index unavailable. Run beddel connect to build the index."},
            )
        if enabled == "true":
            flows = await _index_store.list_flows(enabled_only=True)
        else:
            flows = await _index_store.list_flows()
        for flow_row in flows:
            flow_row["enabled"] = bool(flow_row["enabled"])
        return JSONResponse(content=flows)

    return app


def _populate_kits(db_path: Path, kits: list[dict[str, Any]]) -> None:
    """Insert kit rows into a temporary index.db."""
    conn = sqlite3.connect(str(db_path))
    now = "2026-01-01T00:00:00+00:00"
    with conn:
        for k in kits:
            conn.execute(
                "INSERT INTO kit_index "
                "(name, version, description, category, path, enabled, port, "
                "discovered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    k.get("name", "test-kit"),
                    k.get("version", "0.1.0"),
                    k.get("description", "A test kit"),
                    k.get("category", "general"),
                    k.get("path", "/tmp/kits/test"),
                    k.get("enabled", 1),
                    k.get("port", ""),
                    now,
                    now,
                ),
            )
    conn.close()


def _populate_flows(db_path: Path, flows: list[dict[str, Any]]) -> None:
    """Insert flow rows into a temporary index.db."""
    conn = sqlite3.connect(str(db_path))
    now = "2026-01-01T00:00:00+00:00"
    with conn:
        for f in flows:
            conn.execute(
                "INSERT INTO flow_index "
                "(id, name, description, category, path, enabled, step_count, "
                "discovered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f.get("id", "test-flow"),
                    f.get("name", "Test Flow"),
                    f.get("description", "A test flow"),
                    f.get("category", "general"),
                    f.get("path", "/tmp/flows/test.yaml"),
                    f.get("enabled", 1),
                    f.get("step_count", 3),
                    now,
                    now,
                ),
            )
    conn.close()


@pytest.fixture()
def index_store(tmp_path: Path) -> IndexStore:
    """Create an IndexStore with initialized schema."""
    import asyncio

    db_path = tmp_path / "index.db"
    store = IndexStore(db_path)
    asyncio.run(store._ensure_initialized())
    return store


@pytest.fixture()
def populated_store(tmp_path: Path) -> IndexStore:
    """Create an IndexStore with test kit and flow data."""
    import asyncio

    db_path = tmp_path / "index.db"
    store = IndexStore(db_path)
    asyncio.run(store._ensure_initialized())

    _populate_kits(
        db_path,
        [
            {"name": "kit-alpha", "version": "1.0.0", "enabled": 1, "category": "tools"},
            {"name": "kit-beta", "version": "2.0.0", "enabled": 0, "category": "agents"},
            {"name": "kit-gamma", "version": "0.5.0", "enabled": 1, "category": "general"},
        ],
    )
    _populate_flows(
        db_path,
        [
            {"id": "flow-one", "name": "Flow One", "enabled": 1, "step_count": 5},
            {"id": "flow-two", "name": "Flow Two", "enabled": 0, "step_count": 2},
            {"id": "flow-three", "name": "Flow Three", "enabled": 1, "step_count": 8},
        ],
    )
    return store


@pytest.mark.asyncio()
async def test_get_kits_returns_all(populated_store: IndexStore) -> None:
    """GET /api/kits returns all kits as JSON array."""
    app = _create_test_app(populated_store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/kits")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    names = {k["name"] for k in data}
    assert names == {"kit-alpha", "kit-beta", "kit-gamma"}
    # Verify enabled is bool, not int
    for kit in data:
        assert isinstance(kit["enabled"], bool)


@pytest.mark.asyncio()
async def test_get_kits_enabled_filter(populated_store: IndexStore) -> None:
    """GET /api/kits?enabled=true returns only enabled kits."""
    app = _create_test_app(populated_store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/kits", params={"enabled": "true"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {k["name"] for k in data}
    assert names == {"kit-alpha", "kit-gamma"}
    for kit in data:
        assert kit["enabled"] is True


@pytest.mark.asyncio()
async def test_get_flows_returns_all(populated_store: IndexStore) -> None:
    """GET /api/flows returns all flows as JSON array."""
    app = _create_test_app(populated_store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/flows")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    ids = {f["id"] for f in data}
    assert ids == {"flow-one", "flow-two", "flow-three"}
    # Verify enabled is bool, not int
    for flow in data:
        assert isinstance(flow["enabled"], bool)


@pytest.mark.asyncio()
async def test_get_flows_enabled_filter(populated_store: IndexStore) -> None:
    """GET /api/flows?enabled=true returns only enabled flows."""
    app = _create_test_app(populated_store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/flows", params={"enabled": "true"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ids = {f["id"] for f in data}
    assert ids == {"flow-one", "flow-three"}
    for flow in data:
        assert flow["enabled"] is True


@pytest.mark.asyncio()
async def test_kits_503_when_index_unavailable() -> None:
    """GET /api/kits returns 503 when index store is None."""
    app = _create_test_app(None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/kits")

    assert resp.status_code == 503
    data = resp.json()
    assert "error" in data
    assert "Index unavailable" in data["error"]


@pytest.mark.asyncio()
async def test_flows_503_when_index_unavailable() -> None:
    """GET /api/flows returns 503 when index store is None."""
    app = _create_test_app(None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/flows")

    assert resp.status_code == 503
    data = resp.json()
    assert "error" in data
    assert "Index unavailable" in data["error"]
