"""Tests for dashboard auth middleware (token validation + caching)."""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from beddel.integrations.dashboard.auth_middleware import (
    TokenCache,
    create_auth_middleware,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RealAsyncClient = httpx.AsyncClient


def _github_ok_handler(request: httpx.Request) -> httpx.Response:
    """Mock GitHub /user returning 200 with login=testuser."""
    return httpx.Response(200, json={"login": "testuser", "id": 1})


def _github_401_handler(request: httpx.Request) -> httpx.Response:
    """Mock GitHub /user returning 401."""
    return httpx.Response(401, json={"message": "Bad credentials"})


def _make_mock_client(handler: Any) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient with a MockTransport."""
    return _RealAsyncClient(transport=httpx.MockTransport(handler))


def _make_app(
    allowed_users: list[str] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with auth middleware applied."""
    app = FastAPI()
    middleware_cls = create_auth_middleware(
        allowed_users, client=client, github_url="https://api.github.com/user"
    )
    app.add_middleware(middleware_cls)

    @app.get("/api/test")
    async def api_test() -> JSONResponse:
        return JSONResponse(content={"ok": True})

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(content={"status": "healthy"})

    return app


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


class TestMiddlewarePassesValidToken:
    """Valid token → request proceeds to the endpoint."""

    def test_middleware_passes_valid_token(self) -> None:
        mock_client = _make_mock_client(_github_ok_handler)
        app = _make_app(client=mock_client)
        tc = TestClient(app)

        resp = tc.get("/api/test", headers={"Authorization": "Bearer gho_valid"})

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestMiddlewareRejectsMissingHeader:
    """No Authorization header → 401 with BEDDEL-AUTH-905."""

    def test_middleware_rejects_missing_header(self) -> None:
        mock_client = _make_mock_client(_github_ok_handler)
        app = _make_app(client=mock_client)
        tc = TestClient(app)

        resp = tc.get("/api/test")

        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == "BEDDEL-AUTH-905"
        assert "Missing authorization header" in body["error"]


class TestMiddlewareRejectsInvalidToken:
    """GitHub returns 401 → middleware returns 401 with BEDDEL-AUTH-906."""

    def test_middleware_rejects_invalid_token(self) -> None:
        mock_client = _make_mock_client(_github_401_handler)
        app = _make_app(client=mock_client)
        tc = TestClient(app)

        resp = tc.get("/api/test", headers={"Authorization": "Bearer bad_token"})

        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == "BEDDEL-AUTH-906"
        assert "Invalid token" in body["error"]


class TestMiddlewareRejectsDisallowedUser:
    """Valid token but user not in allowed_users → 403 with BEDDEL-AUTH-907."""

    def test_middleware_rejects_disallowed_user(self) -> None:
        mock_client = _make_mock_client(_github_ok_handler)
        app = _make_app(allowed_users=["admin_only"], client=mock_client)
        tc = TestClient(app)

        resp = tc.get("/api/test", headers={"Authorization": "Bearer gho_valid"})

        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == "BEDDEL-AUTH-907"
        assert "User not allowed" in body["error"]


class TestMiddlewareAllowsAnyUserWhenNoAllowlist:
    """No allowed_users → any valid GitHub token is accepted."""

    def test_middleware_allows_any_user_when_no_allowlist(self) -> None:
        mock_client = _make_mock_client(_github_ok_handler)
        app = _make_app(allowed_users=None, client=mock_client)
        tc = TestClient(app)

        resp = tc.get("/api/test", headers={"Authorization": "Bearer gho_any"})

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestTokenCacheHit:
    """Second request with same token should NOT call GitHub API again."""

    def test_token_cache_hit(self) -> None:
        call_count = 0

        def counting_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"login": "testuser", "id": 1})

        mock_client = _make_mock_client(counting_handler)
        cache = TokenCache()
        app = FastAPI()
        middleware_cls = create_auth_middleware(
            None,
            cache=cache,
            client=mock_client,
            github_url="https://api.github.com/user",
        )
        app.add_middleware(middleware_cls)

        @app.get("/api/test")
        async def api_test() -> JSONResponse:
            return JSONResponse(content={"ok": True})

        tc = TestClient(app)
        headers = {"Authorization": "Bearer gho_cached"}

        # First request — hits GitHub API
        resp1 = tc.get("/api/test", headers=headers)
        assert resp1.status_code == 200
        assert call_count == 1

        # Second request — served from cache
        resp2 = tc.get("/api/test", headers=headers)
        assert resp2.status_code == 200
        assert call_count == 1  # no additional API call


class TestTokenCacheExpiry:
    """Expired cache entry triggers a fresh GitHub API call."""

    def test_token_cache_expiry(self) -> None:
        call_count = 0

        def counting_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"login": "testuser", "id": 1})

        mock_client = _make_mock_client(counting_handler)
        cache = TokenCache(ttl=1)  # 1-second TTL
        app = FastAPI()
        middleware_cls = create_auth_middleware(
            None,
            cache=cache,
            client=mock_client,
            github_url="https://api.github.com/user",
        )
        app.add_middleware(middleware_cls)

        @app.get("/api/test")
        async def api_test() -> JSONResponse:
            return JSONResponse(content={"ok": True})

        tc = TestClient(app)
        headers = {"Authorization": "Bearer gho_expiry"}

        # First request — hits GitHub API
        resp1 = tc.get("/api/test", headers=headers)
        assert resp1.status_code == 200
        assert call_count == 1

        # Simulate expiry by manipulating the cache entry directly
        token_entry = cache._cache.get("gho_expiry")
        assert token_entry is not None
        # Set expiry to the past
        cache._cache["gho_expiry"] = (token_entry[0], time.monotonic() - 10)

        # Third request — cache expired, hits GitHub API again
        resp2 = tc.get("/api/test", headers=headers)
        assert resp2.status_code == 200
        assert call_count == 2  # fresh API call


class TestMiddlewareSkipsNonApiPaths:
    """Request to /health passes without auth."""

    def test_middleware_skips_non_api_paths(self) -> None:
        mock_client = _make_mock_client(_github_401_handler)
        app = _make_app(client=mock_client)
        tc = TestClient(app)

        # /health should pass even without auth header
        resp = tc.get("/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}
