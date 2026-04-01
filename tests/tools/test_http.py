"""Unit tests for beddel_tools_http.http — http_request tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from beddel_tools_http.http import http_request


class TestHttpRequestMetadata:
    """Tests for http_request tool metadata."""

    def test_metadata_name(self) -> None:
        meta: dict[str, str] = http_request._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "http_request"

    def test_metadata_category(self) -> None:
        meta: dict[str, str] = http_request._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["category"] == "http"

    def test_metadata_description(self) -> None:
        meta: dict[str, str] = http_request._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["description"] == "HTTP request"


class TestHttpRequestGet:
    """Tests for GET requests."""

    @patch("beddel_tools_http.http.httpx.Client")
    def test_get_returns_status_body_headers(self, mock_client_cls: Any) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.headers = {"content-type": "application/json"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Act
        result = http_request(method="GET", url="https://example.com/api")

        # Assert
        assert result["status_code"] == 200
        assert result["body"] == '{"ok": true}'
        assert result["headers"] == {"content-type": "application/json"}
        mock_client.request.assert_called_once_with(
            "GET",
            "https://example.com/api",
            headers=None,
            content=None,
        )


class TestHttpRequestPost:
    """Tests for POST requests with body."""

    @patch("beddel_tools_http.http.httpx.Client")
    def test_post_with_string_body(self, mock_client_cls: Any) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = '{"id": 1}'
        mock_response.headers = {}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Act
        result = http_request(method="POST", url="https://example.com/api", body="raw data")

        # Assert
        assert result["status_code"] == 201
        assert result["body"] == '{"id": 1}'
        mock_client.request.assert_called_once_with(
            "POST",
            "https://example.com/api",
            headers=None,
            content="raw data",
        )

    @patch("beddel_tools_http.http.httpx.Client")
    def test_post_with_dict_body_serializes_to_json(self, mock_client_cls: Any) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.headers = {}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Act
        result = http_request(
            method="POST",
            url="https://example.com/api",
            body={"key": "value"},
        )

        # Assert
        assert result["status_code"] == 200
        # Body should be JSON-serialized when dict is passed
        call_kwargs = mock_client.request.call_args
        assert call_kwargs[1]["content"] == '{"key": "value"}'


class TestHttpRequestCustomHeaders:
    """Tests for custom headers."""

    @patch("beddel_tools_http.http.httpx.Client")
    def test_custom_headers_passed_through(self, mock_client_cls: Any) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_response.headers = {}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        custom_headers = {"Authorization": "Bearer token123", "X-Custom": "value"}

        # Act
        http_request(method="GET", url="https://example.com", headers=custom_headers)

        # Assert
        mock_client.request.assert_called_once_with(
            "GET",
            "https://example.com",
            headers=custom_headers,
            content=None,
        )


class TestHttpRequestErrorHandling:
    """Tests for error status codes and HTTP errors."""

    @patch("beddel_tools_http.http.httpx.Client")
    def test_error_status_code_returned_not_raised(self, mock_client_cls: Any) -> None:
        # Arrange — 404 is returned as data, not raised
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.headers = {}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Act
        result = http_request(method="GET", url="https://example.com/missing")

        # Assert
        assert result["status_code"] == 404
        assert result["body"] == "Not Found"

    @patch("beddel_tools_http.http.httpx.Client")
    def test_500_status_code_returned(self, mock_client_cls: Any) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.headers = {"retry-after": "30"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Act
        result = http_request(method="GET", url="https://example.com/error")

        # Assert
        assert result["status_code"] == 500
        assert result["headers"] == {"retry-after": "30"}

    @patch("beddel_tools_http.http.httpx.Client")
    def test_httpx_error_raises_runtime_error(self, mock_client_cls: Any) -> None:
        # Arrange
        import httpx

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.HTTPError("Connection refused")
        mock_client_cls.return_value = mock_client

        # Act / Assert
        with pytest.raises(RuntimeError, match="Connection refused"):
            http_request(method="GET", url="https://unreachable.example.com")
