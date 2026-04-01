"""Unit tests for beddel.adapters.codex_adapter module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beddel_agent_codex.adapter import CodexAgentAdapter

from beddel.domain.errors import AgentError
from beddel.domain.ports import IAgentAdapter
from beddel.error_codes import (
    AGENT_EXECUTION_FAILED,
    AGENT_STREAM_INTERRUPTED,
    CODEX_DOCKER_UNAVAILABLE,
    CODEX_EXEC_FAILED,
    CODEX_TIMEOUT,
)

# ---------------------------------------------------------------------------
# JSONL test data
# ---------------------------------------------------------------------------

JSONL_THREAD_STARTED = '{"type": "thread.started", "thread_id": "thread_abc123"}'
JSONL_AGENT_MESSAGE = (
    '{"type": "item.completed", "item": {"type": "agent_message", "content": "Hello from Codex"}}'
)
JSONL_FILE_CHANGE = (
    '{"type": "item.completed", "item": {"type": "file_change", "path": "src/main.py"}}'
)
JSONL_TURN_COMPLETED = (
    '{"type": "turn.completed", "usage":'
    ' {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}'
)
JSONL_TURN_FAILED = '{"type": "turn.failed", "error": "Something went wrong"}'
JSONL_UNKNOWN = '{"type": "unknown.event", "data": "test"}'
JSONL_MALFORMED = "this is not json"

_PROMPT = "Analyze the codebase"
_PATCH_SUBPROCESS = "beddel_agent_codex.adapter.asyncio.create_subprocess_exec"
_PATCH_WAIT_FOR = "beddel_agent_codex.adapter.asyncio.wait_for"

ALL_JSONL = "\n".join(
    [
        JSONL_THREAD_STARTED,
        JSONL_AGENT_MESSAGE,
        JSONL_FILE_CHANGE,
        JSONL_TURN_COMPLETED,
    ]
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_process(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> AsyncMock:
    """Build a mock subprocess with canned communicate() output."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(
        return_value=(stdout.encode(), stderr.encode()),
    )
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ===================================================================
# Protocol conformance (6.2)
# ===================================================================


class TestProtocolConformance:
    def test_satisfies_iagent_adapter_protocol(self) -> None:
        adapter = CodexAgentAdapter()
        assert isinstance(adapter, IAgentAdapter)


# ===================================================================
# Constructor (6.3)
# ===================================================================


class TestConstructor:
    def test_default_values_no_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            adapter = CodexAgentAdapter()

        assert adapter._model == "gpt-5.3-codex"
        assert adapter._docker_image == "codex-universal:latest"
        assert adapter._timeout == 300
        assert adapter._workspace_dir is None

    def test_env_var_overrides(self) -> None:
        env = {
            "CODEX_MODEL": "custom-model",
            "CODEX_DOCKER_IMAGE": "my-image:v2",
            "CODEX_TIMEOUT": "60",
        }
        with patch.dict("os.environ", env, clear=True):
            adapter = CodexAgentAdapter()

        assert adapter._model == "custom-model"
        assert adapter._docker_image == "my-image:v2"
        assert adapter._timeout == 60

    def test_constructor_overrides_take_precedence(self) -> None:
        env = {
            "CODEX_MODEL": "env-model",
            "CODEX_DOCKER_IMAGE": "env-image:v1",
            "CODEX_TIMEOUT": "999",
        }
        with patch.dict("os.environ", env, clear=True):
            adapter = CodexAgentAdapter(
                model="arg-model",
                docker_image="arg-image:v3",
                timeout=42,
                workspace_dir="/tmp/ws",
            )

        assert adapter._model == "arg-model"
        assert adapter._docker_image == "arg-image:v3"
        assert adapter._timeout == 42
        assert adapter._workspace_dir == "/tmp/ws"


# ===================================================================
# _build_docker_command (6.4)
# ===================================================================


