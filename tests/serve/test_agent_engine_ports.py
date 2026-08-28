"""Unit tests for beddel.serve.agent_engine ports, models, and import boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from beddel.serve import AgentInfo, ChatChunk, IAgentRuntimeAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockAdapter:
    """Minimal concrete class satisfying the IAgentRuntimeAdapter protocol."""

    async def list_agents(self) -> list[AgentInfo]:
        return [AgentInfo(resource_name="test/agent/1", display_name="Test")]

    async def chat(
        self,
        resource_name: str,
        message: str,
        *,
        session_id: str | None = None,
    ) -> AsyncGenerator[ChatChunk, None]:
        yield ChatChunk(text="hello", session_id="s1")
        yield ChatChunk(text="", done=True)


# ---------------------------------------------------------------------------
# IAgentRuntimeAdapter protocol conformance
# ---------------------------------------------------------------------------


class TestIAgentRuntimeAdapterProtocol:
    """Tests for IAgentRuntimeAdapter runtime-checkable protocol conformance."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """IAgentRuntimeAdapter supports isinstance() checks (i.e. is @runtime_checkable).

        A Protocol not decorated with @runtime_checkable raises TypeError on
        isinstance(). Calling isinstance() here is itself the proof: a
        conforming object passes and a non-conforming object does not, which
        is only possible if IAgentRuntimeAdapter is runtime-checkable.
        """
        assert isinstance(_MockAdapter(), IAgentRuntimeAdapter)

        class _Empty:
            pass

        assert not isinstance(_Empty(), IAgentRuntimeAdapter)

    def test_mock_satisfies_protocol(self) -> None:
        """A class implementing both methods passes isinstance check."""
        adapter = _MockAdapter()
        assert isinstance(adapter, IAgentRuntimeAdapter)

    def test_object_without_methods_is_not_adapter(self) -> None:
        """A plain object does not satisfy IAgentRuntimeAdapter."""

        class _Empty:
            pass

        assert not isinstance(_Empty(), IAgentRuntimeAdapter)

    def test_partial_implementation_missing_chat(self) -> None:
        """A class with only list_agents() does not satisfy the protocol."""

        class _OnlyListAgents:
            async def list_agents(self) -> list[AgentInfo]:
                return []

        assert not isinstance(_OnlyListAgents(), IAgentRuntimeAdapter)

    def test_partial_implementation_missing_list_agents(self) -> None:
        """A class with only chat() does not satisfy the protocol."""

        class _OnlyChat:
            async def chat(
                self,
                resource_name: str,
                message: str,
                *,
                session_id: str | None = None,
            ) -> AsyncGenerator[ChatChunk, None]:
                yield ChatChunk(text="x")

        assert not isinstance(_OnlyChat(), IAgentRuntimeAdapter)


# ---------------------------------------------------------------------------
# beddel.serve public API exports
# ---------------------------------------------------------------------------


class TestServeExports:
    """Tests verifying beddel.serve exports the expected symbols."""

    def test_module_is_importable(self) -> None:
        """beddel.serve is importable without errors."""
        import beddel.serve  # noqa: F401

    def test_exports_i_agent_runtime_adapter(self) -> None:
        """beddel.serve exports IAgentRuntimeAdapter."""
        import beddel.serve

        assert hasattr(beddel.serve, "IAgentRuntimeAdapter")

    def test_exports_agent_info(self) -> None:
        """beddel.serve exports AgentInfo."""
        import beddel.serve

        assert hasattr(beddel.serve, "AgentInfo")

    def test_exports_chat_chunk(self) -> None:
        """beddel.serve exports ChatChunk."""
        import beddel.serve

        assert hasattr(beddel.serve, "ChatChunk")

    def test_all_contains_expected_symbols(self) -> None:
        """beddel.serve.__all__ contains the expected public symbols."""
        import beddel.serve

        expected = {
            "IAgentRuntimeAdapter",
            "AgentInfo",
            "ChatChunk",
            "VertexAgentEngineAdapter",
            "register_agent_engine_routes",
        }
        assert set(beddel.serve.__all__) == expected


# ---------------------------------------------------------------------------
# Import boundary: domain/ must never import from beddel.serve
# ---------------------------------------------------------------------------


class TestImportBoundary:
    """Enforces that no file in beddel/domain/ imports from beddel.serve."""

    def test_no_domain_file_imports_beddel_serve(self) -> None:
        """Scan all .py files in domain/ for forbidden imports from beddel.serve."""
        # Resolve from tests/serve/ → src/beddel/domain/
        domain_dir = Path(__file__).resolve().parents[2] / "src" / "beddel" / "domain"
        assert domain_dir.is_dir(), f"domain dir not found: {domain_dir}"

        violations: list[str] = []
        for py_file in sorted(domain_dir.rglob("*.py")):
            lines = py_file.read_text(encoding="utf-8").splitlines()
            for line_no, line in enumerate(lines, start=1):
                stripped = line.strip()
                # Skip comments
                if stripped.startswith("#"):
                    continue
                if "beddel.serve" in stripped or "from beddel.serve" in stripped:
                    violations.append(f"{py_file.name}:{line_no}: {stripped}")

        assert violations == [], (
            "domain/ must not import from beddel.serve. Violations:\n" + "\n".join(violations)
        )
