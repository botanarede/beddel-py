"""Unit tests for beddel.adapters.kiro_cli module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _helpers import make_context

from beddel.adapters.kiro_cli import _DEFAULT_CLI_PATH, KiroCLIAgentAdapter
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

_PROMPT = "Write a hello world program"
_PATCH_EXEC = "beddel.adapters.kiro_cli.asyncio.create_subprocess_exec"
_PATCH_WAIT = "beddel.adapters.kiro_cli.asyncio.wait_for"


def _make_mock_process(
    *,
    stdout: bytes = b"Hello, world!",
    stderr: bytes = b"",
    returncode: int = 0,
) -> AsyncMock:
    """Build a mock async subprocess process object."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    # kill() is synchronous on asyncio.subprocess.Process
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ===================================================================
# Protocol conformance (AC 1)
# ===================================================================


class TestProtocolConformance:
    def test_satisfies_iagent_adapter_protocol(self) -> None:
        adapter = KiroCLIAgentAdapter()
        assert isinstance(adapter, IAgentAdapter)


# ===================================================================
# Constructor (AC 3)
# ===================================================================


class TestConstructor:
    def test_default_values(self) -> None:
        adapter = KiroCLIAgentAdapter()

        assert adapter._model == "claude-sonnet-4.6"
        assert adapter._cli_path == _DEFAULT_CLI_PATH
        assert adapter._timeout == 600

    def test_custom_values(self) -> None:
        custom_path = Path("/usr/local/bin/kiro-cli")
        adapter = KiroCLIAgentAdapter(
            model="claude-opus-4",
            cli_path=custom_path,
            timeout=120,
        )

        assert adapter._model == "claude-opus-4"
        assert adapter._cli_path == custom_path
        assert adapter._timeout == 120

    def test_cli_path_auto_discovery(self) -> None:
        adapter = KiroCLIAgentAdapter(cli_path=None)

        expected = Path.home() / ".local" / "bin" / "kiro-cli"
        assert adapter._cli_path == expected


# ===================================================================
# _build_command (AC 4, 5)
# ===================================================================


class TestBuildCommand:
    def test_sandbox_read_only(self) -> None:
        adapter = KiroCLIAgentAdapter()

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-sonnet-4.6",
            sandbox="read-only",
            tools=None,
        )

        assert "--trust-tools=" in cmd
        assert "-a" not in cmd

    def test_sandbox_workspace_write(self) -> None:
        adapter = KiroCLIAgentAdapter()

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-sonnet-4.6",
            sandbox="workspace-write",
            tools=None,
        )

        assert "-a" in cmd
        assert "--trust-tools=" not in cmd

    def test_sandbox_danger_full_access(self) -> None:
        adapter = KiroCLIAgentAdapter()

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-sonnet-4.6",
            sandbox="danger-full-access",
            tools=None,
        )

        assert "-a" in cmd
        assert "--trust-tools=" not in cmd

    def test_model_override(self) -> None:
        adapter = KiroCLIAgentAdapter(model="claude-sonnet-4.6")

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-opus-4",
            sandbox="read-only",
            tools=None,
        )

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-opus-4"

    def test_tools_single_agent(self) -> None:
        adapter = KiroCLIAgentAdapter()

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-sonnet-4.6",
            sandbox="read-only",
            tools=["my-agent"],
        )

        assert "--agent" in cmd
        agent_idx = cmd.index("--agent")
        assert cmd[agent_idx + 1] == "my-agent"

    def test_tools_none_ignored(self) -> None:
        adapter = KiroCLIAgentAdapter()

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-sonnet-4.6",
            sandbox="read-only",
            tools=None,
        )

        assert "--agent" not in cmd

    def test_tools_multiple_raises(self) -> None:
        """Multi-element tools list raises AgentError (CLI supports one --agent)."""
        adapter = KiroCLIAgentAdapter()

        with pytest.raises(AgentError) as exc_info:
            adapter._build_command(
                _PROMPT,
                model="claude-sonnet-4.6",
                sandbox="read-only",
                tools=["agent-a", "agent-b"],
            )

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "at most one" in exc_info.value.message.lower()
        assert exc_info.value.details["tools"] == ["agent-a", "agent-b"]

    def test_tools_empty_list_ignored(self) -> None:
        """Empty tools list produces no --agent flag."""
        adapter = KiroCLIAgentAdapter()

        cmd = adapter._build_command(
            _PROMPT,
            model="claude-sonnet-4.6",
            sandbox="read-only",
            tools=[],
        )

        assert "--agent" not in cmd

    def test_sandbox_unknown_raises(self) -> None:
        """Unknown sandbox value raises AgentError."""
        adapter = KiroCLIAgentAdapter()

        with pytest.raises(AgentError) as exc_info:
            adapter._build_command(
                _PROMPT,
                model="claude-sonnet-4.6",
                sandbox="unknown-mode",
                tools=None,
            )

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "sandbox" in exc_info.value.message.lower()
        assert exc_info.value.details["sandbox"] == "unknown-mode"

    def test_sandbox_empty_string_raises(self) -> None:
        """Empty string sandbox raises AgentError."""
        adapter = KiroCLIAgentAdapter()

        with pytest.raises(AgentError) as exc_info:
            adapter._build_command(
                _PROMPT,
                model="claude-sonnet-4.6",
                sandbox="",
                tools=None,
            )

        assert exc_info.value.code == AGENT_EXECUTION_FAILED

    @pytest.mark.asyncio
    async def test_output_schema_not_in_command(self) -> None:
        adapter = KiroCLIAgentAdapter()
        mock_proc = _make_mock_process()

        with patch(
            _PATCH_EXEC,
            return_value=mock_proc,
        ) as mock_exec:
            await adapter.execute(
                _PROMPT,
                output_schema={
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                },
            )

            call_args = mock_exec.call_args[0]
            cmd_str = " ".join(str(a) for a in call_args)
            assert "output_schema" not in cmd_str
            assert "schema" not in cmd_str


