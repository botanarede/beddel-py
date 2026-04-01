"""Unit tests for beddel.adapters.openclaw_adapter module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from _helpers import make_context
from beddel_agent_openclaw.adapter import OpenClawAgentAdapter

from beddel.domain.errors import AgentError
from beddel.domain.models import DefaultDependencies
from beddel.domain.ports import IAgentAdapter
from beddel.error_codes import (
    AGENT_EXECUTION_FAILED,
    AGENT_STREAM_INTERRUPTED,
    AGENT_TIMEOUT,
)
from beddel.primitives.agent_exec import AgentExecPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROMPT = "Analyze the codebase"
_PATCH_CLIENT = "beddel_agent_openclaw.adapter.httpx.AsyncClient"

_VALID_RESPONSE_JSON: dict[str, Any] = {
    "choices": [{"message": {"content": "Hello"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _mock_httpx_ok(
    *,
    json_data: dict[str, Any] | None = None,
    status_code: int = 200,
    text: str = "",
) -> tuple[MagicMock, AsyncMock]:
    """Build a patched ``httpx.AsyncClient`` returning a canned response.

    Returns:
        A tuple of (mock_client_cls, mock_client) for assertion access.
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data or _VALID_RESPONSE_JSON
    mock_response.text = text

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    return mock_client_cls, mock_client


# ===================================================================
# Protocol conformance (AC 1)
# ===================================================================


class TestProtocolConformance:
    def test_satisfies_iagent_adapter_protocol(self) -> None:
        adapter = OpenClawAgentAdapter()
        assert isinstance(adapter, IAgentAdapter)


# ===================================================================
# Constructor (AC 3)
# ===================================================================


class TestConstructor:
    def test_default_values(self) -> None:
        adapter = OpenClawAgentAdapter()

        assert adapter._gateway_url == "http://localhost:3000"
        assert adapter._agent == "main"
        assert adapter._model is None
        assert adapter._timeout == 120

    def test_custom_values(self) -> None:
        adapter = OpenClawAgentAdapter(
            gateway_url="http://gateway:8080",
            agent="architect",
            model="gpt-5",
            timeout=60,
        )

        assert adapter._gateway_url == "http://gateway:8080"
        assert adapter._agent == "architect"
        assert adapter._model == "gpt-5"
        assert adapter._timeout == 60


# ===================================================================
# _build_payload (AC 4, 5, 7)
# ===================================================================


class TestBuildPayload:
    def test_read_only_sandbox(self) -> None:
        adapter = OpenClawAgentAdapter(agent="main")

        payload = adapter._build_payload(
            _PROMPT,
            model=None,
            sandbox="read-only",
            tools=None,
        )

        system_msg = payload["messages"][0]["content"]
        assert "main" in system_msg
        assert "Tool authorization" not in system_msg

    def test_workspace_write_sandbox(self) -> None:
        adapter = OpenClawAgentAdapter(agent="main")

        payload = adapter._build_payload(
            _PROMPT,
            model=None,
            sandbox="workspace-write",
            tools=None,
        )

        system_msg = payload["messages"][0]["content"]
        assert "workspace-write" in system_msg

    def test_danger_full_access_sandbox(self) -> None:
        adapter = OpenClawAgentAdapter(agent="main")

        payload = adapter._build_payload(
            _PROMPT,
            model=None,
            sandbox="danger-full-access",
            tools=None,
        )

        system_msg = payload["messages"][0]["content"]
        assert "danger-full-access" in system_msg

    def test_model_included_when_provided(self) -> None:
        adapter = OpenClawAgentAdapter()

        payload = adapter._build_payload(
            _PROMPT,
            model="gpt-5",
            sandbox="read-only",
            tools=None,
        )

        assert payload["model"] == "gpt-5"

    def test_model_omitted_when_none(self) -> None:
        adapter = OpenClawAgentAdapter()

        payload = adapter._build_payload(
            _PROMPT,
            model=None,
            sandbox="read-only",
            tools=None,
        )

        assert "model" not in payload

    def test_tools_included_when_provided(self) -> None:
        adapter = OpenClawAgentAdapter()

        payload = adapter._build_payload(
            _PROMPT,
            model=None,
            sandbox="read-only",
            tools=["tool1", "tool2"],
        )

        assert payload["tools"] == ["tool1", "tool2"]

    def test_tools_omitted_when_none(self) -> None:
        adapter = OpenClawAgentAdapter()

        payload = adapter._build_payload(
            _PROMPT,
            model=None,
            sandbox="read-only",
            tools=None,
        )

        assert "tools" not in payload


