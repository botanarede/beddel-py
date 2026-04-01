"""Unit tests for beddel.adapters.claude_adapter module."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from _helpers import make_context

from beddel.domain.errors import AgentError
from beddel.domain.models import DefaultDependencies
from beddel.domain.ports import IAgentAdapter
from beddel.error_codes import (
    AGENT_EXECUTION_FAILED,
    AGENT_NOT_CONFIGURED,
    AGENT_STREAM_INTERRUPTED,
    AGENT_TIMEOUT,
)
from beddel.primitives.agent_exec import AgentExecPrimitive

# ---------------------------------------------------------------------------
# Mock claude_agent_sdk types (package is NOT installed)
# ---------------------------------------------------------------------------

_PROMPT = "Analyze the codebase"


@dataclass
class TextBlock:
    """Mock for ``claude_agent_sdk.TextBlock``."""

    text: str


@dataclass
class ToolUseBlock:
    """Mock for ``claude_agent_sdk.ToolUseBlock``."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class AssistantMessage:
    """Mock for ``claude_agent_sdk.AssistantMessage``."""

    content: list[Any]


@dataclass
class ResultMessage:
    """Mock for ``claude_agent_sdk.ResultMessage``."""

    subtype: str = "success"
    is_error: bool = False
    result: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    num_turns: int = 1
    session_id: str = "test-session"
    duration_ms: int = 1000
    duration_api_ms: int = 900
    cost_usd: float | None = None
    exit_code: int = 0
    text: str = ""


class CLINotFoundError(Exception):
    """Mock for ``claude_agent_sdk.CLINotFoundError``."""