# ===================================================================
# execute() (AC 2, 7)
# ===================================================================


class TestExecute:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        adapter = KiroCLIAgentAdapter()
        mock_proc = _make_mock_process(
            stdout=b"Task completed successfully",
        )

        with patch(_PATCH_EXEC, return_value=mock_proc):
            result = await adapter.execute(_PROMPT)

        assert result.exit_code == 0
        assert result.output == "Task completed successfully"
        assert result.agent_id == "kiro-cli"
        assert result.events == []
        assert result.files_changed == []
        assert result.usage == {
            "model": "claude-sonnet-4.6",
            "timeout": 600,
        }

    @pytest.mark.asyncio
    async def test_non_zero_exit_code(self) -> None:
        adapter = KiroCLIAgentAdapter()
        mock_proc = _make_mock_process(
            stdout=b"",
            stderr=b"Error: something went wrong",
            returncode=1,
        )

        with (
            patch(_PATCH_EXEC, return_value=mock_proc),
            pytest.raises(AgentError) as exc_info,
        ):
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)
        assert exc_info.value.details["exit_code"] == 1
        assert exc_info.value.details["stderr"] == "Error: something went wrong"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        adapter = KiroCLIAgentAdapter(timeout=5)
        mock_proc = _make_mock_process()

        with (
            patch(_PATCH_EXEC, return_value=mock_proc),
            patch(_PATCH_WAIT, side_effect=TimeoutError),
            pytest.raises(AgentError) as exc_info,
        ):
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == AGENT_TIMEOUT
        assert "BEDDEL-AGENT-702" in str(exc_info.value)
        assert exc_info.value.details["timeout"] == 5
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


# ===================================================================
# stream() (AC 6)
# ===================================================================


class TestStream:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        adapter = KiroCLIAgentAdapter()
        mock_proc = _make_mock_process(stdout=b"Stream output here")

        with patch(_PATCH_EXEC, return_value=mock_proc):
            events: list[dict[str, Any]] = []
            async for event in adapter.stream(_PROMPT):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "complete"
        assert events[0]["output"] == "Stream output here"
        assert events[0]["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_timeout_raises_stream_interrupted(self) -> None:
        adapter = KiroCLIAgentAdapter(timeout=5)
        mock_proc = _make_mock_process()

        with (
            patch(_PATCH_EXEC, return_value=mock_proc),
            patch(_PATCH_WAIT, side_effect=TimeoutError),
            pytest.raises(AgentError) as exc_info,
        ):
            async for _event in adapter.stream(_PROMPT):
                pass  # pragma: no cover

        assert exc_info.value.code == AGENT_STREAM_INTERRUPTED
        assert "BEDDEL-AGENT-703" in str(exc_info.value)


# ===================================================================
# Registry round-trip integration (AC 8)
# ===================================================================


class TestRegistryRoundTrip:
    """Integration tests proving the full adapter registry round-trip.

    Exercises the complete cycle: ``agent_registry`` resolution →
    ``AgentExecPrimitive`` → ``KiroCLIAgentAdapter.execute()`` →
    ``AgentResult`` → plain dict.
    """

    @pytest.mark.asyncio
    async def test_adapter_registered_and_resolved_via_agent_exec(self) -> None:
        """Register adapter as 'kiro-cli', execute via AgentExecPrimitive."""
        # Arrange
        adapter = KiroCLIAgentAdapter()
        ctx = make_context(workflow_id="wf-registry-roundtrip")
        ctx.deps = DefaultDependencies(agent_registry={"kiro-cli": adapter})

        mock_proc = _make_mock_process(stdout=b"hello", returncode=0)

        # Act
        with patch(_PATCH_EXEC, return_value=mock_proc):
            result = await AgentExecPrimitive().execute(
                {"adapter": "kiro-cli", "prompt": "echo hello"},
                ctx,
            )

        # Assert
        assert isinstance(result, dict)
        assert set(result.keys()) == {"output", "files_changed", "usage"}
        assert result["output"] == "hello"
        assert result["files_changed"] == []
        assert isinstance(result["usage"], dict)
        assert "model" in result["usage"]

    @pytest.mark.asyncio
    async def test_result_usage_contains_model_and_timeout(self) -> None:
        """Verify usage metadata includes default model and timeout."""
        # Arrange
        adapter = KiroCLIAgentAdapter()
        ctx = make_context(workflow_id="wf-registry-usage")
        ctx.deps = DefaultDependencies(agent_registry={"kiro-cli": adapter})

        mock_proc = _make_mock_process(stdout=b"hello", returncode=0)

        # Act
        with patch(_PATCH_EXEC, return_value=mock_proc):
            result = await AgentExecPrimitive().execute(
                {"adapter": "kiro-cli", "prompt": "echo hello"},
                ctx,
            )

        # Assert
        assert result["usage"]["model"] == "claude-sonnet-4.6"
        assert result["usage"]["timeout"] == 600