class TestBuildDockerCommand:
    def _adapter(self, workspace: str | None = "/host/project") -> CodexAgentAdapter:
        return CodexAgentAdapter(
            model="test-model",
            docker_image="codex:test",
            workspace_dir=workspace,
        )

    def test_read_only_sandbox(self) -> None:
        cmd = self._adapter()._build_docker_command(
            _PROMPT,
            model="test-model",
            sandbox="read-only",
            tools=None,
        )
        assert "-v" in cmd
        idx = cmd.index("-v")
        assert cmd[idx + 1] == "/host/project:/workspace:ro"

    def test_workspace_write_sandbox(self) -> None:
        cmd = self._adapter()._build_docker_command(
            _PROMPT,
            model="test-model",
            sandbox="workspace-write",
            tools=None,
        )
        idx = cmd.index("-v")
        assert cmd[idx + 1] == "/host/project:/workspace:rw"
        assert "--privileged" not in cmd

    def test_danger_full_access_sandbox(self) -> None:
        cmd = self._adapter()._build_docker_command(
            _PROMPT,
            model="test-model",
            sandbox="danger-full-access",
            tools=None,
        )
        idx = cmd.index("-v")
        assert cmd[idx + 1] == "/host/project:/workspace:rw"
        assert "--privileged" in cmd

    def test_network_none_always_present(self) -> None:
        cmd = self._adapter()._build_docker_command(
            _PROMPT,
            model="test-model",
            sandbox="read-only",
            tools=None,
        )
        assert "--network=none" in cmd

    def test_openai_api_key_always_present(self) -> None:
        cmd = self._adapter()._build_docker_command(
            _PROMPT,
            model="test-model",
            sandbox="read-only",
            tools=None,
        )
        idx = cmd.index("--env")
        assert cmd[idx + 1] == "OPENAI_API_KEY"

    def test_model_passed_to_codex_exec(self) -> None:
        cmd = self._adapter()._build_docker_command(
            _PROMPT,
            model="my-model",
            sandbox="read-only",
            tools=None,
        )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "my-model"

    def test_no_workspace_mount_when_none(self) -> None:
        cmd = self._adapter(workspace=None)._build_docker_command(
            _PROMPT,
            model="test-model",
            sandbox="read-only",
            tools=None,
        )
        assert "-v" not in cmd

    def test_unsupported_sandbox_raises(self) -> None:
        with pytest.raises(AgentError) as exc_info:
            self._adapter()._build_docker_command(
                _PROMPT,
                model="test-model",
                sandbox="invalid",
                tools=None,
            )
        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)


# ===================================================================
# _parse_jsonl_events (6.5-6.8)
# ===================================================================


class TestParseJsonlEvents:
    def _adapter(self) -> CodexAgentAdapter:
        return CodexAgentAdapter()

    def test_thread_started_appended(self) -> None:
        output, files, events, usage = self._adapter()._parse_jsonl_events(
            [JSONL_THREAD_STARTED],
        )
        assert len(events) == 1
        assert events[0]["type"] == "thread.started"
        assert output == ""

    def test_agent_message_extracted(self) -> None:
        output, files, events, usage = self._adapter()._parse_jsonl_events(
            [JSONL_AGENT_MESSAGE],
        )
        assert output == "Hello from Codex"

    def test_file_change_extracted(self) -> None:
        output, files, events, usage = self._adapter()._parse_jsonl_events(
            [JSONL_FILE_CHANGE],
        )
        assert files == ["src/main.py"]

    def test_turn_completed_usage_extracted(self) -> None:
        output, files, events, usage = self._adapter()._parse_jsonl_events(
            [JSONL_TURN_COMPLETED],
        )
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert usage["total_tokens"] == 150

    def test_all_event_types_happy_path(self) -> None:
        lines = [
            JSONL_THREAD_STARTED,
            JSONL_AGENT_MESSAGE,
            JSONL_FILE_CHANGE,
            JSONL_TURN_COMPLETED,
        ]
        output, files, events, usage = self._adapter()._parse_jsonl_events(lines)
        assert output == "Hello from Codex"
        assert files == ["src/main.py"]
        assert len(events) == 1
        assert usage["total_tokens"] == 150

    def test_malformed_json_skipped(self) -> None:
        lines = [JSONL_MALFORMED, JSONL_AGENT_MESSAGE]
        output, files, events, usage = self._adapter()._parse_jsonl_events(lines)
        assert output == "Hello from Codex"

    def test_turn_failed_raises_agent_error(self) -> None:
        with pytest.raises(AgentError) as exc_info:
            self._adapter()._parse_jsonl_events([JSONL_TURN_FAILED])
        assert exc_info.value.code == CODEX_EXEC_FAILED
        assert "BEDDEL-CODEX-801" in str(exc_info.value)

    def test_unknown_event_type_skipped(self) -> None:
        lines = [JSONL_UNKNOWN, JSONL_AGENT_MESSAGE]
        output, files, events, usage = self._adapter()._parse_jsonl_events(lines)
        assert output == "Hello from Codex"

    def test_empty_lines_skipped(self) -> None:
        lines = ["", "  ", JSONL_AGENT_MESSAGE]
        output, files, events, usage = self._adapter()._parse_jsonl_events(lines)
        assert output == "Hello from Codex"


# ===================================================================
# execute() (6.9-6.13)
# ===================================================================


