"""Unit tests for beddel.domain.ports.IAgentAdapter and beddel.domain.models.AgentResult."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from beddel.domain.models import AgentResult
from beddel.domain.ports import IAgentAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAgentAdapter:
    """Minimal concrete class satisfying the IAgentAdapter protocol."""

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Return a canned AgentResult."""
        return AgentResult(
            exit_code=0,
            output="done",
            events=[],
            files_changed=[],
            usage={},
            agent_id="stub",
        )

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield a single event dict."""
        yield {"type": "message", "text": "hello"}


# ---------------------------------------------------------------------------
# IAgentAdapter protocol conformance
# ---------------------------------------------------------------------------


class TestIAgentAdapterProtocol:
    """Tests for IAgentAdapter runtime-checkable protocol conformance."""

    def test_stub_satisfies_protocol(self) -> None:
        """A class with execute() and stream() is an IAgentAdapter instance."""
        adapter = _StubAgentAdapter()

        assert isinstance(adapter, IAgentAdapter)

    def test_protocol_is_runtime_checkable(self) -> None:
        """IAgentAdapter is decorated with @runtime_checkable."""
        assert hasattr(IAgentAdapter, "__protocol_attrs__")

    def test_object_without_methods_is_not_adapter(self) -> None:
        """A plain object does not satisfy IAgentAdapter."""

        class _Empty:
            pass

        assert not isinstance(_Empty(), IAgentAdapter)

    def test_partial_implementation_is_not_adapter(self) -> None:
        """A class with only execute() but no stream() is not an IAgentAdapter."""

        class _OnlyExecute:
            async def execute(self, prompt: str, **kwargs: Any) -> AgentResult:
                return AgentResult(0, "", [], [], {}, "x")

        assert not isinstance(_OnlyExecute(), IAgentAdapter)


# ---------------------------------------------------------------------------
# AgentResult instantiation
# ---------------------------------------------------------------------------


class TestAgentResult:
    """Tests for the AgentResult dataclass."""

    def test_all_fields_set_correctly(self) -> None:
        """All 6 fields are stored and accessible after construction."""
        events = [{"type": "tool_call", "name": "bash"}]
        usage = {"prompt_tokens": 100, "completion_tokens": 50}

        result = AgentResult(
            exit_code=0,
            output="task completed",
            events=events,
            files_changed=["src/main.py", "tests/test_main.py"],
            usage=usage,
            agent_id="codex-mini",
        )

        assert result.exit_code == 0
        assert result.output == "task completed"
        assert result.events == events
        assert result.files_changed == ["src/main.py", "tests/test_main.py"]
        assert result.usage == usage
        assert result.agent_id == "codex-mini"

    def test_non_zero_exit_code(self) -> None:
        """AgentResult accepts non-zero exit codes."""
        result = AgentResult(
            exit_code=1,
            output="error occurred",
            events=[],
            files_changed=[],
            usage={},
            agent_id="test",
        )

        assert result.exit_code == 1

    def test_empty_collections(self) -> None:
        """AgentResult works with empty lists and dicts."""
        result = AgentResult(
            exit_code=0,
            output="",
            events=[],
            files_changed=[],
            usage={},
            agent_id="empty",
        )

        assert result.events == []
        assert result.files_changed == []
        assert result.usage == {}

    def test_no_defaults_exit_code(self) -> None:
        """Omitting exit_code raises TypeError."""
        with pytest.raises(TypeError):
            AgentResult(  # type: ignore[call-arg]
                output="x",
                events=[],
                files_changed=[],
                usage={},
                agent_id="x",
            )

    def test_no_defaults_output(self) -> None:
        """Omitting output raises TypeError."""
        with pytest.raises(TypeError):
            AgentResult(  # type: ignore[call-arg]
                exit_code=0,
                events=[],
                files_changed=[],
                usage={},
                agent_id="x",
            )

    def test_no_defaults_events(self) -> None:
        """Omitting events raises TypeError."""
        with pytest.raises(TypeError):
            AgentResult(  # type: ignore[call-arg]
                exit_code=0,
                output="x",
                files_changed=[],
                usage={},
                agent_id="x",
            )

    def test_no_defaults_files_changed(self) -> None:
        """Omitting files_changed raises TypeError."""
        with pytest.raises(TypeError):
            AgentResult(  # type: ignore[call-arg]
                exit_code=0,
                output="x",
                events=[],
                usage={},
                agent_id="x",
            )

    def test_no_defaults_usage(self) -> None:
        """Omitting usage raises TypeError."""
        with pytest.raises(TypeError):
            AgentResult(  # type: ignore[call-arg]
                exit_code=0,
                output="x",
                events=[],
                files_changed=[],
                agent_id="x",
            )

    def test_no_defaults_agent_id(self) -> None:
        """Omitting agent_id raises TypeError."""
        with pytest.raises(TypeError):
            AgentResult(  # type: ignore[call-arg]
                exit_code=0,
                output="x",
                events=[],
                files_changed=[],
                usage={},
            )
