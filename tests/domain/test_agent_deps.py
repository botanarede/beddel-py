"""Unit tests for DefaultDependencies agent adapter integration.

Complements the basic agent property tests in test_models.py with
integration-level scenarios: combined parameters, protocol-conforming
mocks, multi-adapter registries, and full-parameter construction.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.models import AgentResult, DefaultDependencies
from beddel.domain.ports import IAgentAdapter, NoOpTracer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAgentAdapter:
    """Minimal IAgentAdapter-conforming adapter for testing."""

    def __init__(self, agent_id: str = "fake") -> None:
        self._agent_id = agent_id

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Return a canned result."""
        return AgentResult(
            exit_code=0,
            output=prompt,
            events=[],
            files_changed=[],
            usage={},
            agent_id=self._agent_id,
        )

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield a single event."""
        yield {"type": "done"}


# ---------------------------------------------------------------------------
# Combined agent parameters
# ---------------------------------------------------------------------------


class TestAgentDependenciesCombined:
    """Tests for DefaultDependencies with combined agent adapter + registry."""

    def test_adapter_and_registry_together(self) -> None:
        """Both agent_adapter and agent_registry can be set simultaneously."""
        adapter = _FakeAgentAdapter("default")
        registry = {"codex": _FakeAgentAdapter("codex")}

        deps = DefaultDependencies(agent_adapter=adapter, agent_registry=registry)

        assert deps.agent_adapter is adapter
        assert deps.agent_registry is registry

    def test_adapter_conforms_to_protocol(self) -> None:
        """A protocol-conforming adapter stored in deps passes isinstance check."""
        adapter = _FakeAgentAdapter("proto")
        deps = DefaultDependencies(agent_adapter=adapter)

        assert isinstance(deps.agent_adapter, IAgentAdapter)

    def test_registry_adapters_conform_to_protocol(self) -> None:
        """All adapters in agent_registry satisfy IAgentAdapter protocol."""
        registry = {
            "codex": _FakeAgentAdapter("codex"),
            "claude": _FakeAgentAdapter("claude"),
            "openclaw": _FakeAgentAdapter("openclaw"),
        }
        deps = DefaultDependencies(agent_registry=registry)

        assert deps.agent_registry is not None
        for name, adapter in deps.agent_registry.items():
            assert isinstance(adapter, IAgentAdapter), f"{name} is not IAgentAdapter"

    def test_registry_key_lookup(self) -> None:
        """Individual adapters are retrievable by key from agent_registry."""
        codex = _FakeAgentAdapter("codex")
        claude = _FakeAgentAdapter("claude")
        deps = DefaultDependencies(agent_registry={"codex": codex, "claude": claude})

        assert deps.agent_registry is not None
        assert deps.agent_registry["codex"] is codex
        assert deps.agent_registry["claude"] is claude
        assert len(deps.agent_registry) == 2

    def test_agent_properties_independent(self) -> None:
        """Setting agent_adapter does not affect agent_registry and vice versa."""
        adapter = _FakeAgentAdapter("solo")
        deps_adapter_only = DefaultDependencies(agent_adapter=adapter)
        deps_registry_only = DefaultDependencies(
            agent_registry={"x": _FakeAgentAdapter("x")},
        )

        assert deps_adapter_only.agent_registry is None
        assert deps_registry_only.agent_adapter is None

    def test_full_construction_with_agent_params(self) -> None:
        """DefaultDependencies with ALL params including agent ones works."""
        adapter = _FakeAgentAdapter("full")
        registry = {"a": _FakeAgentAdapter("a")}
        tracer = NoOpTracer()

        deps = DefaultDependencies(
            delegate_model="gpt-4o",
            tracer=tracer,
            agent_adapter=adapter,
            agent_registry=registry,
        )

        assert deps.delegate_model == "gpt-4o"
        assert deps.tracer is tracer
        assert deps.agent_adapter is adapter
        assert deps.agent_registry is registry
        assert deps.llm_provider is None
        assert deps.lifecycle_hooks is None

    def test_backward_compat_no_agent_params(self) -> None:
        """Pre-agent DefaultDependencies() calls still work without regressions."""
        deps = DefaultDependencies(delegate_model="gpt-4o-mini", tracer=NoOpTracer())

        assert deps.delegate_model == "gpt-4o-mini"
        assert deps.tracer is not None
        assert deps.agent_adapter is None
        assert deps.agent_registry is None