class TestExecute:
    async def test_happy_path(self) -> None:
        adapter = CodexAgentAdapter(workspace_dir="/tmp/ws")
        proc = _mock_process(stdout=ALL_JSONL, returncode=0)

        with patch(_PATCH_SUBPROCESS, return_value=proc):
            result = await adapter.execute(_PROMPT)

        assert result.exit_code == 0
        assert result.output == "Hello from Codex"
        assert result.files_changed == ["src/main.py"]
        assert result.usage["total_tokens"] == 150
        assert result.agent_id == "codex-gpt-5.3-codex"
        assert len(result.events) == 1

    async def test_non_zero_exit_code(self) -> None:
        adapter = CodexAgentAdapter()
        proc = _mock_process(stdout="", stderr="fatal error", returncode=1)

        with (
            patch(_PATCH_SUBPROCESS, return_value=proc),
            pytest.raises(AgentError) as exc_info,
        ):
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == CODEX_EXEC_FAILED
        assert "BEDDEL-CODEX-801" in str(exc_info.value)
        assert exc_info.value.details["stderr"] == "fatal error"

    async def test_timeout_raises_codex_timeout(self) -> None:
        adapter = CodexAgentAdapter(timeout=5)
        proc = _mock_process()

        with (
            patch(_PATCH_SUBPROCESS, return_value=proc),
            patch(_PATCH_WAIT_FOR, side_effect=TimeoutError),
            pytest.raises(AgentError) as exc_info,
        ):
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == CODEX_TIMEOUT
        assert "BEDDEL-CODEX-802" in str(exc_info.value)
        assert exc_info.value.details["timeout"] == 5
        proc.kill.assert_called_once()

    async def test_docker_not_found(self) -> None:
        adapter = CodexAgentAdapter()

        with (
            patch(_PATCH_SUBPROCESS, side_effect=FileNotFoundError),
            pytest.raises(AgentError) as exc_info,
        ):
            await adapter.execute(_PROMPT)

        assert exc_info.value.code == CODEX_DOCKER_UNAVAILABLE
        assert "BEDDEL-CODEX-803" in str(exc_info.value)

    async def test_unsupported_sandbox(self) -> None:
        adapter = CodexAgentAdapter()

        with pytest.raises(AgentError) as exc_info:
            await adapter.execute(_PROMPT, sandbox="invalid-sandbox")

        assert exc_info.value.code == AGENT_EXECUTION_FAILED
        assert "BEDDEL-AGENT-701" in str(exc_info.value)
        assert "supported" in str(exc_info.value.details)

    async def test_model_override(self) -> None:
        adapter = CodexAgentAdapter(workspace_dir="/tmp/ws")
        proc = _mock_process(stdout=JSONL_AGENT_MESSAGE, returncode=0)

        with patch(_PATCH_SUBPROCESS, return_value=proc) as mock_sub:
            result = await adapter.execute(_PROMPT, model="custom-model")

        assert result.agent_id == "codex-custom-model"
        # Verify model was passed in the command
        call_args = mock_sub.call_args
        cmd_list = list(call_args.args) if call_args.args else []
        assert "custom-model" in cmd_list


# ===================================================================
# stream() (6.14-6.16)
# ===================================================================


class TestStream:
    async def test_happy_path(self) -> None:
        adapter = CodexAgentAdapter(workspace_dir="/tmp/ws")
        proc = _mock_process(stdout=ALL_JSONL, returncode=0)

        with patch(_PATCH_SUBPROCESS, return_value=proc):
            events: list[dict[str, Any]] = []
            async for event in adapter.stream(_PROMPT):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "complete"
        assert events[0]["output"] == "Hello from Codex"
        assert events[0]["exit_code"] == 0

    async def test_timeout_raises_stream_interrupted(self) -> None:
        adapter = CodexAgentAdapter(timeout=5)
        proc = _mock_process()

        with (
            patch(_PATCH_SUBPROCESS, return_value=proc),
            patch(_PATCH_WAIT_FOR, side_effect=TimeoutError),
            pytest.raises(AgentError) as exc_info,
        ):
            async for _event in adapter.stream(_PROMPT):
                pass  # pragma: no cover

        assert exc_info.value.code == AGENT_STREAM_INTERRUPTED
        assert "BEDDEL-AGENT-703" in str(exc_info.value)

    async def test_docker_not_found(self) -> None:
        adapter = CodexAgentAdapter()

        with (
            patch(_PATCH_SUBPROCESS, side_effect=FileNotFoundError),
            pytest.raises(AgentError) as exc_info,
        ):
            async for _event in adapter.stream(_PROMPT):
                pass  # pragma: no cover

        assert exc_info.value.code == CODEX_DOCKER_UNAVAILABLE
        assert "BEDDEL-CODEX-803" in str(exc_info.value)


# ===================================================================
# Registry round-trip (6.17)
# ===================================================================


class TestRegistryRoundTrip:
    def test_register_and_resolve_by_name(self) -> None:
        adapter = CodexAgentAdapter()
        registry: dict[str, Any] = {"codex": adapter}

        resolved = registry["codex"]
        assert resolved is adapter
        assert isinstance(resolved, IAgentAdapter)