# ===================================================================
# execute() (AC 2, 4, 5, 7, 8)
# ===================================================================


class TestExecute:
    async def test_happy_path(self) -> None:
        adapter = OpenClawAgentAdapter()
        mock_cls, mock_client = _mock_httpx_ok()

        with patch(_PATCH_CLIENT, mock_cls):
            result = await adapter.execute(_PROMPT)

        assert result.exit_code == 0
        assert result.output == "Hello"
        assert result.events == []
        assert result.files_changed == []
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}
        assert result.agent_id == "openclaw-main"

    async def test_connection_refused(self) -> None:
        adapter = OpenClawAgentAdapter()
        mock_cls = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_CLIENT, mock_cls), pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)

    async def test_timeout(self) -> None:
        adapter = OpenClawAgentAdapter(timeout=5)
        mock_cls = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_CLIENT, mock_cls), pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_TIMEOUT
        assert "BEDDEL-AGENT-702" in str(exc_info.value)
        assert exc_info.value.details["timeout"] == 5

    async def test_non_200_response(self) -> None:
        adapter = OpenClawAgentAdapter()
        mock_cls, _ = _mock_httpx_ok(
            status_code=500,
            text="Internal Server Error",
        )

        with patch(_PATCH_CLIENT, mock_cls), pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)
        assert exc_info.value.details["body"] == "Internal Server Error"

    async def test_agent_selection(self) -> None:
        adapter = OpenClawAgentAdapter(agent="architect")
        mock_cls, mock_client = _mock_httpx_ok()

        with patch(_PATCH_CLIENT, mock_cls):
            await adapter.execute(_PROMPT)

        # Inspect the payload sent to post()
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        system_msg = payload["messages"][0]["content"]
        assert "architect" in system_msg

    async def test_sandbox_unsupported(self) -> None:
        adapter = OpenClawAgentAdapter()

        with pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT, sandbox="invalid")

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)
        assert exc_info.value.details["sandbox"] == "invalid"

    async def test_model_override(self) -> None:
        adapter = OpenClawAgentAdapter(model="default-model")
        mock_cls, mock_client = _mock_httpx_ok()

        with patch(_PATCH_CLIENT, mock_cls):
            await adapter.execute(_PROMPT, model="gpt-5")

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        assert payload["model"] == "gpt-5"

    async def test_tools_in_payload(self) -> None:
        adapter = OpenClawAgentAdapter()
        mock_cls, mock_client = _mock_httpx_ok()

        with patch(_PATCH_CLIENT, mock_cls):
            await adapter.execute(_PROMPT, tools=["tool1", "tool2"])

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        assert payload["tools"] == ["tool1", "tool2"]


# ===================================================================
# stream() (AC 6)
# ===================================================================


class TestStream:
    async def test_happy_path(self) -> None:
        adapter = OpenClawAgentAdapter()
        mock_cls, _ = _mock_httpx_ok()

        with patch(_PATCH_CLIENT, mock_cls):
            events: list[dict[str, Any]] = []
            async for event in adapter.stream(_PROMPT):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "complete"
        assert events[0]["output"] == "Hello"
        assert events[0]["exit_code"] == 0

    async def test_timeout_raises_stream_interrupted(self) -> None:
        adapter = OpenClawAgentAdapter(timeout=5)
        mock_cls = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_CLIENT, mock_cls), pytest.raises(AgentError) as exc_info:
            async for _event in adapter.stream(_PROMPT):
                pass  # pragma: no cover

        assert exc_info.value.code == AGENT_STREAM_INTERRUPTED
        assert "BEDDEL-AGENT-703" in str(exc_info.value)


# ===================================================================
# Registry round-trip integration (AC 10)
# ===================================================================


class TestRegistryRoundTrip:
    async def test_adapter_registered_and_resolved(self) -> None:
        adapter = OpenClawAgentAdapter()
        ctx = make_context(workflow_id="wf-openclaw-roundtrip")
        ctx.deps = DefaultDependencies(agent_registry={"openclaw": adapter})

        mock_cls, _ = _mock_httpx_ok()

        with patch(_PATCH_CLIENT, mock_cls):
            result = await AgentExecPrimitive().execute(
                {"adapter": "openclaw", "prompt": "echo hello"},
                ctx,
            )

        assert isinstance(result, dict)
        assert set(result.keys()) == {"output", "files_changed", "usage"}
        assert result["output"] == "Hello"
        assert result["files_changed"] == []
        assert isinstance(result["usage"], dict)
