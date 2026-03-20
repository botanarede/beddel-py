"""Beddel HTTP tool — sync HTTP requests via httpx.

Provides :func:`http_request`, a builtin tool that performs HTTP requests
using ``httpx.Client`` (synchronous) and returns status code, body, and headers.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from beddel.tools import beddel_tool


@beddel_tool(name="http_request", description="HTTP request", category="http")
def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform an HTTP request and return the response.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.).
        url: Target URL.
        headers: Optional request headers.
        body: Optional request body. If a dict, it is JSON-serialized.

    Returns:
        Dict with ``status_code`` (int), ``body`` (str), and
        ``headers`` (dict).

    Raises:
        RuntimeError: When an ``httpx.HTTPError`` occurs (e.g. connection
            failure, timeout).
    """
    content: str | None = None
    if isinstance(body, dict):
        content = json.dumps(body)
    elif isinstance(body, str):
        content = body

    try:
        with httpx.Client() as client:
            response = client.request(method, url, headers=headers, content=content)
    except httpx.HTTPError as exc:
        raise RuntimeError(str(exc)) from exc

    return {
        "status_code": response.status_code,
        "body": response.text,
        "headers": dict(response.headers),
    }
