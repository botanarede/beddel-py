"""Token validation middleware for remote dashboard access.

Provides :class:`TokenCache` for in-memory LRU caching of validated
GitHub tokens, :func:`validate_github_token` for async token validation,
and :func:`create_auth_middleware` which returns a Starlette
``BaseHTTPMiddleware`` subclass that protects ``/api/`` routes.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from beddel.error_codes import (
    AUTH_INVALID_TOKEN,
    AUTH_MISSING_HEADER,
    AUTH_USER_NOT_ALLOWED,
)

__all__ = ["TokenCache", "create_auth_middleware", "validate_github_token"]

logger = logging.getLogger(__name__)

GITHUB_USER_URL: str = "https://api.github.com/user"


class TokenCache:
    """In-memory LRU cache for validated GitHub tokens.

    Keys are token strings; values are ``(username, expiry)`` tuples.
    Uses :func:`time.monotonic` for TTL to avoid wall-clock drift.
    """

    def __init__(self, max_size: int = 100, ttl: int = 300) -> None:
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, token: str) -> str | None:
        """Return cached username for *token*, or ``None`` if expired/missing."""
        entry = self._cache.get(token)
        if entry is None:
            return None
        username, expiry = entry
        if time.monotonic() >= expiry:
            del self._cache[token]
            return None
        self._cache.move_to_end(token)
        return username

    def set(self, token: str, username: str) -> None:
        """Store *username* for *token* with TTL-based expiry.

        Evicts the oldest entry when the cache exceeds ``max_size``.
        """
        self._cache[token] = (username, time.monotonic() + self._ttl)
        self._cache.move_to_end(token)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


async def validate_github_token(
    token: str,
    cache: TokenCache,
    *,
    client: httpx.AsyncClient | None = None,
    github_url: str = GITHUB_USER_URL,
) -> str | None:
    """Validate a GitHub token and return the username, or ``None``.

    Checks the *cache* first.  On a miss, calls the GitHub ``/user``
    endpoint.  A 200 response caches and returns the ``login`` field;
    any other status returns ``None``.

    Args:
        token: GitHub access token.
        cache: Token cache instance.
        client: Optional pre-built httpx client (for testability).
        github_url: GitHub API URL (overridable for tests).

    Returns:
        GitHub username on success, ``None`` on auth failure.
    """
    cached = cache.get(token)
    if cached is not None:
        return cached

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    if client is not None:
        resp = await client.get(github_url, headers=headers)
    else:
        async with httpx.AsyncClient() as _client:
            resp = await _client.get(github_url, headers=headers)

    if resp.status_code == 200:
        body: dict[str, Any] = resp.json()
        username: str = body["login"]
        cache.set(token, username)
        return username

    return None


def create_auth_middleware(
    allowed_users: list[str] | None = None,
    *,
    cache: TokenCache | None = None,
    client: httpx.AsyncClient | None = None,
    github_url: str = GITHUB_USER_URL,
) -> type[BaseHTTPMiddleware]:
    """Return a Starlette middleware class that validates GitHub tokens.

    The returned class can be added to a FastAPI/Starlette app via
    ``app.add_middleware(cls)``.

    Non-``/api/`` paths (health checks, static files) are passed through
    without authentication.

    Args:
        allowed_users: Optional allowlist of GitHub usernames.  When
            ``None``, any valid GitHub token is accepted.
        cache: Optional :class:`TokenCache` instance.  A default cache
            is created when not provided.
        client: Optional httpx client for GitHub API calls (testability).
        github_url: GitHub API URL (overridable for tests).

    Returns:
        A ``BaseHTTPMiddleware`` subclass ready for ``app.add_middleware``.
    """
    _cache = cache if cache is not None else TokenCache()
    _allowed = allowed_users
    _client = client
    _github_url = github_url

    class _TokenValidationMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            if not request.url.path.startswith("/api/"):
                return await call_next(request)  # type: ignore[no-any-return]

            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Missing authorization header",
                        "code": AUTH_MISSING_HEADER,
                    },
                )

            token = auth_header[7:]  # strip "Bearer "
            username = await validate_github_token(
                token, _cache, client=_client, github_url=_github_url
            )

            if username is None:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Invalid token",
                        "code": AUTH_INVALID_TOKEN,
                    },
                )

            if _allowed is not None and username not in _allowed:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "User not allowed",
                        "code": AUTH_USER_NOT_ALLOWED,
                    },
                )

            return await call_next(request)  # type: ignore[no-any-return]

    return _TokenValidationMiddleware