class ProcessError(Exception):
    """Mock for ``claude_agent_sdk.ProcessError``."""

    def __init__(
        self,
        message: str = "",
        exit_code: int | None = None,
        stderr: str | None = None,
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ClaudeAgentOptions:
    """Mock for ``claude_agent_sdk.ClaudeAgentOptions``."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


# Build the mock module and inject into sys.modules so the adapter
# can ``import claude_agent_sdk`` at runtime without the real package.
_mock_sdk = MagicMock()
_mock_sdk.ClaudeAgentOptions = ClaudeAgentOptions
_mock_sdk.CLINotFoundError = CLINotFoundError
_mock_sdk.ProcessError = ProcessError
sys.modules["claude_agent_sdk"] = _mock_sdk

from beddel_agent_claude.adapter import ClaudeAgentAdapter  # noqa: E402, I001


# ---------------------------------------------------------------------------
# Async generator helper for mocking query()
# ---------------------------------------------------------------------------


async def _mock_query_gen(*messages: Any) -> Any:
    """Yield *messages* as an async generator (simulates ``query()``)."""
    for msg in messages:
        yield msg


def _patch_query(*messages: Any) -> None:
    """Patch ``_mock_sdk.query`` to return an async generator of *messages*."""
    _mock_sdk.query = MagicMock(return_value=_mock_query_gen(*messages))


# ===================================================================
# Protocol conformance
# ===================================================================


class TestProtocolConformance:
    def test_satisfies_iagent_adapter_protocol(self) -> None:
        adapter = ClaudeAgentAdapter()
        assert isinstance(adapter, IAgentAdapter)


# ===================================================================
# Constructor
# ===================================================================


class TestConstructor:
    def test_default_values(self) -> None:
        adapter = ClaudeAgentAdapter()

        assert adapter._model == "claude-sonnet-4"
        assert adapter._max_turns == 25
        assert adapter._timeout == 300
        assert adapter._permission_mode == "bypassPermissions"
        assert adapter._cwd is None

    def test_custom_values(self) -> None:
        adapter = ClaudeAgentAdapter(
            model="claude-opus-4",
            max_turns=10,
            timeout=60,
            permission_mode="plan",
            cwd="/tmp/workspace",
        )

        assert adapter._model == "claude-opus-4"
        assert adapter._max_turns == 10
        assert adapter._timeout == 60
        assert adapter._permission_mode == "plan"
        assert adapter._cwd == "/tmp/workspace"


# ===================================================================
# _build_options
# ===================================================================


class TestBuildOptions:
    def test_read_only_sandbox(self) -> None:
        adapter = ClaudeAgentAdapter()
        opts = adapter._build_options(_PROMPT, sandbox="read-only")
        assert opts["permission_mode"] == "plan"

    def test_workspace_write_sandbox(self) -> None:
        adapter = ClaudeAgentAdapter()
        opts = adapter._build_options(_PROMPT, sandbox="workspace-write")
        assert opts["permission_mode"] == "acceptEdits"

    def test_danger_full_access_sandbox(self) -> None:
        adapter = ClaudeAgentAdapter()
        opts = adapter._build_options(_PROMPT, sandbox="danger-full-access")
        assert opts["permission_mode"] == "bypassPermissions"

    def test_unsupported_sandbox(self) -> None:
        adapter = ClaudeAgentAdapter()
        with pytest.raises(AgentError) as exc_info:
            adapter._build_options(_PROMPT, sandbox="invalid")

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)
        assert exc_info.value.details["sandbox"] == "invalid"

    def test_tools_mapped_to_allowed_tools(self) -> None:
        adapter = ClaudeAgentAdapter()
        opts = adapter._build_options(_PROMPT, tools=["Read", "Write"])
        assert opts["allowed_tools"] == ["Read", "Write"]

    def test_output_schema_mapped_to_output_format(self) -> None:
        adapter = ClaudeAgentAdapter()
        schema = {"type": "object", "properties": {"result": {"type": "string"}}}
        opts = adapter._build_options(_PROMPT, output_schema=schema)
        assert opts["output_format"] == {"type": "json_schema", "schema": schema}

    def test_cwd_included_when_set(self) -> None:
        adapter = ClaudeAgentAdapter(cwd="/tmp")
        opts = adapter._build_options(_PROMPT)
        assert opts["cwd"] == "/tmp"

    def test_model_override(self) -> None:
        adapter = ClaudeAgentAdapter(model="claude-sonnet-4")
        opts = adapter._build_options(_PROMPT, model="claude-opus-4")
        assert opts["model"] == "claude-opus-4"


# ===================================================================
# execute()
# ===================================================================


class TestExecute:
    async def test_happy_path(self) -> None:
        adapter = ClaudeAgentAdapter()

        assistant = AssistantMessage(
            content=[TextBlock(text="Hello world")],
        )
        result_msg = ResultMessage(
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            cost_usd=0.01,
            exit_code=0,
        )
        _patch_query(assistant, result_msg)

        result = await adapter.execute(_PROMPT)

        assert result.exit_code == 0
        assert result.output == "Hello world"
        assert result.events == []
        assert result.files_changed == []
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5
        assert result.usage["cost_usd"] == 0.01
        assert result.agent_id == "claude-agent-sdk"

    async def test_import_error(self) -> None:
        adapter = ClaudeAgentAdapter()

        saved = sys.modules.get("claude_agent_sdk")
        sys.modules["claude_agent_sdk"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(AgentError) as exc_info:
                await adapter.execute(_PROMPT)

            assert exc_info.value.code == AGENT_NOT_CONFIGURED
            assert "BEDDEL-AGENT-700" in str(exc_info.value)
        finally:
            if saved is not None:
                sys.modules["claude_agent_sdk"] = saved

    async def test_cli_not_found(self) -> None:
        adapter = ClaudeAgentAdapter()

        async def _raise_cli_not_found(**kwargs: Any) -> Any:
            raise CLINotFoundError("CLI not found")
            yield  # pragma: no cover  # noqa: B027

        _mock_sdk.query = MagicMock(return_value=_raise_cli_not_found())

        with pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_NOT_CONFIGURED
        assert "BEDDEL-AGENT-700" in str(exc_info.value)

    async def test_process_error(self) -> None:
        adapter = ClaudeAgentAdapter()

        async def _raise_process_error(**kwargs: Any) -> Any:
            raise ProcessError("build failed", stderr="error: syntax")
            yield  # pragma: no cover  # noqa: B027

        _mock_sdk.query = MagicMock(return_value=_raise_process_error())

        with pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)
        assert exc_info.value.details["stderr"] == "error: syntax"

    async def test_timeout(self) -> None:
        adapter = ClaudeAgentAdapter(timeout=0)

        async def _slow_query(**kwargs: Any) -> Any:
            import asyncio

            await asyncio.sleep(10)
            yield ResultMessage()  # pragma: no cover

        _mock_sdk.query = MagicMock(return_value=_slow_query())

        with pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_TIMEOUT
        assert "BEDDEL-AGENT-702" in str(exc_info.value)
        assert exc_info.value.details["timeout"] == 0

    async def test_files_changed_from_write_tool(self) -> None:
        adapter = ClaudeAgentAdapter()

        assistant = AssistantMessage(
            content=[
                ToolUseBlock(
                    id="tool-1",
                    name="Write",
                    input={"file_path": "/tmp/test.py"},
                ),
            ],
        )
        result_msg = ResultMessage()
        _patch_query(assistant, result_msg)

        result = await adapter.execute(_PROMPT)

        assert result.files_changed == ["/tmp/test.py"]

    async def test_files_changed_from_edit_tool(self) -> None:
        adapter = ClaudeAgentAdapter()

        assistant = AssistantMessage(
            content=[
                ToolUseBlock(
                    id="tool-2",
                    name="Edit",
                    input={"file_path": "/tmp/test.py"},
                ),
            ],
        )
        result_msg = ResultMessage()
        _patch_query(assistant, result_msg)

        result = await adapter.execute(_PROMPT)

        assert result.files_changed == ["/tmp/test.py"]

    async def test_usage_from_result_message(self) -> None:
        adapter = ClaudeAgentAdapter()

        result_msg = ResultMessage(
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            cost_usd=0.05,
        )
        _patch_query(result_msg)

        result = await adapter.execute(_PROMPT)

        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 50
        assert result.usage["cost_usd"] == 0.05

    async def test_unsupported_sandbox(self) -> None:
        adapter = ClaudeAgentAdapter()

        with pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT, sandbox="invalid")

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)

    async def test_tools_passed_as_allowed_tools(self) -> None:
        adapter = ClaudeAgentAdapter()

        result_msg = ResultMessage()
        _patch_query(result_msg)

        await adapter.execute(_PROMPT, tools=["Read", "Write"])

        # Verify ClaudeAgentOptions was constructed with allowed_tools
        call_args = _mock_sdk.query.call_args
        options = call_args.kwargs.get("options") or call_args[1]["options"]
        assert hasattr(options, "allowed_tools")
        assert options.allowed_tools == ["Read", "Write"]

    async def test_output_schema_mapped(self) -> None:
        adapter = ClaudeAgentAdapter()

        result_msg = ResultMessage()
        _patch_query(result_msg)

        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        await adapter.execute(_PROMPT, output_schema=schema)

        call_args = _mock_sdk.query.call_args
        options = call_args.kwargs.get("options") or call_args[1]["options"]
        assert hasattr(options, "output_format")
        assert options.output_format == {"type": "json_schema", "schema": schema}


# ===================================================================
# stream()
# ===================================================================


class TestStream:
    async def test_yields_text_events(self) -> None:
        adapter = ClaudeAgentAdapter()

        assistant = AssistantMessage(
            content=[TextBlock(text="streaming text")],
        )
        _patch_query(assistant)

        events: list[dict[str, Any]] = []
        async for event in adapter.stream(_PROMPT):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "text"
        assert events[0]["text"] == "streaming text"

    async def test_yields_tool_use_events(self) -> None:
        adapter = ClaudeAgentAdapter()

        assistant = AssistantMessage(
            content=[
                ToolUseBlock(
                    id="tool-1",
                    name="Read",
                    input={"file_path": "/tmp/foo.py"},
                ),
            ],
        )
        _patch_query(assistant)

        events: list[dict[str, Any]] = []
        async for event in adapter.stream(_PROMPT):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "tool_use"
        assert events[0]["name"] == "Read"
        assert events[0]["input"] == {"file_path": "/tmp/foo.py"}
        assert events[0]["id"] == "tool-1"

    async def test_yields_complete_event(self) -> None:
        adapter = ClaudeAgentAdapter()

        result_msg = ResultMessage(
            text="done",
            exit_code=0,
            usage={"prompt_tokens": 5},
            cost_usd=0.001,
        )
        _patch_query(result_msg)

        events: list[dict[str, Any]] = []
        async for event in adapter.stream(_PROMPT):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "complete"
        assert events[0]["output"] == "done"
        assert events[0]["exit_code"] == 0
        assert events[0]["usage"] == {"prompt_tokens": 5}
        assert events[0]["cost_usd"] == 0.001

    async def test_import_error(self) -> None:
        adapter = ClaudeAgentAdapter()

        saved = sys.modules.get("claude_agent_sdk")
        sys.modules["claude_agent_sdk"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(AgentError) as exc_info:
                async for _event in adapter.stream(_PROMPT):
                    pass  # pragma: no cover

            assert exc_info.value.code == AGENT_NOT_CONFIGURED
            assert "BEDDEL-AGENT-700" in str(exc_info.value)
        finally:
            if saved is not None:
                sys.modules["claude_agent_sdk"] = saved

    async def test_timeout(self) -> None:
        adapter = ClaudeAgentAdapter()

        async def _raise_timeout(**kwargs: Any) -> Any:
            raise TimeoutError("timed out")
            yield  # pragma: no cover  # noqa: B027

        _mock_sdk.query = MagicMock(return_value=_raise_timeout())

        with pytest.raises(AgentError) as exc_info:
            async for _event in adapter.stream(_PROMPT):
                pass  # pragma: no cover

        assert exc_info.value.code == AGENT_STREAM_INTERRUPTED
        assert "BEDDEL-AGENT-703" in str(exc_info.value)


# ===================================================================
# Registry round-trip integration
# ===================================================================


class TestRegistryRoundTrip:
    async def test_adapter_in_registry(self) -> None:
        adapter = ClaudeAgentAdapter()
        ctx = make_context(workflow_id="wf-claude-roundtrip")
        ctx.deps = DefaultDependencies(agent_registry={"claude": adapter})

        assistant = AssistantMessage(
            content=[TextBlock(text="registry result")],
        )
        result_msg = ResultMessage(
            usage={"prompt_tokens": 8, "completion_tokens": 3},
        )
        _patch_query(assistant, result_msg)

        result = await AgentExecPrimitive().execute(
            {"adapter": "claude", "prompt": "echo hello"},
            ctx,
        )

        assert isinstance(result, dict)
        assert set(result.keys()) == {"output", "files_changed", "usage"}
        assert result["output"] == "registry result"
        assert result["files_changed"] == []
        assert isinstance(result["usage"], dict)
